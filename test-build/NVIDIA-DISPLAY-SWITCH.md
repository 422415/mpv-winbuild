# NVIDIA Windows swapchain replacement workaround

`libplacebo-nvidia-swapchain-recreate.patch` changes only the existing Vulkan
swapchain recreation path, and only for NVIDIA devices on Windows. Both the
production workflow and the Windows native test build apply it.

## Reason and scope

Jeff's pre-fix preview.6 process dump is blocked in NVIDIA's driver under
`vkCreateSwapchainKHR`, reached from libplacebo's handling of an out-of-date
swapchain after returning from 4K to 8K. The UI is idle in that dump. Two kernel
dumps also contain NVIDIA 621.01 DPC watchdog failures. These are evidence of
the failing transition, not proof that this patch cures the driver defect.

The workaround flushes submitted libplacebo work, waits for its completion,
cleans up retired swapchains, and destroys the current swapchain using the
library's existing presentation-completion handling. The next creation uses
`oldSwapchain = VK_NULL_HANDLE`, avoiding overlap between the old and new
presentation resources. The device, renderer, CUDA/inference pipeline and
compiled engines stay alive. The original behavior remains on other vendors
and operating systems.

No draw/submit/present loop is changed. There is no new timer, per-frame wait,
CPU image copy, or reduced queue count. Extra waiting is confined to
recreation, including window resizing and output-color changes. Initial
creation does not take the new wait. The existing presentation-order and RTX
HDR queue-synchronization patches still apply unchanged.

## Focused validation

Tested against libplacebo `275f7dea27924cdd34ab2e6c20e448b6bc4fab65`
(7.387.0), the preview.6 mpv binary, and the corrected PerMonitorV2 mpv.net
wrapper on Windows/RTX 5090 with driver 616.92:

- Built the shared library with Vulkan, OpenGL and D3D11 enabled. All 541
  exported names match preview.6; there are no new imported DLLs.
- With TensorRT upscaling and `vulkan-queue-count=3`, windowed/fullscreen and
  4K/144 -> 1080p/120 -> 4K/144 transitions continued playback. Five steady
  four-second samples had zero additional dropped frames and no executions
  of the recreation workaround. The player exited normally.
- Theater Lighting 0.1.7, with physical light output disabled, continued
  background analysis and whole-frame sampling across another resolution/
  refresh round trip (40 and 35 distinct sampled frames respectively). Stop
  survived reloading the file and removed the optional observation filters.
  The probe waits for the bridge's existing debounce rather than asserting
  removal at a fixed 1.5-second boundary.
- Debug output includes `Draining NVIDIA swapchain before replacement` and
  `NVIDIA swapchain drained; creating without oldSwapchain` at replacement.
  These messages must not appear repeatedly during steady playback.

For a reproduction, use a disposable preview copy, preserve its configs,
enable `msg-level=vo=debug`, and exercise the affected display transition.
Check continued playback, correct framebuffer dimensions, addon sample
progress if subscribed, and normal shutdown. Reissue the native-capability
metadata for a rebuilt DLL: the addon host deliberately rejects an old hash.

This does not reproduce Jeff's 8K/projector/NVIDIA 621.01 failure locally.
The candidate must remain unconfirmed for that hardware until tested there.
Because an externally requested mode change has already entered the driver,
the patch cannot guarantee recovery from a GPU/kernel stall that occurs
before recreation, or while waiting for outstanding work. It is a targeted
workaround for the observed replacement path, not a watchdog recovery system.
