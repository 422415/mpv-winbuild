float lanczos(float x) {
    if(abs(x)<1e-6) return 1.0;
    if(abs(x)>=4.0) return 0.0;
    float a=3.141592653589793*x;
    return sin(a)*sin(a/4.0)/(a*a/4.0);
}
bool isolated_hold(vec4 before,vec4 held,vec4 after) {
    if(before.w<0.5 || held.w<0.5 || after.w<0.5) return false;
    vec2 a=before.xy*vec2(640,360),b=after.xy*vec2(640,360);
    float scale=min(length(a),length(b));
    return length(held.xy*vec2(640,360))<0.1 && scale>=0.5 &&
           length(a-b)<=0.25*scale;
}
vec4 confirm_redraw(vec4 flow,vec4 candidate,vec4 before,vec4 after) {
    if(flow.w>0.5 || candidate.z<0.5 || before.w<0.5 || after.w<0.5)
        return flow;
    vec2 expected=(before.xy+after.xy)*0.5;
    // Neighbors are two source intervals apart; bound per-interval change.
    if(0.5*length((before.xy-after.xy)*vec2(640,360))>=0.6 ||
       length((candidate.xy-expected)*vec2(640,360))>=0.6)
        return flow;
    // Only an isolated redraw between two independently verified pan pairs.
    // A cut or a continuing stationary foreground cannot bridge this check.
    return vec4(expected,0,1);
}
void run_weights() {
    vec4 flow=texelFetch(motion,ivec2(0),0);
    vec2 correction=vec2(0);
    bool confirmed=flow.z>0.5;
    if(rigid_pan!=0) {
        vec4 a=(available&1)!=0 ? texelFetch(earlier_motion,ivec2(0),0):vec4(0);
        vec4 b=(available&2)!=0 ? texelFetch(previous_motion,ivec2(0),0):vec4(0);
        vec4 d=(available&4)!=0 ? texelFetch(next_motion,ivec2(0),0):vec4(0);
        vec4 e=(available&8)!=0 ? texelFetch(later_motion,ivec2(0),0):vec4(0);
        vec4 previous=b,next=d,original=flow;
        if((available&3)==3)
            b=confirm_redraw(b,texelFetch(previous_motion,ivec2(1,0),0),a,original);
        if((available&6)==6)
            flow=confirm_redraw(flow,texelFetch(motion,ivec2(1,0),0),previous,next);
        if((available&12)==12)
            d=confirm_redraw(d,texelFetch(next_motion,ivec2(1,0),0),original,e);
        // Require a connected three-pair run, with at most an isolated redraw
        // confirmed from the original strict pairs on either side.
        confirmed=confirmed || (flow.w>0.5 &&
                    ((a.w>0.5 && b.w>0.5) || (b.w>0.5 && d.w>0.5) ||
                     (d.w>0.5 && e.w>0.5)));
        vec2 first=vec2(0),last=vec2(0);
        // Redistribute one held camera interval over its two moving neighbors.
        // Both ends of the three-interval span stay fixed. Longer camera stops
        // and direction changes are left alone; source drawings are never mixed.
        if(isolated_hold(a,b,flow)) first=(2.0*flow.xy-a.xy-b.xy)/3.0;
        if(isolated_hold(b,flow,d)) {
            first=(flow.xy+d.xy-2.0*b.xy)/3.0;
            last=(2.0*d.xy-b.xy-flow.xy)/3.0;
        }
        if(isolated_hold(flow,d,e)) last=(d.xy+e.xy-2.0*flow.xy)/3.0;
        correction=mix(first,last,fraction<0.0 ? 1.0+fraction:fraction);
        // Still pairs also have valid geometry. They cannot establish a pan
        // around one isolated drawing movement; require another moving pair.
        // A single held interval inside a pan remains supported from either end.
        bool nearby_motion=(b.w>0.5 && length(b.xy*vec2(640,360))>=0.1) ||
                           (d.w>0.5 && length(d.xy*vec2(640,360))>=0.1) ||
                           isolated_hold(a,b,flow) || isolated_hold(flow,d,e);
        confirmed=confirmed && nearby_motion;
    }
    vec2 displacement=flow.xy*image_size*fraction;
    displacement+=correction*image_size;
    // Sub-analysis-pixel noise in held shots is not useful camera motion.
    // Keep those original pixels exact instead of adding a fractional wobble.
    bool moving=rigid_pan==0 || length(flow.xy*vec2(640,360))>=0.1 ||
                length(correction*vec2(640,360))>=0.1;
    bool shifting=confirmed && moving && length(displacement)>0.02;
    if(!shifting) displacement=vec2(0);
    imageStore(dst,ivec2(0),vec4(displacement,shifting ? 1.0:0.0,0));
    imageStore(dst,ivec2(9,0),vec4(flow.xy,0,0));
    // pixel - displacement has the same fractional part across the image.
    vec2 part=fract(-displacement);
    vec2 sums=vec2(0);
    for(int i=0;i<8;i++) sums+=vec2(lanczos(part.x-float(i-3)),lanczos(part.y-float(i-3)));
    for(int i=0;i<8;i++)
        imageStore(dst,ivec2(i+1,0),vec4(lanczos(part.x-float(i-3))/sums.x,
                                       lanczos(part.y-float(i-3))/sums.y,0,0));
}
