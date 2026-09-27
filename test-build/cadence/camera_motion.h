/* Experimental rigid-camera cadence correction. LGPL-2.1-or-later. */
#ifndef AJN_CAMERA_MOTION_H
#define AJN_CAMERA_MOTION_H
#include <stdint.h>
#include <libplacebo/dispatch.h>
#include <libplacebo/shaders/custom.h>

struct ajn_camera;
struct ajn_camera *ajn_camera_create(pl_gpu gpu, pl_dispatch dispatch);
void ajn_camera_destroy(struct ajn_camera **camera);
void ajn_camera_reset(struct ajn_camera *camera);

// Cache luma pyramids by rendered-frame identity. No host-visible GPU storage.
bool ajn_camera_frame(struct ajn_camera *camera, uint64_t signature, pl_tex frame);
// The returned 1x1 GPU texture contains normalized translation and confidence.
// It is consumed by shaders only, never mapped/read by the renderer.
pl_tex ajn_camera_pair(struct ajn_camera *camera, uint64_t before, uint64_t after);
// Append the correction to the existing output shader. fraction is a timestamp
// offset relative to the selected original frame, in source-frame durations.
bool ajn_camera_sample(struct ajn_camera *camera, pl_shader shader,
                       pl_tex base, pl_tex neighbor, pl_tex motion, float fraction);

#endif
