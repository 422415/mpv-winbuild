// Standalone test of the production GPU kernels. No video/flow downloads.
// Only a GPU-computed assertion result and GPU timing queries reach the host.
#include <libplacebo/vulkan.h>
#include "camera_motion.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAILED %s:%d: %s\n",__FILE__,__LINE__,#x); exit(1); } } while(0)
static void logger(void *p,enum pl_log_level level,const char *text) { fprintf(stderr,"%s\n",text); }
struct measurement { char name[160]; double sum,peak; int count; };
static struct measurement timings[32];
static int timing_count;
static void collect(void *p,const struct pl_dispatch_info *info) {
    if (!info->num_samples || !info->last) return;
    const char *name=info->shader->description;
    if (!name || !strstr(name,"camera motion:")) return;
    int i;
    for(i=0;i<timing_count;i++) if(!strcmp(name,timings[i].name)) break;
    if(i==timing_count) { CHECK(i<32); snprintf(timings[i].name,sizeof(timings[i].name),"%s",name); timing_count++; }
    double ms=info->last/1e6;
    timings[i].sum+=ms; timings[i].count++;
    if(ms>timings[i].peak) timings[i].peak=ms;
}

static struct pl_shader_desc read_tex(const char *name,pl_tex tex) {
    return (struct pl_shader_desc){.desc={.name=name,.type=PL_DESC_SAMPLED_TEX},
        .binding={.object=tex,.sample_mode=PL_TEX_SAMPLE_LINEAR}};
}
static struct pl_shader_desc write_tex(pl_tex tex) {
    return (struct pl_shader_desc){.desc={.name="dst",.type=PL_DESC_STORAGE_IMG,.access=PL_DESC_ACCESS_WRITEONLY},
        .binding={.object=tex}};
}
static void generate(pl_dispatch dp,pl_tex tex,float dx,float dy,int cut) {
    const char *body=
        "ivec2 p=ivec2(gl_GlobalInvocationID.xy); ivec2 s=imageSize(dst);"
        "if(all(lessThan(p,s))) {"
        "vec2 q=(vec2(p)+0.5)/vec2(s)*vec2(640,360)-offset;"
        "float c=0.45+0.18*cos(q.x*0.15)*cos(q.y*0.37)+0.12*sin(q.x*0.07+q.y*0.08)+0.1*sin(q.x*0.43)*cos(q.y*0.24);"
        "if(cut==1) c=0.5+0.25*cos(q.y*0.11)*sin(q.x*0.31+q.y*0.52);"
        // A held foreground drawing over a moving background. Most tracked
        // features still agree with the background, but warping both is wrong.
        "vec2 stationary=(vec2(p)+0.5)/vec2(s)*vec2(640,360);"
        "if(cut==2 && all(greaterThan(stationary,vec2(230,135))) && all(lessThan(stationary,vec2(330,215))))"
        " c=0.3+0.25*cos(stationary.x*0.5)*sin(stationary.y*0.4);"
        // A small animated meteor over a genuine camera pan. Its original
        // drawing must survive, without disabling the background's camera.
        "vec2 star=stationary-vec2(90+offset.x*8,85-offset.y*20);"
        "if(cut==3 && dot(star,star)<64.0) c=1.0;"
        // A smooth area contains weak stationary texture, as with grain in
        // flat anime shading. It must not outvote clear translating detail.
        "if(cut==4 && stationary.x>400.0)"
        " c=0.45+0.015*sin(stationary.x*0.73)*cos(stationary.y*0.59);"
        // A large drawing changes once while the background keeps panning.
        // Each pose is held over adjacent frames, as in animation on threes.
        "if(cut==5 && all(greaterThan(q,vec2(175,75))) && all(lessThan(q,vec2(455,285)))) {"
        " float pose=offset.x>=7.0?1.0:0.0;"
        " c=0.4+0.25*cos(q.x*0.41+pose*2.0)*sin(q.y*0.33+pose); }"
        "imageStore(dst,p,vec4(c,c,c,1)); }";
    pl_shader sh=pl_dispatch_begin(dp);
    float offset[2]={dx,dy};
    struct pl_shader_desc d=write_tex(tex);
    struct pl_shader_var v[]={ {.var=pl_var_vec2("offset"),.data=offset}, {.var=pl_var_int("cut"),.data=&cut} };
    struct pl_custom_shader cs={.description="GPU-generated test fixture",.body=body,
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_NONE,.compute=true,.compute_group_size={16,16},
        .descriptors=&d,.num_descriptors=1,.variables=v,.num_variables=2};
    CHECK(pl_shader_custom(sh,&cs));
    CHECK(pl_dispatch_compute(dp,pl_dispatch_compute_params(.shader=&sh,.dispatch_size={(tex->params.w+15)/16,(tex->params.h+15)/16,1})));
}

static void verify(pl_gpu gpu,pl_dispatch dp,pl_tex motion,bool expect_motion,const char *label) {
    pl_fmt fmt=pl_find_fmt(gpu,PL_FMT_FLOAT,4,32,32,PL_FMT_CAP_STORABLE|PL_FMT_CAP_HOST_READABLE);
    CHECK(fmt);
    pl_tex assertion=pl_tex_create(gpu,pl_tex_params(.w=1,.h=1,.format=fmt,.storable=true,.host_readable=true));
    CHECK(assertion);
    struct pl_shader_desc d[]={read_tex("flow",motion),write_tex(assertion)};
    int expect=expect_motion;
    struct pl_shader_var v={.var=pl_var_int("expect_motion"),.data=&expect};
    pl_shader sh=pl_dispatch_begin(dp);
    struct pl_custom_shader cs={.description="GPU assertion",.compute=true,.compute_group_size={1,1},
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_NONE,.descriptors=d,.num_descriptors=2,.variables=&v,.num_variables=1,
        .body="vec4 f=texelFetch(flow,ivec2(0),0); float error=length(f.xy*vec2(640,360)-vec2(1.8,0.25));"
              "bool ok=expect_motion!=0 ? (f.z>0.5 && error<0.2) : f.z<0.5;"
              "imageStore(dst,ivec2(0),vec4(ok ? 1.0:0.0,error,0,0));"};
    CHECK(pl_shader_custom(sh,&cs));
    CHECK(pl_dispatch_compute(dp,pl_dispatch_compute_params(.shader=&sh,.dispatch_size={1,1,1})));
    float result[4];
    CHECK(pl_tex_download(gpu,pl_tex_transfer_params(.tex=assertion,.ptr=result)));
    printf("GPU assertion %s: %s, tracking error %.6f analysis pixels\n",label,result[0]>0.5?"PASS":"FAIL",result[1]);
    fflush(stdout);
    CHECK(result[0]>0.5);
    pl_tex_destroy(gpu,&assertion);
}

static void verify_sample(pl_gpu gpu,pl_dispatch dp,pl_tex tex,float fraction) {
    pl_fmt fmt=pl_find_fmt(gpu,PL_FMT_FLOAT,4,32,32,PL_FMT_CAP_STORABLE|PL_FMT_CAP_HOST_READABLE);
    pl_tex assertion=pl_tex_create(gpu,pl_tex_params(.w=1,.h=1,.format=fmt,.storable=true,.host_readable=true));
    CHECK(assertion);
    struct pl_shader_desc d[]={read_tex("picture",tex),write_tex(assertion)};
    struct pl_shader_var phase={.var=pl_var_float("phase"),.data=&fraction};
    pl_shader sh=pl_dispatch_begin(dp);
    struct pl_custom_shader cs={.description="GPU presentation assertion",.compute=true,.compute_group_size={1,1},
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_NONE,.descriptors=d,.num_descriptors=2,
        .variables=&phase,.num_variables=1,
        .body="ivec2 s=textureSize(picture,0); float error=0.0;"
              "for(int i=0;i<16;i++) { ivec2 p=s/4+ivec2(i%4,i/4)*32;"
              "vec2 q=(vec2(p)+0.5)/vec2(s)*vec2(640,360)-vec2(1.8,0.25)*phase;"
              "float expected=0.45+0.18*cos(q.x*0.15)*cos(q.y*0.37)+0.12*sin(q.x*0.07+q.y*0.08)+0.1*sin(q.x*0.43)*cos(q.y*0.24);"
              "error=max(error,abs(texelFetch(picture,p,0).r-expected)); }"
              "imageStore(dst,ivec2(0),vec4(error<0.003 ? 1.0:0.0,error,0,0));"};
    CHECK(pl_shader_custom(sh,&cs));
    CHECK(pl_dispatch_compute(dp,pl_dispatch_compute_params(.shader=&sh,.dispatch_size={1,1,1})));
    float result[4]; CHECK(pl_tex_download(gpu,pl_tex_transfer_params(.tex=assertion,.ptr=result)));
    printf("GPU assertion presentation: %s, maximum luma error %.6f\n",result[0]>0.5?"PASS":"FAIL",result[1]);
    CHECK(result[0]>0.5);
    pl_tex_destroy(gpu,&assertion);
}

static void verify_protected_sample(pl_gpu gpu,pl_dispatch dp,pl_tex base,pl_tex picture) {
    pl_fmt fmt=pl_find_fmt(gpu,PL_FMT_FLOAT,4,32,32,PL_FMT_CAP_STORABLE|PL_FMT_CAP_HOST_READABLE);
    pl_tex assertion=pl_tex_create(gpu,pl_tex_params(.w=1,.h=1,.format=fmt,.storable=true,.host_readable=true)); CHECK(assertion);
    struct pl_shader_desc d[]={read_tex("base",base),read_tex("picture",picture),write_tex(assertion)};
    pl_shader sh=pl_dispatch_begin(dp);
    struct pl_custom_shader cs={.description="GPU protected foreground assertion",.compute=true,.compute_group_size={1,1},
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_NONE,.descriptors=d,.num_descriptors=3,
        .body="ivec2 s=textureSize(picture,0); float foreground=0.0,background=0.0;"
              "for(int y=136;y<215;y+=3) for(int x=231;x<330;x+=3) {"
              "ivec2 p=ivec2(vec2(x,y)/vec2(640,360)*vec2(s));"
              "foreground=max(foreground,abs(texelFetch(picture,p,0).r-texelFetch(base,p,0).r)); }"
              "for(int i=0;i<16;i++) { ivec2 p=ivec2(vec2(60+i%4*20,45+i/4*15)/vec2(640,360)*vec2(s));"
              "vec2 q=(vec2(p)+0.5)/vec2(s)*vec2(640,360)-vec2(1.8,0.25)*4.37;"
              "float expected=0.45+0.18*cos(q.x*0.15)*cos(q.y*0.37)+0.12*sin(q.x*0.07+q.y*0.08)+0.1*sin(q.x*0.43)*cos(q.y*0.24);"
              "background=max(background,abs(texelFetch(picture,p,0).r-expected)); }"
              "imageStore(dst,ivec2(0),vec4(foreground<1e-6 && background<0.003 ? 1.0:0.0,foreground,background,0));"};
    CHECK(pl_shader_custom(sh,&cs));
    CHECK(pl_dispatch_compute(dp,pl_dispatch_compute_params(.shader=&sh,.dispatch_size={1,1,1})));
    float result[4]; CHECK(pl_tex_download(gpu,pl_tex_transfer_params(.tex=assertion,.ptr=result)));
    printf("GPU assertion protected foreground: %s, foreground error %.6f, background error %.6f\n",result[0]>.5?"PASS":"FAIL",result[1],result[2]);
    CHECK(result[0]>.5); pl_tex_destroy(gpu,&assertion);
}

static void verify_animated_drawing(pl_gpu gpu,pl_dispatch dp,pl_tex picture,float fraction,bool after) {
    pl_fmt fmt=pl_find_fmt(gpu,PL_FMT_FLOAT,4,32,32,PL_FMT_CAP_STORABLE|PL_FMT_CAP_HOST_READABLE);
    pl_tex assertion=pl_tex_create(gpu,pl_tex_params(.w=1,.h=1,.format=fmt,.storable=true,.host_readable=true)); CHECK(assertion);
    struct pl_shader_desc d[]={read_tex("picture",picture),write_tex(assertion)};
    float source=after?5:4,other=after?4:5;
    struct pl_shader_var v[]={
        {.var=pl_var_float("phase"),.data=&fraction},
        {.var=pl_var_float("source_frame"),.data=&source},
        {.var=pl_var_float("other_frame"),.data=&other}};
    pl_shader sh=pl_dispatch_begin(dp);
    struct pl_custom_shader cs={.description="GPU original drawing assertion",.compute=true,.compute_group_size={1,1},
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_NONE,.descriptors=d,.num_descriptors=2,.variables=v,.num_variables=3,
        .body="vec2 s=vec2(textureSize(picture,0));"
              "vec2 shift=vec2(1.8,0.25)*phase;"
              "vec2 original_pos=vec2(90+source_frame*14.4,85-source_frame*5)+shift;"
              "vec2 other_pos=vec2(90+other_frame*14.4,85-other_frame*5)+shift;"
              "float original=texelFetch(picture,ivec2(original_pos/vec2(640,360)*s),0).r;"
              "float future=texelFetch(picture,ivec2(other_pos/vec2(640,360)*s),0).r;"
              "imageStore(dst,ivec2(0),vec4(original>0.98 && future<0.90 ? 1.0:0.0,original,future,0));"};
    CHECK(pl_shader_custom(sh,&cs));
    CHECK(pl_dispatch_compute(dp,pl_dispatch_compute_params(.shader=&sh,.dispatch_size={1,1,1})));
    float result[4]; CHECK(pl_tex_download(gpu,pl_tex_transfer_params(.tex=assertion,.ptr=result)));
    printf("GPU assertion original animated drawing: %s, original %.6f, future %.6f\n",result[0]>.5?"PASS":"FAIL",result[1],result[2]);
    CHECK(result[0]>.5); pl_tex_destroy(gpu,&assertion);
}

static void verify_unchanged(pl_gpu gpu,pl_dispatch dp,pl_tex base,pl_tex picture) {
    pl_fmt fmt=pl_find_fmt(gpu,PL_FMT_FLOAT,4,32,32,PL_FMT_CAP_STORABLE|PL_FMT_CAP_HOST_READABLE);
    pl_tex assertion=pl_tex_create(gpu,pl_tex_params(.w=1,.h=1,.format=fmt,.storable=true,.host_readable=true)); CHECK(assertion);
    struct pl_shader_desc d[]={read_tex("base",base),read_tex("picture",picture),write_tex(assertion)};
    pl_shader sh=pl_dispatch_begin(dp);
    struct pl_custom_shader cs={.description="GPU unchanged drawing assertion",.compute=true,.compute_group_size={1,1},
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_NONE,.descriptors=d,.num_descriptors=3,
        .body="ivec2 s=textureSize(picture,0); float error=0.0;"
              "for(int y=1;y<16;y++) for(int x=1;x<16;x++) { ivec2 p=s*ivec2(x,y)/16;"
              "error=max(error,length(texelFetch(base,p,0)-texelFetch(picture,p,0))); }"
              "imageStore(dst,ivec2(0),vec4(error==0.0 ? 1.0:0.0,error,0,0));"};
    CHECK(pl_shader_custom(sh,&cs));
    CHECK(pl_dispatch_compute(dp,pl_dispatch_compute_params(.shader=&sh,.dispatch_size={1,1,1})));
    float result[4]; CHECK(pl_tex_download(gpu,pl_tex_transfer_params(.tex=assertion,.ptr=result)));
    printf("GPU assertion negligible motion leaves drawing unchanged: %s, error %.6f\n",result[0]>.5?"PASS":"FAIL",result[1]);
    CHECK(result[0]>.5); pl_tex_destroy(gpu,&assertion);
}

static void verify_redraw_sample(pl_gpu gpu,pl_dispatch dp,pl_tex picture,float dx,float dy) {
    pl_fmt fmt=pl_find_fmt(gpu,PL_FMT_FLOAT,4,32,32,PL_FMT_CAP_STORABLE|PL_FMT_CAP_HOST_READABLE);
    pl_tex assertion=pl_tex_create(gpu,pl_tex_params(.w=1,.h=1,.format=fmt,.storable=true,.host_readable=true)); CHECK(assertion);
    struct pl_shader_desc d[]={read_tex("picture",picture),write_tex(assertion)};
    float offset[2]={dx,dy};
    struct pl_shader_var v={.var=pl_var_vec2("camera_offset"),.data=offset};
    pl_shader sh=pl_dispatch_begin(dp);
    struct pl_custom_shader cs={.description="GPU redraw continuity assertion",.compute=true,.compute_group_size={1,1},
        .input=PL_SHADER_SIG_NONE,.output=PL_SHADER_SIG_NONE,.descriptors=d,.num_descriptors=2,
        .variables=&v,.num_variables=1,
        .body="ivec2 s=textureSize(picture,0); float error=0.0;"
              "for(int y=0;y<8;y++) for(int x=0;x<8;x++) {"
              "ivec2 p=ivec2(vec2(45+x*72,40+y*40)/vec2(640,360)*vec2(s));"
              "vec2 q=(vec2(p)+0.5)/vec2(s)*vec2(640,360)-camera_offset;"
              "float c=0.45+0.18*cos(q.x*0.15)*cos(q.y*0.37)+0.12*sin(q.x*0.07+q.y*0.08)+0.1*sin(q.x*0.43)*cos(q.y*0.24);"
              "if(all(greaterThan(q,vec2(175,75))) && all(lessThan(q,vec2(455,285))))"
              " c=0.4+0.25*cos(q.x*0.41)*sin(q.y*0.33);"
              "error=max(error,abs(texelFetch(picture,p,0).r-c)); }"
              "imageStore(dst,ivec2(0),vec4(error<0.004?1.0:0.0,error,0,0));"};
    CHECK(pl_shader_custom(sh,&cs));
    CHECK(pl_dispatch_compute(dp,pl_dispatch_compute_params(.shader=&sh,.dispatch_size={1,1,1})));
    float result[4]; CHECK(pl_tex_download(gpu,pl_tex_transfer_params(.tex=assertion,.ptr=result)));
    printf("GPU assertion pan across large redraw retains original pose: %s, error %.6f\n",result[0]>.5?"PASS":"FAIL",result[1]);
    CHECK(result[0]>.5); pl_tex_destroy(gpu,&assertion);
}

// Prime a connected, coherent source history ending with a at offset zero
// and b at (1.8, .25), so presentation assertions keep their analytic target.
static pl_tex coherent_pair(struct ajn_camera *camera,pl_dispatch dp,pl_tex a,pl_tex b) {
    ajn_camera_reset(camera);
    pl_tex motion=NULL;
    for(int i=0;i<4;i++) {
        pl_tex tex=i==3?b:a;
        generate(dp,tex,(i-2)*1.8f,(i-2)*0.25f,0);
        CHECK(ajn_camera_frame(camera,i+1,tex));
        if(i) { motion=ajn_camera_pair(camera,i,i+1); CHECK(motion); }
    }
    return motion;
}

int main(int argc,char **argv) {
    int w=argc>1?atoi(argv[1]):1920,h=argc>2?atoi(argv[2]):1080;
    pl_log log=pl_log_create(PL_API_VER,pl_log_params(.log_cb=logger,.log_level=PL_LOG_WARN));
    pl_vulkan vk=pl_vulkan_create(log,pl_vulkan_params(.queue_count=3)); CHECK(vk);
    pl_gpu gpu=vk->gpu;
    pl_dispatch dp=pl_dispatch_create(log,gpu); CHECK(dp);
    pl_dispatch_callback(dp,NULL,collect);
    struct ajn_camera *camera=ajn_camera_create(gpu,dp); CHECK(camera);
    pl_fmt fmt=pl_find_fmt(gpu,PL_FMT_FLOAT,4,16,0,PL_FMT_CAP_STORABLE|PL_FMT_CAP_SAMPLEABLE|PL_FMT_CAP_RENDERABLE|PL_FMT_CAP_LINEAR); CHECK(fmt);
    pl_tex a=pl_tex_create(gpu,pl_tex_params(.w=w,.h=h,.format=fmt,.sampleable=true,.storable=true));
    pl_tex b=pl_tex_create(gpu,pl_tex_params(.w=w,.h=h,.format=fmt,.sampleable=true,.storable=true));
    pl_tex out=pl_tex_create(gpu,pl_tex_params(.w=w,.h=h,.format=fmt,.renderable=true,.sampleable=true));
    CHECK(a && b && out);
    generate(dp,a,0,0,0); generate(dp,b,1.8,0.25,0);
    CHECK(ajn_camera_frame(camera,1,a)); CHECK(ajn_camera_frame(camera,2,b));
    pl_tex motion=ajn_camera_pair(camera,1,2); CHECK(motion);
    verify(gpu,dp,motion,false,"isolated good pair");
    for(int i=0;i<8;i++) motion=ajn_camera_pair(camera,1,2);
    verify(gpu,dp,motion,false,"cached repeats do not establish a pan");
    motion=coherent_pair(camera,dp,a,b);
    verify(gpu,dp,motion,true,"translation");
    for(int reverse=0;reverse<2;reverse++) {
        pl_shader sh=pl_dispatch_begin(dp);
        CHECK(ajn_camera_sample(camera,sh,reverse?b:a,reverse?a:b,motion,reverse?-0.63f:0.37f));
        CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&sh,.target=out)));
        verify_sample(gpu,dp,out,0.37f);
    }
    for(int k=0;k<76;k++) {
        if(k==12) { pl_gpu_finish(gpu); timing_count=0; memset(timings,0,sizeof(timings)); }
        // Rebuild a coherent source history; timings are per GPU pass, with
        // the warmed correction active rather than profiling the cold bypass.
        if(k%5==0 || k%5==3) {
            motion=coherent_pair(camera,dp,a,b);
        }
        pl_shader sh=pl_dispatch_begin(dp);
        CHECK(ajn_camera_sample(camera,sh,a,b,motion,0.37f));
        CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&sh,.target=out)));
        pl_gpu_flush(gpu);
    }
    pl_gpu_finish(gpu);
    printf("resolution %dx%d; three GPU queues; warmed GPU pass timings\n",w,h);
    for(int i=0;i<timing_count;i++)
        printf("%s: mean=%.6f ms peak=%.6f ms observations=%d\n",timings[i].name,timings[i].sum/timings[i].count,timings[i].peak,timings[i].count);
    // Reject a cut from an already mature pan, without resetting its cache.
    generate(dp,a,0,0,1); CHECK(ajn_camera_frame(camera,5,a));
    motion=ajn_camera_pair(camera,4,5); CHECK(motion); verify(gpu,dp,motion,false,"cut");
    // One good pair after a rejected scene must not immediately reactivate.
    generate(dp,b,1.8,0.25,1); CHECK(ajn_camera_frame(camera,6,b));
    motion=ajn_camera_pair(camera,5,6); CHECK(motion);
    verify(gpu,dp,motion,false,"isolated reactivation after rejection");
    // Keep the independently moving foreground fixture connected long enough
    // that a failure cannot be hidden by the history warm-up requirement.
    ajn_camera_reset(camera);
    for(int i=0;i<6;i++) {
        pl_tex tex=i%2?b:a;
        generate(dp,tex,i*1.8f,i*0.25f,2);
        CHECK(ajn_camera_frame(camera,i+1,tex));
        if(i) { motion=ajn_camera_pair(camera,i,i+1); CHECK(motion); }
    }
    verify(gpu,dp,motion,true,"background pan with a protected foreground");
    for(int reverse=0;reverse<2;reverse++) {
        pl_shader sh=pl_dispatch_begin(dp);
        CHECK(ajn_camera_sample(camera,sh,reverse?b:a,reverse?a:b,motion,reverse?-0.63f:0.37f));
        CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&sh,.target=out)));
        verify_protected_sample(gpu,dp,reverse?b:a,out);
    }
    // The separate pan mode uses full-frame translation at source-aligned
    // 72 Hz phases. Original source instants and held drawing geometry remain.
    ajn_camera_set_rigid(camera,true);
    motion=coherent_pair(camera,dp,a,b);
    verify(gpu,dp,motion,true,"rigid pan");
    for(int tick=0;tick<3;tick++) {
        float fraction=tick/3.0f;
        pl_shader sh=pl_dispatch_begin(dp);
        CHECK(ajn_camera_sample(camera,sh,a,b,motion,fraction));
        CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&sh,.target=out)));
        verify_sample(gpu,dp,out,fraction);
    }
    ajn_camera_reset(camera);
    for(int i=0;i<6;i++) {
        pl_tex tex=i%2?b:a;
        generate(dp,tex,i*1.8f,i*0.25f,2);
        CHECK(ajn_camera_frame(camera,i+1,tex));
        if(i) { motion=ajn_camera_pair(camera,i,i+1); CHECK(motion); }
    }
    verify(gpu,dp,motion,false,"rigid pan rejects independently moving foreground");
    // The changed drawing pair is rejected by the strict classifier. The
    // presentation lookahead must nevertheless preserve the verified pan,
    // sampling the original pose rather than blending into the next one.
    ajn_camera_reset(camera);
    pl_tex redraw_pairs[6];
    for(int i=0;i<7;i++) {
        generate(dp,a,i*1.8f,i*0.25f,5);
        CHECK(ajn_camera_frame(camera,i+1,a));
        if(i) { redraw_pairs[i-1]=ajn_camera_pair(camera,i,i+1); CHECK(redraw_pairs[i-1]); }
    }
    verify(gpu,dp,redraw_pairs[3],false,"large redraw remains strictly rejected");
    generate(dp,a,3*1.8f,3*0.25f,5);
    generate(dp,b,4*1.8f,4*0.25f,5);
    pl_shader redraw=pl_dispatch_begin(dp);
    CHECK(ajn_camera_sample(camera,redraw,a,b,redraw_pairs[3],0.5f));
    CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&redraw,.target=out)));
    verify_redraw_sample(gpu,dp,out,6.3f,0.875f);
    // The same isolated redraw during a fast, steadily decelerating pan.
    // Neighbor velocities differ by 0.8 pixels per interval: above the old
    // fixed 0.6-pixel limit, but only about 6% of the verified camera speed.
    ajn_camera_reset(camera);
    const float slowing_offsets[]={-46.6f,-30.6f,-15.4f,-1.0f,12.6f,25.4f,37.4f};
    for(int i=0;i<7;i++) {
        generate(dp,a,slowing_offsets[i],slowing_offsets[i]*0.125f,5);
        CHECK(ajn_camera_frame(camera,i+1,a));
        if(i) { redraw_pairs[i-1]=ajn_camera_pair(camera,i,i+1); CHECK(redraw_pairs[i-1]); }
    }
    verify(gpu,dp,redraw_pairs[3],false,"decelerating pan redraw remains strictly rejected");
    generate(dp,a,-1.0f,-0.125f,5); generate(dp,b,12.6f,1.575f,5);
    pl_shader slowing=pl_dispatch_begin(dp);
    CHECK(ajn_camera_sample(camera,slowing,a,b,redraw_pairs[3],0.5f));
    CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&slowing,.target=out)));
    verify_redraw_sample(gpu,dp,out,5.8f,0.725f);
    // A stationary foreground arriving during an established pan is not a
    // redraw: subsequent pairs disagree too, so lookahead must keep it still.
    ajn_camera_reset(camera);
    for(int i=0;i<7;i++) {
        generate(dp,a,i*1.8f,i*0.25f,i<3?0:2);
        CHECK(ajn_camera_frame(camera,i+1,a));
        if(i) { redraw_pairs[i-1]=ajn_camera_pair(camera,i,i+1); CHECK(redraw_pairs[i-1]); }
    }
    generate(dp,a,3*1.8f,3*0.25f,2); generate(dp,b,4*1.8f,4*0.25f,2);
    pl_shader foreground=pl_dispatch_begin(dp);
    CHECK(ajn_camera_sample(camera,foreground,a,b,redraw_pairs[3],0.5f));
    CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&foreground,.target=out)));
    verify_unchanged(gpu,dp,a,out);
    // Held pairs are geometrically valid, but one isolated drawing movement
    // between them is not an established camera pan.
    ajn_camera_reset(camera);
    for(int i=0;i<7;i++) {
        generate(dp,a,i<4?0.0f:1.8f,i<4?0.0f:0.25f,0);
        CHECK(ajn_camera_frame(camera,i+1,a));
        if(i) { redraw_pairs[i-1]=ajn_camera_pair(camera,i,i+1); CHECK(redraw_pairs[i-1]); }
    }
    generate(dp,a,0,0,0); generate(dp,b,1.8f,0.25f,0);
    pl_shader isolated=pl_dispatch_begin(dp);
    CHECK(ajn_camera_sample(camera,isolated,a,b,redraw_pairs[3],0.5f));
    CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&isolated,.target=out)));
    verify_unchanged(gpu,dp,a,out);
    ajn_camera_reset(camera);
    for(int i=0;i<6;i++) {
        pl_tex tex=i%2?b:a;
        generate(dp,tex,i*1.8f,i*0.25f,4);
        CHECK(ajn_camera_frame(camera,i+1,tex));
        if(i) { motion=ajn_camera_pair(camera,i,i+1); CHECK(motion); }
    }
    verify(gpu,dp,motion,true,"clear camera tracks outweigh weak stationary texture");
    ajn_camera_reset(camera);
    for(int i=0;i<6;i++) {
        pl_tex tex=i%2?b:a;
        generate(dp,tex,i*1.8f,i*0.25f,3);
        CHECK(ajn_camera_frame(camera,i+1,tex));
        if(i) { motion=ajn_camera_pair(camera,i,i+1); CHECK(motion); }
    }
    verify(gpu,dp,motion,true,"rigid pan remains active with animated meteors");
    pl_shader drawing=pl_dispatch_begin(dp);
    CHECK(ajn_camera_sample(camera,drawing,a,b,motion,0.37f));
    CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&drawing,.target=out)));
    verify_animated_drawing(gpu,dp,out,0.37f,false);
    // A drawing changes at 24 fps while a 36 fps camera holds its position:
    // A + 2/3 and B - 1/3 have the same background, but different original poses.
    for(int after=0;after<2;after++) {
        float phase=after?-1.0f/3:2.0f/3;
        pl_shader sh=pl_dispatch_begin(dp);
        CHECK(ajn_camera_sample(camera,sh,after?b:a,after?a:b,motion,phase));
        CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&sh,.target=out)));
        verify_sample(gpu,dp,out,4+2.0f/3);
        verify_animated_drawing(gpu,dp,out,phase,after);
    }
    // Confirm the beginning from lookahead, then remove a single held camera
    // interval without discontinuity when the selected original frame changes.
    ajn_camera_reset(camera);
    const float positions[]={0,1,2,2,3,4};
    pl_tex pairs[5];
    for(int i=0;i<6;i++) {
        generate(dp,a,positions[i]*1.8f,positions[i]*0.25f,0);
        CHECK(ajn_camera_frame(camera,i+1,a));
        if(i) { pairs[i-1]=ajn_camera_pair(camera,i,i+1); CHECK(pairs[i-1]); }
    }
    generate(dp,a,0,0,0); generate(dp,b,1.8f,0.25f,0);
    pl_shader start=pl_dispatch_begin(dp);
    CHECK(ajn_camera_sample(camera,start,a,b,pairs[0],0.5f));
    CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&start,.target=out)));
    verify_sample(gpu,dp,out,0.5f);
    for(int i=1;i<=3;i++) for(int after=0;after<2;after++) {
        generate(dp,a,positions[i]*1.8f,positions[i]*0.25f,0);
        generate(dp,b,positions[i+1]*1.8f,positions[i+1]*0.25f,0);
        pl_shader sh=pl_dispatch_begin(dp);
        CHECK(ajn_camera_sample(camera,sh,after?b:a,after?a:b,pairs[i],
                                after?-1.0f/3:2.0f/3));
        CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&sh,.target=out)));
        verify_sample(gpu,dp,out,1+(i-1+2.0f/3)*2.0f/3);
    }
    // A longer source camera stop remains stationary.
    ajn_camera_reset(camera);
    const float stopped[]={0,1,2,2,2,3};
    for(int i=0;i<6;i++) {
        generate(dp,a,stopped[i]*1.8f,stopped[i]*0.25f,0);
        CHECK(ajn_camera_frame(camera,i+1,a));
        if(i) { pairs[i-1]=ajn_camera_pair(camera,i,i+1); CHECK(pairs[i-1]); }
    }
    generate(dp,a,3.6f,0.5f,0); generate(dp,b,3.6f,0.5f,0);
    pl_shader stop=pl_dispatch_begin(dp);
    CHECK(ajn_camera_sample(camera,stop,a,b,pairs[2],2.0f/3));
    CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&stop,.target=out)));
    verify_unchanged(gpu,dp,a,out);
    ajn_camera_reset(camera);
    for(int i=0;i<6;i++) {
        pl_tex tex=i%2?b:a;
        generate(dp,tex,i*0.04f,0,0);
        CHECK(ajn_camera_frame(camera,i+1,tex));
        if(i) { motion=ajn_camera_pair(camera,i,i+1); CHECK(motion); }
    }
    pl_shader held=pl_dispatch_begin(dp);
    CHECK(ajn_camera_sample(camera,held,a,b,motion,2.0f/3));
    CHECK(pl_dispatch_finish(dp,pl_dispatch_params(.shader=&held,.target=out)));
    verify_unchanged(gpu,dp,a,out);
    // Switching experiments must not carry mature confidence across modes.
    ajn_camera_set_rigid(camera,false);
    CHECK(!ajn_camera_pair(camera,5,6));
    ajn_camera_destroy(&camera);
    pl_tex_destroy(gpu,&a); pl_tex_destroy(gpu,&b); pl_tex_destroy(gpu,&out);
    pl_dispatch_destroy(&dp); pl_vulkan_destroy(&vk); pl_log_destroy(&log);
    return 0;
}
