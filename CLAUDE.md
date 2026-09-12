# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A fork of [`zhongfly/mpv-winbuild`](https://github.com/zhongfly/mpv-winbuild) (itself based on
[`shinchiro/mpv-winbuild-cmake`](https://github.com/shinchiro/mpv-winbuild-cmake)) that
cross-compiles **mpv for Windows on Ubuntu** via GitHub Actions.

Its only purpose in the AnimeJaNai project is to produce the **Windows** `libmpv-2.dll` and
`mpv.exe` that carry the `vf_animejanai` filter and the forked-libass deferred subtitle
APIs. The `mpv-upscale-2x_animejanai` assembler downloads the resulting release assets
(`InstallCustomLibmpv` / `InstallCustomMpvExe`).

This repo builds nothing locally on a dev machine — the build is CI-only. Work here is
editing `.github/workflows/mpv.yml` and dispatching the workflow.

**Remotes:** `origin` = `the-database/mpv-winbuild`, `upstream` = `zhongfly/mpv-winbuild`.
Branch: `main`.

## The fork's entire delta vs upstream

`git diff --name-status upstream/main...main` touches exactly two files:

```
M	.github/workflows/mpv.yml
A	patch/0013-vulkan-rebase-patch.patch
```

Everything else — `build.sh`, the `patch/` series, `prunetags.sh`, `clean.yml`, `llvm.yml`,
`toolchain.yml` — is unmodified upstream. **Do not document or change upstream behaviour
here; send it upstream or carry it as a workflow edit.**

### `.github/workflows/mpv.yml` — the five fork changes

1. **Two new dispatch inputs** pin the fork sources:
   ```yaml
   mpv_ref:
     description: "the-database/mpv ref (branch/tag/sha) to build"
     default: "master"
   libass_ref:
     description: "the-database/libass ref (branch/tag/sha) to build"
     default: "master"
   ```
2. **`build_target` default `all-64bit` → `64bit`** and **`release` default `false` → `true`**.
3. **The `params` job resolves the fork, not upstream** — `owner: 'mpv-player'` became
   `owner: 'the-database'`, and a second `getCommit` resolves `the-database/libass` into a
   new `libass_sha` job output.
4. **The `Build` step redirects both sources** by `sed`-ing the toolchain's CMake package
   files. Quoted verbatim, including the comments that explain the ordering constraints:
   ```bash
   # Use the-database/mpv as the mpv source (carries the seek-speedup
   # patch). Must run AFTER zhongfly's patch series (they also touch
   # mpv.cmake) and BEFORE the build, so commit as a normal change.
   sed -i 's|mpv-player/mpv\.git|the-database/mpv.git|g' packages/mpv.cmake
   sed -i 's|\(GIT_REPOSITORY https://github.com/the-database/mpv.git\)|\1\n    GIT_TAG ${{ needs.params.outputs.sha }}|' packages/mpv.cmake
   # The Source Cache restore is not gated on needclean and mpv.cmake sets
   # UPDATE_COMMAND "", so a cached mpv checkout would ignore the GIT_TAG
   # above. Drop the mpv source + ExternalProject subtree so the pinned ref
   # is always freshly cloned (keeps toolchain/dep/ccache warm).
   rm -rf src_packages/mpv 2>/dev/null || true
   find build${{ matrix.bit }} -maxdepth 3 -type d -name 'mpv-prefix' -exec rm -rf {} + 2>/dev/null || true
   git add packages/mpv.cmake && \
     git -c user.name=ci -c user.email=ci@local commit -m "redirect mpv source"
   ```
   and the libass half, which additionally **turns the threads feature on**:
   ```bash
   sed -i 's|libass/libass\.git|the-database/libass.git|g' packages/libass.cmake
   sed -i 's|\(GIT_REPOSITORY https://github.com/the-database/libass.git\)|\1\n    GIT_TAG ${{ needs.params.outputs.libass_sha }}|' packages/libass.cmake
   sed -i 's|-Dlibunibreak=enabled|-Dlibunibreak=enabled\n        -Dthreads=enabled|' packages/libass.cmake
   rm -rf src_packages/libass 2>/dev/null || true
   find build${{ matrix.bit }} -maxdepth 3 -type d -name 'libass-prefix' -exec rm -rf {} + 2>/dev/null || true
   ```
   `-Dthreads=enabled` is what makes `--sub-ass-render-threads` and `--sub-gpu-blur` live in
   the shipped build — it is the libass fork's only meson option.

**Why the `rm -rf` lines matter:** the Source Cache restore is not gated on `needclean`, and
the toolchain's `mpv.cmake` sets `UPDATE_COMMAND ""`. Without dropping `src_packages/<pkg>`
and the `<pkg>-prefix` subtree, a cached checkout silently ignores the pinned `GIT_TAG` and
you get a stale build that looks successful. If a dispatch produces an unexpectedly old
`libmpv-2.dll`, check these lines first.

### `patch/0013-vulkan-rebase-patch.patch`

Present on `main`, absent from current `upstream/main`. Its header says
`From: zhongfly <11155705+zhongfly@users.noreply.github.com>`, i.e. it is **upstream-authored**,
not fork content.

> **Unverified:** whether upstream deleted this file after our last sync or the fork
> deliberately carries it. `main` is currently **20 commits behind `upstream/main`**
> (`git rev-list --count main..upstream/main`), so either is possible.

## How to dispatch a Windows build

`MPV` is **`workflow_dispatch` only** in this fork — there is no `schedule` trigger in
`mpv.yml` (upstream's `README.md` advertises hourly auto-builds; that does not apply here).

```bash
gh workflow run MPV -R the-database/mpv-winbuild \
  -f mpv_ref=master \
  -f libass_ref=master \
  -f build_target=64bit \
  -f compiler=clang \
  -f release=true
```

All inputs, with defaults: `mpv_ref` (`master`), `libass_ref` (`master`), `build_target`
(`64bit`; choices `32bit`/`64bit`/`64bit-v3`/`aarch64`/`all-64bit`/`all`), `lgpl` (`false`),
`compiler` (`clang`; or `gcc`), `needclean` (`false`), `no_save_cache` (`false`), `release`
(`true`), `command` (shell run before the build), `prs` (comma-separated mpv PR numbers),
`run_name` (display name in the run list).

Watch it with `gh run list -R the-database/mpv-winbuild` / `gh run watch`. Historical runs
take roughly 20–65 minutes for a single `64bit` clang target.

### Jobs

| Job | Runner | What it does |
|---|---|---|
| `params` | `ubuntu-latest` | resolves `mpv_ref`/`libass_ref` → SHAs, builds the bit matrix, applies mpv PR patches, uploads `mpv-patch` |
| `build_mpv` | `ubuntu-latest`, container `ghcr.io/archlinux/archlinux:base-devel`, `continue-on-error: true` | the real build |
| `publish_release` | `ubuntu-latest`, `if: inputs.release == true` | creates the GitHub release |
| `cache`, `cache_llvm` | `ubuntu-latest` | keep the toolchain/LLVM caches warm |

`build_mpv` installs its toolchain with pacman:

```bash
sudo pacman -S --noconfirm --needed git ninja cmake meson clang lld libc++ unzip ragel \
  yasm nasm gperf rst2pdf lib32-gcc-libs lib32-glib2 python-cairo curl wget mimalloc \
  ccache python-pip 7zip shaderc
```

then checks out `shinchiro/mpv-winbuild-cmake` into `mpv-winbuild-cmake/` (`fetch-depth: 0`)
and finally runs:

```bash
bash ../build.sh -t '<bit>' -c '<compiler>' -s '<lgpl>'
```

> **The CMake package files that the `sed` lines above edit — `packages/mpv.cmake` and
> `packages/libass.cmake` — live in `shinchiro/mpv-winbuild-cmake`, not in this repo.** They
> are not available locally; read them on GitHub before changing a `sed` expression.

`build.sh` (upstream, unmodified) does the real work per target: `cmake -Wno-dev --fresh
-DTARGET_ARCH=<arch>-w64-mingw32 -DCOMPILER_TOOLCHAIN=<compiler> -DENABLE_CCACHE=ON
-DSINGLE_SOURCE_LOCATION=$srcdir -G Ninja`, then `ninja download`, the toolchain targets
(`llvm`/`llvm-clang` for clang, `gcc` for gcc), `ninja update`, `ninja mpv-fullclean`,
`ninja mpv`, and packages each output dir with `7z a -m0=lzma2 -mx=9 -ms=on`.

## Outputs, and what the assembler expects

Release tag format (from the `publish_release` job):
`$(date "+%Y-%m-%d")-$(head -c 10 <<< "$mpv_sha")` — e.g. `2026-07-23-7fc08d90c7`.

The assembler consumes exactly two of the assets, by interpolated filename
(`BuildMpvUpscale2xAnimeJaNai/Program.cs:396` and `:432` in `the-database/mpv-AnimeJaNai`):

| Asset | Used for |
|---|---|
| `mpv-dev-x86_64-<YYYYMMDD>-git-<hash>.7z` | `libmpv-2.dll` (overwrites mpv.net's) |
| `mpv-x86_64-<YYYYMMDD>-git-<hash>.7z` | `mpv.exe`, `mpv.com` only |

so **three** constants in that repo must be bumped together after a dispatch, and they are
three different spellings of the same build:

```csharp
const string MpvForkVersion   = "2026-07-23-7fc08d90c7"; // the release tag
const string MpvForkBuildDate = "20260723";              // date in the archive filename
const string MpvForkGitHash   = "7fc08d90c7";            // short hash in the archive filename
```

Other assets published but unused by AnimeJaNai: `mpv-debug-*.7z`, `ffmpeg-*.7z`, `sha256.txt`.

## Related repos

- `the-database/mpv` — the mpv source this builds, and the **Linux** counterpart build
  (`Build Linux (portable mpv + vf_animejanai)`). See its `docs/BUILD-CI.md`.
- `the-database/libass` — the libass source this builds with `-Dthreads=enabled`.
- `the-database/mpv-AnimeJaNai` — the consumer; see its `docs/RELEASE.md` for where a
  dispatch here sits in the overall release order.
