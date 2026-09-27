shared vec4 best_points[64];
float luma(ivec2 p) { return texelFetch(src,p,0).r; }
void run_features() {
    uint lane=gl_LocalInvocationID.x;
    uint feature=gl_WorkGroupID.x;
    ivec2 dims=textureSize(src,0);
    vec2 center=(vec2(feature%16u,feature/16u)+0.5)*vec2(dims)/vec2(16,8);
    ivec2 p=ivec2(center)+ivec2(int(lane%8u)-4,int(lane/8u)-4)*3;
    p=clamp(p,ivec2(24),dims-ivec2(25));
    float a=0.0,b=0.0,c=0.0;
    for(int y=-2;y<=2;y++) for(int x=-2;x<=2;x++) {
        ivec2 q=p+ivec2(x,y);
        vec2 g=0.5*vec2(luma(q+ivec2(1,0))-luma(q-ivec2(1,0)),
                         luma(q+ivec2(0,1))-luma(q-ivec2(0,1)));
        a+=g.x*g.x; b+=g.x*g.y; c+=g.y*g.y;
    }
    float strength=0.5*(a+c-sqrt((a-c)*(a-c)+4.0*b*b));
    best_points[lane]=vec4(vec2(p),strength,1);
    barrier();
    for(uint step=32u;step>0u;step/=2u) {
        if(lane<step && best_points[lane+step].z>best_points[lane].z)
            best_points[lane]=best_points[lane+step];
        barrier();
    }
    if(lane==0u) imageStore(dst,ivec2(feature,0),best_points[0]);
}
