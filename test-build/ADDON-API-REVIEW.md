# Addon API native build integration

This is the producer/packaging companion to the API 1.12 PR set. See [README.md](README.md) for the exact workflow inputs and qualification limits. The complete system and creator guides are in `mpv-AnimeJaNai/addons/REVIEW-GUIDE.md` and `DEVELOPER-GUIDE.md`.

The ordinary cross-build remains available. `addon_metadata=true` enables the addon preparation, dependency and metadata steps. Use full mpv/libass commits and `release=false` for acceptance builds. The optional Windows native-test workflow produces a separate MSYS2 test artifact; it is not a claim of bit-identical production output.

The workflow rejects `addon_metadata=true` combined with `release=true`. Addon build and toolchain caches use separate key prefixes; production build-cache paths and keys are unchanged. Failed runs do not save these caches. Dependency preparation is tested against the pinned toolchain's actual curl recipe, including its empty `PATCH_COMMAND` form.

Review in this order:

1. `prepare-addon-build.py` and `prepare-addon-dependencies.py`: retain required configuration/introspection before upstream cleanup and include optional native providers.
2. `clean-native-packages.py` and related preflight tests: avoid combining stale native artifacts with a new source selection.
3. `produce-native-metadata.py`: record actual source commits, build features, required private ABIs, file hashes and provenance.
4. `stage-native.py` and `prepare-test-runtime.py`: stage complete dependencies/licenses and exercise the isolated runtime.
5. Workflow wiring and the focused Python tests under this directory.

The main package assembler refuses an incomplete or mismatched native record. A checked-in capability JSON is only the source expectation; a released package needs metadata from its producing build. The same matching native files must accompany mpv.exe and mpv.net. Keep source and third-party license notices available to recipients.

No additional libass patch belongs to the addon set. Build against AJN's existing libass fork and record the selected commit. Source changes for camera pans, display-sync experiments and unrelated inference optimizations are outside this PR.

Existing native build and desktop integration results are identified by commit/run in the main review guide. Documentation-only updates do not justify rebuilding the unchanged native player. Rebuild and rerun affected native tests when the source, ABI, dependency or staging logic changes. Do not advertise the addon-enabled public package until inference, player, Manager and host have been assembled and verified together.
