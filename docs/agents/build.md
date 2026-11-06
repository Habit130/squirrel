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
git submodule update --init --recursive librime plum
./action-install.sh
make
```

Initialize submodules before staging the prebuilt artifacts in a fresh worktree. The Swift
bridge still needs librime's checked-out headers. Staging first creates a nonempty `librime/`
directory that Git cannot initialize as a fresh submodule.

`action-install.sh` downloads the pinned prebuilt `librime.1.dylib`, Sparkle framework, bundled librime plugins, and the pinned universal `librime-llm-rerank.dylib` release artifact. It stages them under `lib/`, `Frameworks/`, and `lib/rime-plugins/`. It also installs the extra plum recipes listed in `package/bundled_recipes` (currently the octagram grammar data). `action-build.sh release` / `package` / `archive` call the same script and must not redeclare that list.

The top-level `$(RIME_LIBRARY)` rule has no prerequisites. Once `lib/librime.1.dylib` exists, `make` and `make debug` do not re-enter the librime build, even if source under `librime/` or `librime/plugins/` changed. Editing those sources has no effect on this path.

The llm-rerank plugin also stays pinned on this path. Plugin source changes appear here only after the plugin repository publishes a release built against this repository's exact `rime_version`/`rime_git_hash`, and `action-install.sh` updates `llm_rerank_version` and `llm_rerank_sha256`.

Every artifact `action-install.sh` downloads has a repository-reviewed SHA-256. The script verifies all four hashes before extracting any archive or copying the plugin dylib. A mismatch exits non-zero and leaves the download directory unextracted. `package/pin_build_deps_test.sh` covers that gate.

### Fast-path pin updates

Change these pins together; regenerate a hash with `shasum -a 256 download/<archive>` after fetching the new artifact.

| Bump | Change together |
| --- | --- |
| librime release | `rime_version`, `rime_git_hash`, `rime_sha256`, `rime_deps_sha256`. If the plugin was rebuilt against that librime, also `llm_rerank_version` and `llm_rerank_sha256`. |
| Sparkle | `sparkle_version`, `sparkle_sha256` |
| llm-rerank | `llm_rerank_version`, `llm_rerank_sha256` (must remain built against the pinned `rime_version` / `rime_git_hash`) |
| CI action | The full commit SHA and version comment on every `uses:` of that action under `.github/workflows/` |

Do not retarget a mutable tag (`@v6`, `@latest`). Pin `uses: org/action@<40-char-sha> # vX.Y.Z`.

### Bundled-file manifests

`make release` and `make debug` run `package/add_data_files` before Xcode. The script registers only entries in:

- `package/data_files_manifest`
- `package/rime_plugins_manifest`

Unlisted files left in `data/plum/` or `lib/rime-plugins/` are warned about and never added to `Squirrel.xcodeproj/project.pbxproj`. Missing manifest entries are also warnings. When bundled recipes or the librime release's plugin set changes, update `package/bundled_recipes`, the relevant manifest, and project-file references together; never let local build leftovers determine project contents.

`package/check_bundled_recipes` is the deterministic contract check: both scripts share that recipe file, and after a clean install the project-referenced grammar artifacts exist under `data/plum/`. Pass `--require-installed` to fail if those files are absent.

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
- `make archive`: package plus the versioned installer archive. Appcast generation stays off until this fork owns a signed feed.
- `make check-package-integrity`: packaging fail-closed checks (stale package rebuild; no leftover complete release)
- `make check-update-channel`: fail if Info.plist, the update-channel type, or `package/make_archive` names the upstream rime/squirrel feed, key, or download URL
- `make install` / `make install-debug` / `make install-release`: install into `/Library/Input Methods`
- `make clean` / `make clean-deps` / `make clean-package`: remove the corresponding generated artifacts

The Squirrel Xcode project has no unit-test target. Delivery and review are defined by
`docs/agents/builder.md` and `docs/agents/review.md`; the ticket names its Verification.
Frontend changes require `swiftlint`, a full build, and the post-build Periphery scan:

```sh
swiftlint
periphery scan --relative-results --skip-build --index-store-path build/Index.noindex/DataStore
```

Use `.agents/skills/squirrel-input-method-architecture/SKILL.md` for the behavior-specific manual validation checklist. For live testing, install a debug or release build, enable Squirrel in System Settings, and attach Xcode to the Squirrel process that macOS launches; do not expect Xcode Run to launch the IMK server correctly.

For librime source changes, use `make -C librime test` or `make -C librime test-debug` as required by the ticket. A separately delivered plugin follows its own repository's test rules in addition to the Squirrel integration path specified by its ticket.

For governance/docs-only work with `sources/` unchanged, use the structural Verification
named by the ticket. App builds, SwiftLint and Periphery are not automatic prerequisites for
that path. Preserve separately observed command failures as facts rather than weakening the
ticket's Verification or repairing product code in a governance delivery.

## CI and Actions secrets

CI uses macOS 26 with Xcode 26.5. Commit and pull-request workflows run the download-checksum
test, SwiftLint, `package/check_package_integrity`, `package/check_bundled_recipes`,
`package/check_update_channel`, `./action-build.sh package` (the prebuilt path with universal
and package flags), and Periphery. After packaging they rerun the recipe check with
`--require-installed`. The release workflow substitutes `./action-build.sh archive` and
creates draft tag releases; its upstream-only nightly condition is not active in this fork.

`pull request ci` runs on every PR without a path filter, and its job's reported name is
`build`: this is the repository's confirmed required check. The push-only `commit ci` and
`release ci` also name their job `build`; they are not additional every-PR checks. The
default-branch push-triggered CI run is the post-merge smoke check.

The generated governance workflows are separate: `governance-gate` judges default-branch PRs
from the default branch's trusted checkout, and `merge-watch` records misses after pushes or
completed default-branch workflow runs. The owner script adds the model's governance check
when habit applies the approved GitHub target state after merge; Merge watch is not required.

There are no referenced custom Actions secrets to provision. The built-in credential is
issued automatically by GitHub for each job, never supplied as a value by an agent:

| Name | Purpose | Issuing service |
| --- | --- | --- |
| `GITHUB_TOKEN` / `github.token` | Draft release publishing; the governance gate's head check run; Merge watch's issue records and evidence reads, within each workflow's declared permissions | GitHub Actions |

Optional local signing/notarization uses `DEV_ID` to select Apple Developer certificates and
a preconfigured keychain profile. No current workflow references an Actions secret for it.
This guide names the mechanism only; it does not authorize reading or creating credentials.

### Periphery in CI

All three workflows install Periphery from the official Homebrew core formula and log the scanner version before the scan:

```sh
brew install periphery
periphery version
```

Do not use the `peripheryapp/periphery` tap. Upstream stopped updating it at 3.0, and its cask now fails on current Homebrew (`depends_on macos: :catalina` is disabled). On `macos-26` / Xcode 26.5 the core formula installs Periphery 3.8.0 (#208). The last tap-based green run used 2.21.2.

The scan requirement is unchanged: the same `.periphery.yml` and the same `periphery scan --relative-results --skip-build --index-store-path build/Index.noindex/DataStore`. It runs after the build and the installed-grammar check, with no `continue-on-error`, skip condition, exclusion, or baseline. An install or scan failure fails `build`. Findings are reported as warnings and do not fail the job, the same policy as before. Version 3.x differs in two ways:

- 3.0 removed target selection, so 3.8.0 logs `warning: .periphery.yml: invalid key 'targets'` and scans every source file in the index store. `Squirrel` is the project's only native target, so the scanned set does not shrink.
- 3.8.0 also reports superfluous `periphery:ignore` comments as additional warnings.

Deferred limitation: Homebrew marks the core formula deprecated because the upstream repository is archived, and it is scheduled for disablement on 2027-08-12. Replacing Periphery, or otherwise acquiring it after that date, is follow-up work outside #208.

## Command evidence from Initialize (#206)

Commands were run in an owned temporary worktree at
`25dcef379ce6954a2a4274560c9ec85bb13ed999`, not in the original checkout or live deployment.
The optional source-plugin checkout resolved to
`e95f50a42769f1895636b6c4380f1dd5e300a2dc` in `Habit130/librime-llm-rerank`. These are
observations of that baseline and environment, not promises that a future mutable checkout
or another machine passes. Raw command results and causes are recorded on the issue.

| Command run | Result | Context or cause |
| --- | --- | --- |
| `./package/pin_build_deps_test.sh` | Working | Checksum mismatch prevents extraction; matching checksums reach extraction |
| `make check-package-integrity` | Working | Stale package rebuild and disabled-appcast cases passed |
| `make check-update-channel` | Working | Fork channel checks passed |
| `bash package/check_bundled_recipes` | Working | Shared recipe/manifest contract passed |
| `swiftlint` | Failing, exit 127 | Executable absent on PATH; no installation attempted |
| `./action-install.sh` | Working | Pinned downloads, hashes, prebuilt staging and recipe installation succeeded |
| `make`, `make debug`, `make package`, `make archive` before submodule initialization | Failing, exit 2 | Swift bridge could not find `rime_api_stdbool.h` |
| `git submodule update --init --recursive librime plum` after prebuilt staging | Failing, exit 1 | Generated `librime/` was nonempty; those own generated bytes were preserved outside the worktree |
| `git submodule update --init --recursive librime plum` with the submodule destination absent | Working | Initialized checked-out engine headers and plum before the subsequent builds |
| `make` after initialization | Working | Release app built with pinned prebuilts |
| `make debug` after initialization | Working | Debug app built with pinned prebuilts |
| `make package` after initialization | Working | Unsigned local installer built; not installed or published |
| `bash package/check_bundled_recipes --require-installed` | Working | Referenced grammar files existed after prebuilt staging |
| `periphery scan --relative-results --skip-build --index-store-path build/Index.noindex/DataStore` | Failing, exit 127 | Executable absent on PATH; no installation attempted |
| `make sparkle`, `make package/generate_keys`, `make package/sign_update` | Failing, exit 2 | Sparkle source submodule/project was absent; a staged framework is not its source-tool project |
| `make archive` after engine/plum initialization | Failing, exit 2 | App/package stages succeeded, but `package/sign_update` required the absent Sparkle source project |
| `librime/install-plugins.sh Habit130/librime-llm-rerank` | Working | Cloned the custom plugin into the temporary engine tree only |
| `make clean` | Working | Removed that temporary worktree's generated staging outputs only |
| `make` after the source-path exports and clean | Failing, exit 2 | Engine and custom plugin compiled; app bundling lacked the expected lua, predict and octagram dylibs |
| `make -C librime test` | Failing, exit 2 | Plugin suite setup rejected a 172-byte Unix-socket pathname against its 104-byte limit; 26 dependent cases skipped; core `rime_test` passed |
| `make -C librime test-debug` | Failing, exit 2 | Plugin test process segfaulted while starting `LazyTranslationsKeepTheirOwnScoringContext`; underlying cause not diagnosed; core `rime_test` passed |

The source-build attempt used the documented `BOOST_ROOT=/opt/homebrew/opt/boost` and
`MACOSX_DEPLOYMENT_TARGET=13.0` exports. Installing only the custom plugin did not provide
the other plugin binaries required by the app's checked-in bundle manifest.

No product code, Makefile, existing CI configuration or dependency pin was changed to make a
command pass. No machine-level software installation, live input-method installation,
permission-changing target, notary credential storage or real-input capture was run.
Failures above remain separate product, dependency or environment work, not options to
silently repair during governance initialization.
