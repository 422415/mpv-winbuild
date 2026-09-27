float lanczos(float x) {
    if(abs(x)<1e-6) return 1.0;
    if(abs(x)>=4.0) return 0.0;
    float a=3.141592653589793*x;
    return sin(a)*sin(a/4.0)/(a*a/4.0);
}
void run_weights() {
    vec4 flow=texelFetch(motion,ivec2(0),0);
    vec2 displacement=flow.xy*image_size*fraction;
    bool shifting=flow.z>0.5 && length(displacement)>0.02;
    if(!shifting) displacement=vec2(0);
    imageStore(dst,ivec2(0),vec4(displacement,shifting ? 1.0:0.0,0));
    // pixel - displacement has the same fractional part across the image.
    vec2 part=fract(-displacement);
    vec2 sums=vec2(0);
    for(int i=0;i<8;i++) sums+=vec2(lanczos(part.x-float(i-3)),lanczos(part.y-float(i-3)));
    for(int i=0;i<8;i++)
        imageStore(dst,ivec2(i+1,0),vec4(lanczos(part.x-float(i-3))/sums.x,
                                       lanczos(part.y-float(i-3))/sums.y,0,0));
}
