# Build and Dependency Guide

Agent-facing build guidance for this fork. `INSTALL.md` remains the general contributor guide; this file records the non-obvious path selection and failure modes that matter to automated delivery.

## Choose the build path

Squirrel has two materially different build paths:

| Change | Required path |
| --- | --- |
| Swift/AppKit frontend, checked-in data, packaging, or project configuration | Fast path with prebuilt librime |
| librime engine source or a locally checked-out librime plugin | From-source path |

Do not infer that a successful top-level `make` compiled changes under `librime/`. The top-level dependency check is based on file existence, not source freshness.

## Fast path: prebuilt librime

This is the CI and day-to-day frontend path:

```sh
./action-install.sh
make
```

`action-install.sh` downloads the pinned prebuilt `librime.1.dylib`, Sparkle framework, bundled librime plugins, and the pinned universal `librime-llm-rerank.dylib` release artifact. It stages them under `lib/`, `Frameworks/`, and `lib/rime-plugins/`.

The top-level `$(RIME_LIBRARY)` rule has no prerequisites. Once `lib/librime.1.dylib` exists, `make` and `make debug` do not re-enter the librime build, even if source under `librime/` or `librime/plugins/` changed. Editing those sources has no effect on this path.

The llm-rerank plugin also stays pinned on this path. Plugin source changes appear here only after the plugin repository publishes a release built against this repository's exact `rime_version`/`rime_git_hash`, and `action-install.sh` updates `llm_rerank_version` and `llm_rerank_sha256`.

### Bundled-file manifests

`make release` and `make debug` run `package/add_data_files` before Xcode. The script registers only entries in:

- `package/data_files_manifest`
- `package/rime_plugins_manifest`

Unlisted files left in `data/plum/` or `lib/rime-plugins/` are warned about and never added to `Squirrel.xcodeproj/project.pbxproj`. Missing manifest entries are also warnings. When bundled recipes or the librime release's plugin set changes, update the relevant manifest and project-file references together; never let local build leftovers determine project contents.

## From-source path

Use this path for any librime engine or source-plugin change:

```sh
git submodule update --init --recursive librime plum
export BOOST_ROOT=/opt/homebrew/opt/boost
export MACOSX_DEPLOYMENT_TARGET=13.0
make clean
make
```

`BOOST_ROOT` must point at an available Boost installation. The global Agent rules prohibit installing system software without explicit user action; inspect the environment rather than silently running Homebrew.

`plum` is mandatory even when the change is unrelated to schemas. `make clean` removes `data/plum/*` and `bin/*`; the next build needs `bin/rime-install` and the files in `$(PLUM_DATA)`, so it invokes `make -C plum`. An empty `plum/` submodule makes that build fail.

### Cached-input gotchas

- Recent Xcode/macOS SDKs no longer support librime's default deployment target cleanly. Always export `MACOSX_DEPLOYMENT_TARGET=13.0` before building dependencies; leveldb promotes the resulting availability warning to an error. `INSTALL.md` describes it as optional for general supported environments, but automated delivery on the current toolchain deliberately treats it as required.
- CMake caches the deployment target in each dependency build directory. If a dependency was configured with the wrong target, run `make -C librime -f deps.mk clean`, then `make librime`. Cleaning only `deps/*/build/` is insufficient: the top-level Makefile may see installed static libraries under `librime/lib/` and skip rebuilding them.
- After `lib/librime.1.dylib` exists, a plain top-level `make` skips librime again. Force recompilation and copy-out after engine or plugin changes with `make librime`.

## Plugin source and acquisition

The candidate-reranking plugin source lives in `Habit130/librime-llm-rerank`. Code PRs go there; issues, specifications, the delivery map, and blocking edges stay in `Habit130/squirrel`. A session in the plugin repository follows that repository's own Agent instructions and uses this repository's `CONTEXT.md` and issue tracker only through explicit prompt references.

For a source build, install a plugin with:

```sh
librime/install-plugins.sh Habit130/librime-llm-rerank
```

The script strips the `librime-` prefix and places the checkout at `librime/plugins/llm-rerank`, where librime's CMake discovers it. Plugin installation alone does not rebuild the top-level dylib; run `make librime`.

Other plugins follow the same discovery path. `librime-lua` additionally vendors Lua 5.4 from its `thirdparty` branch; after cloning it, run its `action-install.sh` from `librime/plugins/lua` before configuring librime.

## Targets and validation

Common targets:

- `make` / `make release`: release app build
- `make debug`: debug app build
- `make package`: installer package; always rebuilt from the current release app. Signing/notarization uses `DEV_ID`
- `make archive`: package plus Sparkle `sign_update` and the distributable archive. A missing or failed `sign_update` is fatal; the versioned archive and appcast are not left as a successful release
- `make check-package-integrity`: packaging fail-closed checks (stale package rebuild, signer failure, complete unsigned archive)
- `make install` / `make install-debug` / `make install-release`: install into `/Library/Input Methods`
- `make clean` / `make clean-deps` / `make clean-package`: remove the corresponding generated artifacts

The Squirrel Xcode project has no unit-test target. The repository-wide delivery baseline is in `docs/agents/issue-tracker.md`. Frontend changes require `swiftlint`, a full build, and the post-build Periphery scan:

```sh
swiftlint
periphery scan --relative-results --skip-build --index-store-path build/Index.noindex/DataStore
```

Use `SKILL.md` for the behavior-specific manual validation checklist. For live testing, install a debug or release build, enable Squirrel in System Settings, and attach Xcode to the Squirrel process that macOS launches; do not expect Xcode Run to launch the IMK server correctly.

For librime source changes, use `make -C librime test` or `make -C librime test-debug` as required by the ticket. A separately delivered plugin follows its own repository's test rules in addition to the Squirrel integration path specified by the execution prompt.

CI uses macOS 26 with Xcode 26.5. Commit and pull-request workflows run SwiftLint, `package/check_package_integrity`, `./action-build.sh package`, and Periphery; the release workflow substitutes `./action-build.sh archive` so it also builds Sparkle's `sign_update` tool and the release archive.
