/* Experimental rigid-camera cadence correction. LGPL-2.1-or-later. */
#include "camera_motion.h"
#include "camera_motion_shaders.h"
#include <stdlib.h>
#include <string.h>

#define SLOTS 8
struct frame_slot {
    uint64_t signature, before, age;
    bool valid, paired;
    int width, height;
    pl_tex pyramid[3], motion;
};

struct ajn_camera {
    pl_gpu gpu;
    pl_dispatch dispatch;
    uint64_t clock;
    bool rigid;
    struct frame_slot slots[SLOTS];
    pl_tex points, forward, backward, weights;
};

static bool ensure_tex(struct ajn_camera *c, pl_tex *tex, int w, int h, int components)
{
    if (*tex) return true;
    pl_fmt fmt=pl_find_fmt(c->gpu,PL_FMT_FLOAT,components,components==1?16:32,0,
                         PL_FMT_CAP_SAMPLEABLE|PL_FMT_CAP_STORABLE|PL_FMT_CAP_LINEAR);
    if (!fmt) return false;
    *tex=pl_tex_create(c->gpu,pl_tex_params(.w=w,.h=h,.format=fmt,
                                           .sampleable=true,.storable=true));
    return *tex!=NULL;
}

static struct pl_shader_desc sampled(const char *name,pl_tex tex)
{
    return (struct pl_shader_desc){
        .desc={.name=name,.type=PL_DESC_SAMPLED_TEX},
        .binding={.object=tex,.sample_mode=PL_TEX_SAMPLE_LINEAR,
                  .address_mode=PL_TEX_ADDRESS_CLAMP}};
}

static struct pl_shader_desc output(pl_tex tex)
{
    return (struct pl_shader_desc){
        .desc={.name="dst",.type=PL_DESC_STORAGE_IMG,.access=PL_DESC_ACCESS_WRITEONLY},
        .binding={.object=tex}};
}

static bool run(struct ajn_camera *c,const char *name,const char *header,const char *body,
                struct pl_shader_desc *descs,int nd,struct pl_shader_var *vars,int nv,
                int gx,int gy,int dx,int dy,size_t shared)
{
    pl_shader sh=pl_dispatch_begin(c->dispatch);
    struct pl_custom_shader program={
        .description=name,.header=header,.body=body,
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_NONE,
        .compute=true,.compute_group_size={gx,gy},.compute_shmem=shared,
        .descriptors=descs,.num_descriptors=nd,.variables=vars,.num_variables=nv};
    if (!pl_shader_custom(sh,&program)) {
        pl_dispatch_abort(c->dispatch,&sh);
        return false;
    }
    return pl_dispatch_compute(c->dispatch,pl_dispatch_compute_params(
        .shader=&sh,.dispatch_size={dx,dy,1}));
}

struct ajn_camera *ajn_camera_create(pl_gpu gpu,pl_dispatch dispatch)
{
    struct ajn_camera *c=calloc(1,sizeof(*c));
    if (!c) return NULL;
    c->gpu=gpu;
    c->dispatch=dispatch;
    return c;
}

void ajn_camera_destroy(struct ajn_camera **pc)
{
    struct ajn_camera *c=*pc;
    if (!c) return;
    for (int i=0;i<SLOTS;i++) {
        for (int j=0;j<3;j++) pl_tex_destroy(c->gpu,&c->slots[i].pyramid[j]);
        pl_tex_destroy(c->gpu,&c->slots[i].motion);
    }
    pl_tex_destroy(c->gpu,&c->points);
    pl_tex_destroy(c->gpu,&c->forward);
    pl_tex_destroy(c->gpu,&c->backward);
    pl_tex_destroy(c->gpu,&c->weights);
    free(c);
    *pc=NULL;
}

void ajn_camera_reset(struct ajn_camera *c)
{
    if (!c) return;
    for (int i=0;i<SLOTS;i++) c->slots[i].valid=c->slots[i].paired=false;
}

void ajn_camera_set_rigid(struct ajn_camera *c,bool rigid)
{
    if (c->rigid != rigid) {
        ajn_camera_reset(c);
        c->rigid = rigid;
    }
}

static struct frame_slot *find(struct ajn_camera *c,uint64_t signature)
{
    for (int i=0;i<SLOTS;i++)
        if (c->slots[i].valid && c->slots[i].signature==signature) return &c->slots[i];
    return NULL;
}

bool ajn_camera_frame(struct ajn_camera *c,uint64_t signature,pl_tex frame)
{
    struct frame_slot *f=find(c,signature);
    if (f && f->width==frame->params.w && f->height==frame->params.h) {
        f->age=++c->clock;
        return true;
    }
    if (!f) {
        f=&c->slots[0];
        for (int i=0;i<SLOTS;i++) {
            if (!c->slots[i].valid) { f=&c->slots[i]; break; }
            if (c->slots[i].age<f->age) f=&c->slots[i];
        }
    }
    f->valid=f->paired=false;
    for (int i=0;i<3;i++) {
        int w=640>>i,h=360>>i;
        if (!ensure_tex(c,&f->pyramid[i],w,h,1)) return false;
        int rgb=i==0;
        struct pl_shader_desc d[]={sampled("src",i?f->pyramid[i-1]:frame),output(f->pyramid[i])};
        struct pl_shader_var v={.var=pl_var_int("rgb_source"),.data=&rgb};
        if (!run(c,"camera motion: luma pyramid",cm_pyramid_glsl,"run_pyramid();",d,2,&v,1,16,16,(w+15)/16,(h+15)/16,0))
            return false;
    }
    f->signature=signature;
    f->age=++c->clock;
    f->width=frame->params.w;
    f->height=frame->params.h;
    f->valid=true;
    return true;
}

pl_tex ajn_camera_pair(struct ajn_camera *c,uint64_t before,uint64_t after)
{
    struct frame_slot *a=find(c,before),*b=find(c,after);
    if (!a || !b || a->width!=b->width || a->height!=b->height) return NULL;
    if (b->paired && b->before==before) return b->motion;
    if (!ensure_tex(c,&c->points,128,1,4) || !ensure_tex(c,&c->forward,128,1,4) ||
        !ensure_tex(c,&c->backward,128,1,4) || !ensure_tex(c,&b->motion,16,9,4)) return NULL;
    struct pl_shader_desc features[]={sampled("src",a->pyramid[0]),output(c->points)};
    if (!run(c,"camera motion: features",cm_features_glsl,"run_features();",features,2,NULL,0,64,1,128,1,64*16))
        return NULL;
    for (int reverse=0;reverse<2;reverse++) {
        struct frame_slot *from=reverse?b:a,*to=reverse?a:b;
        struct pl_shader_desc track[]={
            sampled("a0",from->pyramid[0]),sampled("a1",from->pyramid[1]),sampled("a2",from->pyramid[2]),
            sampled("b0",to->pyramid[0]),sampled("b1",to->pyramid[1]),sampled("b2",to->pyramid[2]),
            sampled("points",c->points),output(reverse?c->backward:c->forward),
            sampled("forward_flow",c->forward)};
        struct pl_shader_var v={.var=pl_var_int("reverse_pass"),.data=&reverse};
        if (!run(c,"camera motion: track",reverse?cm_track_reverse_glsl:cm_track_glsl,"run_track();",track,reverse?9:8,&v,1,128,1,128,1,128*24+32))
            return NULL;
    }
    int history_valid=a->paired;
    struct pl_shader_desc reduce[]={sampled("forward_flow",c->forward),sampled("backward_flow",c->backward),
                                    sampled("points",c->points),output(b->motion),
                                    // Compare at the existing coarser level:
                                    // full-resolution detail must not turn
                                    // subpixel resampling into false animation.
                                    sampled("luma_before",a->pyramid[1]),sampled("luma_after",b->pyramid[1]),
                                    // Bind an unused luma level for the first
                                    // pair; the uniform prevents reading it.
                                    sampled("history",a->paired?a->motion:a->pyramid[2])};
    int rigid=c->rigid;
    struct pl_shader_var uniforms[]={
        {.var=pl_var_int("history_valid"),.data=&history_valid},
        {.var=pl_var_int("rigid_pan"),.data=&rigid}};
    if (!run(c,"camera motion: consensus",cm_consensus_glsl,"run_consensus();",reduce,7,uniforms,2,128,1,1,1,128*32+48))
        return NULL;
    b->before=before;
    b->paired=true;
    return b->motion;
}

bool ajn_camera_sample(struct ajn_camera *c,pl_shader sh,pl_tex base,pl_tex neighbor,pl_tex motion,float fraction)
{
    if (!ensure_tex(c,&c->weights,9,1,4)) return false;
    float size[2]={base->params.w,base->params.h};
    int rigid=c->rigid;
    struct pl_shader_desc d[]={sampled("motion",motion),output(c->weights)};
    struct pl_shader_var v[]={
        {.var=pl_var_vec2("image_size"),.data=size,.dynamic=true},
        {.var=pl_var_float("fraction"),.data=&fraction,.dynamic=true},
        {.var=pl_var_int("rigid_pan"),.data=&rigid}};
    if (!run(c,"camera motion: sampling weights",cm_weights_glsl,"run_weights();",d,2,v,3,1,1,1,1,0)) return false;
    float coords[4][2]={{0,0},{1,0},{0,1},{1,1}};
    struct pl_shader_va position={.attr={.name="pos",.fmt=pl_find_vertex_fmt(c->gpu,PL_FMT_FLOAT,2)},
                                  .data={coords[0],coords[1],coords[2],coords[3]}};
    struct pl_shader_desc inputs[]={sampled("base",base),sampled("neighbor",neighbor),
                                    sampled("motion",motion),sampled("weights",c->weights)};
    struct pl_shader_var sampling[]={v[1],
        {.var=pl_var_int("rigid_pan"),.data=&rigid}};
    struct pl_custom_shader program={
        .description="camera motion: Lanczos4 presentation",
        .header=cm_sample_glsl,.body="color = sample_camera();",
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_COLOR,
        .descriptors=inputs,.num_descriptors=4,.variables=sampling,.num_variables=2,
        .vertex_attribs=&position,.num_vertex_attribs=1,
        .output_w=base->params.w,.output_h=base->params.h};
    return pl_shader_custom(sh,&program);
}
