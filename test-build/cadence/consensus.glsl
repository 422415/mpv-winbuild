shared float sorted_x[128],sorted_y[128];
shared vec2 totals[128];
shared uint valid_count,inlier_count,coverage;
shared vec2 candidate;
shared uint mismatches,checked,rejected_tiles;
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
    bool ok=valid_count>=24u && float(inlier_count)>=0.82*float(valid_count) && bitCount(coverage)>=8;
    if(lane==0u) {
        candidate=ok ? totals[0]/float(inlier_count):vec2(0);
        mismatches=0u; checked=0u; rejected_tiles=0u;
    }
    barrier();
    // Agreement among surviving tracks only proves dominant motion. A moving
    // background can outvote an independently animated character, especially
    // when its tracks fail. Check the actual image, including those regions,
    // before applying one translation to the entire source pose.
    if(ok) {
        ivec2 tile=ivec2(int(lane)%16,int(lane)/16);
        uint bad=0u,count=0u;
        for(int y=1;y<45;y+=2) for(int x=1;x<40;x+=2) {
            vec2 p=vec2(tile*ivec2(40,45)+ivec2(x,y))+0.5;
            vec2 q=p+candidate;
            if(any(lessThan(p,vec2(4))) || any(greaterThan(p,vec2(636,356))) ||
               any(lessThan(q,vec2(4))) || any(greaterThan(q,vec2(636,356)))) continue;
            float a=textureLod(luma_before,p/vec2(640,360),0.0).r;
            float b=textureLod(luma_after,q/vec2(640,360),0.0).r;
            if(abs(a-b)>0.04) bad++;
            count++;
        }
        atomicAdd(mismatches,bad);
        atomicAdd(checked,count);
        // Both a small animated subject and broad parallax must reject the
        // whole-frame warp. Allow small sampling/compression differences.
        if(count>0u && float(bad)>0.12*float(count)) atomicAdd(rejected_tiles,1u);
    }
    barrier();
    if(lane==0u) {
        ok=ok && checked>0u && float(mismatches)<=0.01*float(checked) && rejected_tiles==0u;
        vec2 motion=ok ? candidate/vec2(640,360):vec2(0);
        imageStore(dst,ivec2(0),vec4(motion,ok ? 1.0:0.0,float(inlier_count)));
    }
}
