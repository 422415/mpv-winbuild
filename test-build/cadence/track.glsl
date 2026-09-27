shared vec4 terms[128];
shared vec2 rhs[128];
shared vec2 displacement;
shared int valid_track;
shared float final_error;
float sample_a(int level,vec2 p) {
    if(level==2) return textureLod(a2,(p+0.5)/vec2(textureSize(a2,0)),0.0).r;
    if(level==1) return textureLod(a1,(p+0.5)/vec2(textureSize(a1,0)),0.0).r;
    return textureLod(a0,(p+0.5)/vec2(textureSize(a0,0)),0.0).r;
}
float sample_b(int level,vec2 p) {
    if(level==2) return textureLod(b2,(p+0.5)/vec2(textureSize(b2,0)),0.0).r;
    if(level==1) return textureLod(b1,(p+0.5)/vec2(textureSize(b1,0)),0.0).r;
    return textureLod(b0,(p+0.5)/vec2(textureSize(b0,0)),0.0).r;
}
void run_track() {
    uint lane=gl_LocalInvocationID.x;
    int feature=int(gl_WorkGroupID.x);
    vec4 key=texelFetch(points,ivec2(feature,0),0);
#ifdef REVERSE_TRACK
    vec4 prior=texelFetch(forward_flow,ivec2(feature,0),0);
#else
    vec4 prior=vec4(0);
#endif
    vec2 point=key.xy+prior.xy;
    if(lane==0u) {
        displacement=vec2(0);
        valid_track=(key.z>0.00001 && (reverse_pass==0 || prior.w>0.5)) ? 1 : 0;
        final_error=1.0;
    }
    barrier();
    // The same fixed reduction order is used in forward and backward tracking.
    for(int level=2;level>=0;level--) {
        if(lane==0u && level<2) displacement*=2.0;
        barrier();
        vec2 origin=(point+0.5)/float(1<<level)-0.5;
        vec2 q=origin+vec2(int(lane%11u)-5,int(lane/11u)-5);
        float reference=lane<121u ? sample_a(level,q) : 0.0;
        vec2 grad=lane<121u ? 0.5*vec2(sample_a(level,q+vec2(1,0))-sample_a(level,q-vec2(1,0)),
                                               sample_a(level,q+vec2(0,1))-sample_a(level,q-vec2(0,1))) : vec2(0);
        for(int iteration=0;iteration<8;iteration++) {
            if(valid_track==0) break;
            float difference=lane<121u ? sample_b(level,q+displacement)-reference : 0.0;
            terms[lane]=vec4(grad.x*grad.x,grad.x*grad.y,grad.y*grad.y,abs(difference));
            rhs[lane]=grad*difference;
            barrier();
            for(uint step=64u;step>0u;step/=2u) {
                if(lane<step) { terms[lane]+=terms[lane+step]; rhs[lane]+=rhs[lane+step]; }
                barrier();
            }
            if(lane==0u) {
                float determinant=terms[0].x*terms[0].z-terms[0].y*terms[0].y;
                if(determinant<=1e-10) valid_track=0;
                else {
                    vec2 delta=vec2(terms[0].z*rhs[0].x-terms[0].y*rhs[0].y,
                                    terms[0].x*rhs[0].y-terms[0].y*rhs[0].x)/determinant;
                    displacement-=clamp(delta,vec2(-2.0),vec2(2.0));
                    if(any(greaterThan(abs(displacement),vec2(40.0)))) valid_track=0;
                    final_error=terms[0].w/121.0;
                }
            }
            barrier();
        }
    }
    if(lane==0u) {
        vec2 end=point+displacement;
        bool inside=all(greaterThan(end,vec2(8))) && all(lessThan(end,vec2(textureSize(a0,0))-8.0));
        imageStore(dst,ivec2(feature,0),vec4(displacement,final_error,
                   valid_track!=0 && inside && final_error<0.04 ? 1.0:0.0));
    }
}
