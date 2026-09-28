# Experimental GPU camera cadence

## Separate rigid-pan experiment

`camera-pan-smoothing=yes` selects a different presentation schedule: camera
position advances at each refresh of a display running at an integer multiple
of the source rate. For 24 to 72, the phases are 0, 1/3 and 2/3. Source drawing
changes retain their timestamps. This mode takes precedence over the older
`camera-cadence` experiment; the older mode remains available unchanged.

The initial scope is a coherent camera translation. It requires the established
GPU tracking consensus, a verified background fit, and three connected source
pairs. Queued frames confirm the start before presentation, avoiding the former
two-pair visible warm-up. Small animated regions retain their original drawings while sharing
the camera translation; their presence does not repeatedly disable a good pan.
A changed region that fits substantially better without camera translation
rejects the whole pair, protecting stationary foregrounds. Large inconsistent
regions and cuts also reject it. Motions below 0.1 of an analysis pixel per
source frame in held shots leave the original pixels untouched, avoiding tracking-noise
wobbles in held shots. Presentation applies a uniform translation, without a regional
mask, bending transition, or blending between animation drawings. The adjacent
frame can supply newly revealed borders. This cannot guarantee perfect scene
classification or reconstruct zoom, parallax, or arbitrary animation layers.

Rigid-pan consensus weights each corner by the square root of its strength,
capped at a strength of 0.01. This prevents weak grain in smooth shading from
vetoing a pan supported by clear edges, while limiting the influence of a few
sharp features. At least 24 agreeing tracks, 82% of valid tracking weight,
and eight covered image regions are still required, followed by the existing
dense image checks. The older cadence mode retains its unweighted voting.

With `camera-pan-half-rate=yes`, camera positions are held for two refreshes
(36 fps on a 72 Hz display). Source drawings still change on their own timeline,
including when a new drawing needs translating back to a held camera position.

A single held camera interval surrounded by similar verified translations is
redistributed across those three intervals, retaining both outer camera positions.
The drawings and their timestamps are unchanged. This intentionally adjusts the
camera trajectory near isolated one-frame pauses; longer stops, cuts and direction
changes are preserved. The sampling shader reads five cached pair estimates.
Rigid-pan mode prepares up to five processed frames (one preceding and three
following the current drawing), adding two full-resolution textures compared
with the old three-frame window. It retains three Vulkan queues and does not
add a GPU readback or an extra image-processing pass.

An isolated character redraw can fail the strict pair classifier even while
the background continues the camera pan. A separate GPU candidate retains
that background fit when a majority of tracks agree across at least eight
image regions, and a majority of sampled pixels have low alignment error.
Presentation can use it only between two strictly accepted pairs, with bounded
per-frame motion change and a matching intermediate estimate. It samples the
selected original drawing at the neighboring camera trajectory. Cuts,
consecutive rejected pairs and persistent stationary foregrounds cannot use
this path. Strict pair confidence is unchanged. The existing five-pair window
provides the lookahead; no additional frames, passes or CPU transfers are added.

Use `video-sync=display-resample`, `interpolation=no`, `blend-subtitles=no`,
Vulkan/NVDEC, and a supported multiple such as nominal 72 Hz for 23.976 fps.
An unmatched display rate bypasses this experiment. It does not change display
modes itself. Production has no frame or motion-vector readback; the existing
three Vulkan queues and source-frame inference rate are retained.

## Original cadence experiment

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

The schedule uses the player's current display interval and source duration,
with no fixed Hz preset. The original comparison with the offline `emulate-60`
prototype used a 60 Hz display and 23.976 fps source. The cadence clock advances
from successive presentation timestamps so a later refresh estimate does not
reinterpret the whole elapsed episode. Substantial rate changes and playback
resets re-anchor it; OSD redraws do not advance it.

This option does not change the display refresh rate. It bypasses near-integer
display/source ratios, content faster than the display, pauses, and source-blended
subtitles. Ordinary target subtitles and OSD are composited after the correction.
Turn it off with `camera-cadence=no`. It is disabled by default and is only
available when mpv is built with this patched libplacebo.

The GPU detector uses three luma pyramid levels, tiled corner selection and
forward/backward Lucas–Kanade tracking. It chooses the most-supported translation
and refines it with three robust alignment steps on the existing GPU luma images.
Image consistency uses the existing 320×180 level and symmetric half-way
sampling, so fine source detail and subpixel filtering are not mistaken for
animation. The background must have low mean alignment error; appreciable
camera movement must also halve the error compared with leaving it unaligned.
Before translating the image, it checks whether the camera estimate aligns the
actual image content. Small inconsistent regions retain their selected original
pixels while the rest of the background can receive correction. Large animated
regions, broad parallax and poor background alignment still reject the pair.

The 16×8 protection mask stays in the cached GPU motion texture. Three source
pairs of protection cover briefly held drawings. Both the output location and
translated sampling footprint are checked, so protected objects do not leave
shifted copies. Correction tapers outside a protected region and its sampling
margin; it resamples one pose rather than blending drawings at a mask boundary.
These are coarse motion-consistency regions, not semantic object segmentation.
They may include nearby background; boundary quality needs visual evaluation.
Correction also requires three consecutive accepted source-frame pairs. Any
rejected pair resets that GPU confidence history; repeated display samples of
one pair do not advance it. This prevents isolated valid pairs inside complex
animation from causing short bursts of correction. A clean pan starts correcting
after the initial two-pair warm-up, without adding playback buffering.
Uncertain motion and cuts retain the selected original pose. Confident backgrounds use
Lanczos4 translation, with a neighboring original frame supplying exposed edges.
This is a perceptual experiment, not bit-exact/lossless output or a general motion
interpolator. Complex motion can remain juddery; false pan decisions and boundary
artifacts still require visual evaluation. The inverse-rate schedule follows the
offline prototype, inspired by Templin et al., *Emulating Displays with
Continuously Varying Frame Rates* (SIGGRAPH 2016).

The renderer uses three working full-resolution processed frames, plus reusable
texture caches and small luma pyramids. Extra memory and concurrent inference load matter even
when isolated shader timings are low. HDR visual equivalence is not established.

Edit the `.glsl` sources and run `python embed.py` to regenerate
`camera_motion_shaders.h` before compiling. The generated file is included for
standalone native kernel tests; the build regenerates it as well.
