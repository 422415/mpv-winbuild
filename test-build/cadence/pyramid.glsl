// GPU-only luma downsampling. Fixed-size work, independent of output resolution.
void run_pyramid() {
    ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    ivec2 dims = imageSize(dst);
    if (any(greaterThanEqual(p, dims))) return;
    vec2 scale = vec2(textureSize(src, 0)) / vec2(dims);
    vec2 center = (vec2(p) + 0.5) * scale;
    vec3 sum = vec3(0.0);
    for (int y = 0; y < 4; y++)
        for (int x = 0; x < 4; x++) {
            vec2 q = center + (vec2(x,y) / 4.0 - 0.375) * scale;
            sum += textureLod(src, q / vec2(textureSize(src,0)), 0.0).rgb;
        }
    float value = rgb_source != 0 ? dot(sum / 16.0, vec3(0.2126,0.7152,0.0722)) : sum.r/16.0;
    imageStore(dst, p, vec4(value,0,0,1));
}
