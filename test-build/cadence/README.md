# Experimental GPU camera cadence

This code is built into the pinned libplacebo renderer by
`libplacebo-camera-cadence.patch`. It analyzes cached, processed video textures
and merges a rigid translation into the presentation shader. It does not run
inference again at display rate. Motion estimates, consistency checks, sampling
weights and video textures remain on the GPU. The host supplies timestamps and
dispatches commands. The existing three render queues and ordered presentation
patch are unchanged.

Native mpv test settings:

```ini
vo=gpu-next
gpu-api=vulkan
hwdec=nvdec
video-sync=display-resample
interpolation=no
blend-subtitles=no
camera-cadence=yes
```

Use a fixed 60 Hz display and 23.976 fps source for comparison with the offline
`emulate-60` prototype. This option does not change the display refresh rate.
It bypasses near-integer display/source ratios, pauses, and source-blended
subtitles. Ordinary target subtitles and OSD are composited after the correction.
Turn it off with `camera-cadence=no`. It is disabled by default and is only
available when mpv is built with this patched libplacebo.

The GPU detector uses three luma pyramid levels, tiled corner selection,
forward/backward Lucas–Kanade tracking and a global translation consensus.
Uncertain motion and cuts retain the selected original pose. Confident pans use
Lanczos4 translation, with a neighboring original frame supplying exposed edges.
This is a perceptual experiment, not bit-exact/lossless output or a general motion
interpolator. Complex motion can remain juddery; false pan decisions and boundary
artifacts still require visual evaluation. The inverse-rate schedule follows the
offline prototype, inspired by Templin et al., *Emulating Displays with
Continuously Varying Frame Rates* (SIGGRAPH 2016).

The renderer retains up to three full-resolution processed frame textures, plus
small luma pyramids. Extra video memory and concurrent inference load matter even
when isolated shader timings are low. HDR visual equivalence is not established.

Edit the `.glsl` sources and run `python embed.py` to regenerate
`camera_motion_shaders.h` before compiling. The generated file is included for
standalone native kernel tests; the build regenerates it as well.
