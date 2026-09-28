shared vec4 tracks[128],totals[128];
shared uint valid_count,inlier_count,coverage;
shared vec2 candidate;
shared uint rejected_tiles,stationary_tiles;
void run_consensus() {
    uint lane=gl_LocalInvocationID.x;
    vec4 f=texelFetch(forward_flow,ivec2(lane,0),0);
    vec4 b=texelFetch(backward_flow,ivec2(lane,0),0);
    vec4 point=texelFetch(points,ivec2(lane,0),0);
    // Low-contrast grain can pass a forward/backward check without locating
    // the drawing reliably. Weight camera votes by corner strength, capped
    // so a few sharp animated features cannot dominate the whole image.
    float weight=rigid_pan!=0 ? sqrt(min(max(point.z,0.0),0.01)):1.0;
    bool valid=f.w>0.5 && b.w>0.5 && length(f.xy+b.xy)<0.7;
    if(lane==0u) { valid_count=0u; inlier_count=0u; coverage=0u; }
    barrier();
    if(valid) atomicAdd(valid_count,1u);
    tracks[lane]=vec4(f.xy,weight,valid ? 1.0:0.0);
    barrier();
    // Choose the translation supported by the largest group. A component-wise
    // median can sit near one edge of an otherwise coherent group, rejecting
    // its opposite edge and intermittently losing a real pan.
    float support=0.0;
    if(valid) for(uint i=0u;i<128u;i++)
        if(tracks[i].w>0.5 && length(tracks[i].xy-f.xy)<0.6) support+=tracks[i].z;
    totals[lane]=vec4(f.xy,support,0);
    barrier();
    for(uint step=64u;step>0u;step/=2u) {
        if(lane<step && totals[lane+step].z>totals[lane].z)
            totals[lane]=totals[lane+step];
        barrier();
    }
    vec2 center=totals[0].xy;
    barrier();
    bool inlier=valid && length(f.xy-center)<0.6;
    totals[lane]=vec4(inlier ? f.xy:vec2(0),inlier ? weight:0.0,valid ? weight:0.0);
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
    bool consensus_ok=rigid_pan!=0 ? (inlier_count>=24u && totals[0].z>=0.82*totals[0].w)
                              : float(inlier_count)>=0.82*float(valid_count);
    bool ok=valid_count>=24u && consensus_ok && bitCount(coverage)>=8;
    if(lane==0u) {
        candidate=ok ? totals[0].xy/float(inlier_count):vec2(0);
        rejected_tiles=0u;
        stationary_tiles=0u;
    }
    barrier();
    // Sparse tracks establish the camera model, but averaging their subpixel
    // errors can misalign sharp backgrounds. Refine that model against luma,
    // with bounded robust updates so independently animated pixels do not
    // pull the estimate away from the dominant background.
    if(ok) for(int iteration=0;iteration<3;iteration++) {
        ivec2 tile=ivec2(int(lane)%16,int(lane)/16);
        vec4 h=vec4(0);
        float ry=0.0;
        for(int y=2;y<45;y+=4) for(int x=2;x<40;x+=4) {
            vec2 p=vec2(tile*ivec2(40,45)+ivec2(x,y))+0.5;
            vec2 q=p+candidate;
            if(any(lessThan(p,vec2(4))) || any(greaterThan(p,vec2(636,356))) ||
               any(lessThan(q,vec2(4))) || any(greaterThan(q,vec2(636,356)))) continue;
            vec2 uv=p/vec2(640,360), step=1.0/vec2(640,360);
            float reference=textureLod(luma_before,uv,0.0).r;
            vec2 gradient=0.5*vec2(
                textureLod(luma_before,uv+vec2(step.x,0),0.0).r-textureLod(luma_before,uv-vec2(step.x,0),0.0).r,
                textureLod(luma_before,uv+vec2(0,step.y),0.0).r-textureLod(luma_before,uv-vec2(0,step.y),0.0).r);
            float difference=textureLod(luma_after,q/vec2(640,360),0.0).r-reference;
            float weight=min(1.0,0.02/max(abs(difference),1e-6));
            h+=weight*vec4(gradient.x*gradient.x,gradient.x*gradient.y,gradient.y*gradient.y,gradient.x*difference);
            ry+=weight*gradient.y*difference;
        }
        totals[lane]=h; tracks[lane].x=ry;
        barrier();
        for(uint step=64u;step>0u;step/=2u) {
            if(lane<step) { totals[lane]+=totals[lane+step]; tracks[lane].x+=tracks[lane+step].x; }
            barrier();
        }
        if(lane==0u) {
            h=totals[0]; ry=tracks[0].x;
            float determinant=h.x*h.z-h.y*h.y;
            if(determinant>1e-8)
                candidate-=clamp(vec2(h.z*h.w-h.y*ry,h.x*ry-h.y*h.w)/determinant,vec2(-1),vec2(1));
        }
        barrier();
    }
    // Preserve regions whose image content does not follow the camera. Do not
    // turn the entire pan off just because a small animated region disagrees.
    ivec2 tile=ivec2(int(lane)%16,int(lane)/16);
    bool protect=false;
    vec3 errors=vec3(0);
    if(ok) {
        uint bad=0u,count=0u;
        for(int y=1;y<45;y+=2) for(int x=1;x<40;x+=2) {
            vec2 p=vec2(tile*ivec2(40,45)+ivec2(x,y))+0.5;
            // Give both images equivalent bilinear filtering. Sampling one at
            // its pixel centers and only resampling the other makes fine static
            // detail appear to animate. Align around a shared half-way grid.
            vec2 scale=vec2(640,360)/vec2(textureSize(luma_before,0));
            vec2 middle=(floor((p+candidate*0.5)/scale)+0.5)*scale;
            p=middle-candidate*0.5;
            vec2 q=p+candidate;
            if(any(lessThan(p,vec2(4))) || any(greaterThan(p,vec2(636,356))) ||
               any(lessThan(q,vec2(4))) || any(greaterThan(q,vec2(636,356)))) continue;
            float a=textureLod(luma_before,p/vec2(640,360),0.0).r;
            float b=textureLod(luma_after,q/vec2(640,360),0.0).r;
            if(abs(a-b)>0.04) bad++;
            errors+=vec3(abs(a-b),abs(a-textureLod(luma_after,p/vec2(640,360),0.0).r),1);
            count++;
        }
        protect=count>0u && float(bad)>0.12*float(count);
        if(protect) atomicAdd(rejected_tiles,1u);
        // Animated content may change drawing while sharing the camera pan.
        // Moving those original drawings rigidly does not morph their poses.
        // A region that fits substantially better with NO translation is
        // different: moving it would introduce a wobble into a stationary
        // foreground. Keep rejecting that case for the whole-frame mode.
        if(protect && errors.y<0.5*errors.x) atomicAdd(stationary_tiles,1u);
    }
    totals[lane]=protect ? vec4(0):vec4(errors,0);
    barrier();
    for(uint step=64u;step>0u;step/=2u) {
        if(lane<step) totals[lane]+=totals[lane+step];
        barrier();
    }
    // Three source pairs of protection cover held drawings. Carry protection
    // both in screen space and along the preceding camera translation: local
    // animation need not move at the camera's speed. Store undilated history;
    // the presentation shader expands its footprint without growing it forever.
    float age=0.0;
    if(history_valid!=0) {
        ivec2 previous_tile=ivec2(floor(vec2(tile)+0.5-
            texelFetch(history,ivec2(0),0).xy*vec2(16,8)));
        previous_tile=clamp(previous_tile,ivec2(0),ivec2(15,7));
        age=max(texelFetch(history,tile+ivec2(0,1),0).r,
                texelFetch(history,previous_tile+ivec2(0,1),0).r)-1.0;
    }
    age=protect ? 3.0:max(age,0.0);
    imageStore(dst,tile+ivec2(0,1),vec4(age,0,0,0));
    if(lane==0u) {
        // Require low mean background error AND a clear improvement over
        // leaving moving images unaligned. Counting every sharp-edge residual
        // above one threshold was resolution-dependent and rejected real pans.
        float count=totals[0].z;
        float error=totals[0].x/max(count,1.0);
        float original_error=totals[0].y/max(count,1.0);
        ok=ok && count>0.0 && error<=0.01 && rejected_tiles<=12u &&
           (length(candidate)<0.5 || error<=0.5*original_error);
        // Limited animation no longer repeatedly disables an otherwise
        // verified camera pan. The existing background fit and coverage
        // requirements still reject large motion disagreements and cuts.
        if(rigid_pan!=0) ok=ok && stationary_tiles==0u;
        // A single well-aligned pair inside an animated shot must not turn
        // correction on for one frame. Count distinct, connected source pairs
        // on the GPU; cached presentation repeats never advance this streak.
        float previous=history_valid!=0 ? texelFetch(history,ivec2(0),0).w:0.0;
        float streak=ok ? min(previous+1.0,3.0):0.0;
        bool apply=streak>=3.0;
        vec2 motion=ok ? candidate/vec2(640,360):vec2(0);
        imageStore(dst,ivec2(0),vec4(motion,apply ? 1.0:0.0,streak));
    }
}
