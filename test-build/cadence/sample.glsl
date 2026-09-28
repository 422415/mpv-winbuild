float protected_region(vec2 uv) {
    vec2 p=clamp(uv,vec2(0),vec2(1))*vec2(640,360);
    ivec2 tile=clamp(ivec2(p/vec2(40,45)),ivec2(0),ivec2(15,7));
    float distance2=400.0;
    for(int y=-1;y<=1;y++) for(int x=-1;x<=1;x++) {
        ivec2 q=tile+ivec2(x,y);
        if(any(lessThan(q,ivec2(0))) || any(greaterThan(q,ivec2(15,7)))) continue;
        if(texelFetch(motion,q+ivec2(0,1),0).r<0.5) continue;
        vec2 d=max(abs(p-(vec2(q)+0.5)*vec2(40,45))-vec2(20,22.5),vec2(0));
        distance2=min(distance2,dot(d,d));
    }
    // Preserve the protected region and a sampling margin exactly. Taper only
    // outside it, so a mask boundary cannot cut a sharp step into background
    // geometry. Resample one pose; do not blend two drawings at the boundary.
    return 1.0-smoothstep(4.0,20.0,sqrt(distance2));
}
float camera_lanczos(float x) {
    if(abs(x)<1e-6) return 1.0;
    if(abs(x)>=4.0) return 0.0;
    float a=3.141592653589793*x;
    return sin(a)*sin(a/4.0)/(a*a/4.0);
}
vec4 sample_camera() {
    ivec2 size=textureSize(base,0);
    vec2 pixel=pos*vec2(size)-0.5;
    vec4 info=texelFetch(weights,ivec2(0),0);
    if(info.z<0.5) return texelFetch(base,clamp(ivec2(round(pixel)),ivec2(0),size-1),0);
    vec2 delta=texelFetch(motion,ivec2(0),0).xy;
    vec2 before_pos=pos-(fraction<0.0 ? delta:vec2(0));
    // Protect both the destination and the translated sampling footprint so
    // an animated object cannot leave a shifted copy in the background.
    float protection=rigid_pan!=0 ? 0.0:
        max(protected_region(before_pos),protected_region(before_pos-info.xy/vec2(size)));
    if(protection>=1.0)
        return texelFetch(base,clamp(ivec2(round(pixel)),ivec2(0),size-1),0);
    info.xy*=1.0-protection;
    vec2 coord=pixel-info.xy;
    ivec2 origin=ivec2(floor(coord));
    if(all(greaterThanEqual(origin,ivec2(3))) && all(lessThan(origin+4,size))) {
        vec2 kernel[8],sums=vec2(0);
        for(int i=0;i<8;i++) {
            kernel[i]=protection>0.0 ? vec2(camera_lanczos(fract(coord.x)-float(i-3)),
                                           camera_lanczos(fract(coord.y)-float(i-3)))
                                     :texelFetch(weights,ivec2(i+1,0),0).xy;
            sums+=kernel[i];
        }
        vec4 color=vec4(0);
        for(int y=0;y<8;y++) {
            vec4 row=vec4(0);
            for(int x=0;x<8;x++) row+=texelFetch(base,origin+ivec2(x-3,y-3),0)*kernel[x].x/sums.x;
            color+=row*kernel[y].y/sums.y;
        }
        return color;
    }
    // A neighboring original frame supplies only the newly exposed border.
    // Interior sampling retains the selected original drawing.
    vec2 other=pixel-delta*vec2(size)*(fraction*(1.0-protection)+(fraction<0.0 ? 1.0:-1.0));
    if(all(greaterThanEqual(other,vec2(0))) && all(lessThan(other,vec2(size))))
        return textureLod(neighbor,(other+0.5)/vec2(size),0.0);
    return texelFetch(base,clamp(ivec2(round(pixel)),ivec2(0),size-1),0);
}
