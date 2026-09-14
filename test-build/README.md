# Optional Windows native test build

`.github/workflows/ajn-test-windows.yml` builds the selected mpv and libass sources
with MSYS2 UCRT64 on Windows Server 2022. It accepts manual dispatches and tests
changes to the integration branch. It uploads test artifacts. The ordinary
`mpv.yml` cross-build retains its default release behavior and has an optional
`addon_metadata` input for the static UCRT integration build.

For repeatable source selection, pass full commits rather than moving branches:

```sh
gh workflow run ajn-test-windows.yml -R the-database/mpv-winbuild \
  -f mpv_repository=the-database/mpv -f mpv_ref=FULL_MPV_COMMIT \
  -f libass_repository=the-database/libass -f libass_ref=FULL_LIBASS_COMMIT
```

The defaults select each upstream fork's `master`. Repository inputs also allow
testing contributors' forks. The resolved commits and the installed MSYS2 package
versions are recorded in `build-info/`; MSYS2 package versions are not pinned,
so this is not a bit-for-bit reproducible production toolchain.

The build enables the AJN libass features, Direct3D 11, Vulkan, CUDA interop and
the built-in mpv tests. It recursively bundles imported DLLs, checks required
feature defines and unresolved imports, runs the bundled player with only the
Windows system directory on PATH, and places those same DLLs beside the test
executables before running Meson's suite. Licenses, file hashes and dependency
metadata accompany the binaries. Artifacts expire after 14 days.

The required headless playback check disables `load-select` because the Server
runner has no audio endpoint and the AJN player currently fails during WASAPI
device-notification cleanup with that script enabled. An additional diagnostic
runs with normal scripts for both AJN and stock MSYS2 mpv and records both exit
codes in `server-desktop-probes.json`. This diagnostic failure is visible but
does not make the headless build fail. A green workflow does not establish that
the audio cleanup issue is fixed. No packaged playback default is changed.

The 3.6.1 test package used the same build/staging scripts with mpv
`21d5e10e5ca27a4b8a6dd4a8bbb02062bb8e6e24` and libass
`e813acd072d3f0f13aecf1966c5acec8b3ef7a1d`:
[native build and 36 passing mpv tests](https://github.com/422415/mpv-winbuild/actions/runs/34715845932).
Windows 11 desktop playback with normal scripts, D3D11/Vulkan subtitles, DirectML
upscaling, mpv.net and Manager were tested separately on an RTX 5090. Further
hardware and long-session coverage is still needed before a stable release.

## Official static addon builds

Use the ordinary `mpv.yml` workflow with full mpv/libass commits, the 64bit clang
target, `addon_metadata=true` and `release=false` for acceptance testing. The
preflight runs the producer tests and a small real CMake/Ninja cleanup test
before compiling the native dependency tree.

The upstream toolchain deletes each package's build directory after installation.
`prepare-addon-build.py` inserts an ordered mpv step that copies `config.h` and
the two required Meson introspection files before that cleanup. The metadata
producer reads this preserved configuration and the built binaries before
archive creation. Compilation errors stop the addon build immediately.

The player/development archives, producer JSON and `addon-build-configuration-64`
artifact belong together. Consumers verify the native hashes and exact source
pins, then run hardware acceptance tests against those same files. The metadata
record is not a publisher signature or evidence of successful GPU playback.

Opted-in failed builds retain diagnostic binaries/configuration and reusable
dependency caches where available. Diagnostic artifacts are unverified inputs,
not a release or accepted runtime. Packaged binaries and capability evidence are
excluded from the dependency cache to prevent reuse as a later build's output.
