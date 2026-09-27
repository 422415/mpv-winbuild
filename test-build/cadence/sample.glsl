vec4 sample_camera() {
    ivec2 size=textureSize(base,0);
    vec2 pixel=pos*vec2(size)-0.5;
    vec4 info=texelFetch(weights,ivec2(0),0);
    if(info.z<0.5) return texelFetch(base,clamp(ivec2(round(pixel)),ivec2(0),size-1),0);
    vec2 coord=pixel-info.xy;
    ivec2 origin=ivec2(floor(coord));
    if(all(greaterThanEqual(origin,ivec2(3))) && all(lessThan(origin+4,size))) {
        vec4 color=vec4(0);
        for(int y=0;y<8;y++) {
            vec4 row=vec4(0);
            for(int x=0;x<8;x++) row+=texelFetch(base,origin+ivec2(x-3,y-3),0)*texelFetch(weights,ivec2(x+1,0),0).x;
            color+=row*texelFetch(weights,ivec2(y+1,0),0).y;
        }
        return color;
    }
    // A neighboring original frame supplies only the newly exposed border.
    // Interior sampling retains the selected original drawing.
    vec2 delta=texelFetch(motion,ivec2(0),0).xy*vec2(size);
    vec2 other=pixel-delta*(fraction+(fraction<0.0 ? 1.0:-1.0));
    if(all(greaterThanEqual(other,vec2(0))) && all(lessThan(other,vec2(size))))
        return textureLod(neighbor,(other+0.5)/vec2(size),0.0);
    return texelFetch(base,clamp(ivec2(round(pixel)),ivec2(0),size-1),0);
}
