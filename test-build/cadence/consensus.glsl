shared float sorted_x[128],sorted_y[128];
shared vec2 totals[128];
shared uint valid_count,inlier_count,coverage;
void run_consensus() {
    uint lane=gl_LocalInvocationID.x;
    vec4 f=texelFetch(forward_flow,ivec2(lane,0),0);
    vec4 b=texelFetch(backward_flow,ivec2(lane,0),0);
    bool valid=f.w>0.5 && b.w>0.5 && length(f.xy+b.xy)<0.7;
    if(lane==0u) { valid_count=0u; inlier_count=0u; coverage=0u; }
    barrier();
    if(valid) atomicAdd(valid_count,1u);
    sorted_x[lane]=valid ? f.x:1e10;
    sorted_y[lane]=valid ? f.y:1e10;
    barrier();
    for(uint k=2u;k<=128u;k*=2u) for(uint j=k/2u;j>0u;j/=2u) {
        uint other=lane^j;
        float ax=sorted_x[lane],bx=sorted_x[other],ay=sorted_y[lane],by=sorted_y[other];
        bool low=((lane&k)==0u)==((lane&j)==0u);
        barrier();
        sorted_x[lane]=low ? min(ax,bx):max(ax,bx);
        sorted_y[lane]=low ? min(ay,by):max(ay,by);
        barrier();
    }
    uint middle=min(valid_count/2u,127u);
    vec2 median=vec2(sorted_x[middle],sorted_y[middle]);
    bool inlier=valid && length(f.xy-median)<0.6;
    totals[lane]=inlier ? f.xy:vec2(0);
    if(inlier) {
        atomicAdd(inlier_count,1u);
        vec2 p=texelFetch(points,ivec2(lane,0),0).xy/vec2(640,360);
        ivec2 tile=clamp(ivec2(p*vec2(4,3)),ivec2(0),ivec2(3,2));
        atomicOr(coverage,1u<<uint(tile.y*4+tile.x));
    }
    barrier();
    for(uint step=64u;step>0u;step/=2u) {
        if(lane<step) totals[lane]+=totals[lane+step];
        barrier();
    }
    if(lane==0u) {
        bool ok=valid_count>=24u && float(inlier_count)>=0.82*float(valid_count) && bitCount(coverage)>=8;
        vec2 motion=ok ? totals[0]/float(inlier_count)/vec2(640,360):vec2(0);
        imageStore(dst,ivec2(0),vec4(motion,ok ? 1.0:0.0,float(inlier_count)));
    }
}
