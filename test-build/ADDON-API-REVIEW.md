# Addon API native build integration

This is the producer/packaging companion to the API 1.12 PR set. See [README.md](README.md) for the exact workflow inputs and qualification limits. The complete system and creator guides are in `mpv-AnimeJaNai/addons/REVIEW-GUIDE.md` and `DEVELOPER-GUIDE.md`.

The ordinary cross-build remains available. `addon_metadata=true` enables the addon preparation, dependency and metadata steps. Use full mpv/libass commits and `release=false` for acceptance builds. The optional Windows native-test workflow produces a separate MSYS2 test artifact; it is not a claim of bit-identical production output.

`addon_metadata=true` can publish an official 64-bit GPL release with `release=true`; fork source repositories are rejected for public releases. Addon tags append `-addons-<workflow-run-id>`, never replace the normal version/latest release, and are retained by daily pruning. Published addon assets cannot be overwritten by a rerun. The host assembler selects them with separate `AddonMpvForkVersion`/date/hash pins. Addon build and toolchain caches use separate key prefixes; production build-cache paths and keys are unchanged. Failed runs do not save these caches. Dependency preparation is tested against the pinned toolchain's actual curl recipe, including its empty `PATCH_COMMAND` form.

Addon runs also skip saving the shared `clang_root`, source-package and Rust
caches. Production prefix restores cannot therefore select modified addon
sysroots or detached dependency sources from those saves.

The old toolchain's fontconfig patches stopped applying to its moving `main` dependency. Addon preparation uses [upstream's patch rebase](https://github.com/shinchiro/mpv-winbuild-cmake/commit/bda10a2816ce9908d419b3f4b564227330457e76) and pins fontconfig to `b6cf4b270c42b13347a4012cdceb9bbc3d2e8f32`, where both patches apply with `git am --3way`. The two patch files retain their upstream author metadata. This override only runs for addon metadata builds.

Review in this order:

1. `prepare-addon-build.py` and `prepare-addon-dependencies.py`: retain required configuration/introspection before upstream cleanup and include optional native providers.
2. `clean-native-packages.py` and related preflight tests: avoid combining stale native artifacts with a new source selection.
3. `produce-native-metadata.py`: record actual source commits, build features, required private ABIs, file hashes and provenance.
4. `stage-native.py` and `prepare-test-runtime.py`: stage complete dependencies/licenses and exercise the isolated runtime.
5. Workflow wiring and the focused Python tests under this directory.

The main package assembler refuses an incomplete or mismatched native record. A checked-in capability JSON is only the source expectation; a released package needs metadata from its producing build. The same matching native files must accompany mpv.exe and mpv.net. Keep source and third-party license notices available to recipients.

The Windows native workflow compiles the addon filters, CUDA ownership code and
mux callback with `-Werror` before the full build, so an unrelated later source
failure cannot hide warnings in those files. It also checks the mux callback
against actual FFmpeg 6.1 headers. `prepare-test-runtime.py` stages the produced
MVTools DLL beside each test executable before running the native suite.

The MSYS2 shared runtime also rebuilds the matching ggml 0.28.0 base DLL with
`ggml-shared-terminate.patch`. That DLL otherwise installs a process-wide C++
terminate handler that survives unload and causes reload failures. The patch
leaves the application's handler untouched in Windows shared builds; explicit
ggml assertion/backtrace paths remain. It adds no player-side hook, permanent
module pin, frame work, lock or readback. Static production builds are unchanged.

`build-ggml-reload-fix.py` checks the original version, verifies the pinned source
archive, preserves every original named export and tests repeated DLL load/unload
with the application's handler intact. An unreviewed dependency version stops
the build instead of mixing versions. The artifact includes source/patch/DLL
hashes, the source commit, patch and MIT license. The complete native suite,
including the unmodified `libmpv-lifetime` test and the same-process sample
reload test, runs against the resulting bundled dependencies.

No additional libass patch belongs to the addon set. Build against AJN's existing libass fork and record the selected commit. Source changes for camera pans, display-sync experiments and unrelated inference optimizations are outside this PR.

Existing native build and desktop integration results are identified by commit/run in the main review guide. Documentation-only updates do not justify rebuilding the unchanged native player. Rebuild and rerun affected native tests when the source, ABI, dependency or staging logic changes. Do not advertise the addon-enabled public package until inference, player, Manager and host have been assembled and verified together.
