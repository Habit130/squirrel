# AGENTS.md

Guidance for coding agents working in this repository. The machine-global `~/.config/opencode/AGENTS.md` applies; this file holds repo-specific overrides and hard-earned facts. (`CLAUDE.md` is a pointer here.)

## What this repository is

Squirrel (鼠鬚管) is the **macOS front-end** for Rime — an InputMethodKit (IMK) app written in Swift/AppKit. It talks to **librime**, the actual input-method engine (C++), through a C API. Squirrel receives an already-ranked candidate list from librime via `get_context` and only renders/paginates/highlights it; it does not generate or sort candidates itself (verified: there is no ranking/weight/sort/compare logic anywhere under `sources/`).

This matters for this project's planned direction of building a custom candidate-ranking algorithm: **that work does not belong in this repo's Swift code.** Read "Where candidate ranking actually lives" below before starting it.

## Git remotes and workflow (project override)

- `origin` = personal fork, `https://github.com/Habit130/squirrel` — the only write remote and PR target.
- `upstream` = official project, `https://github.com/rime/squirrel` — read-only reference. This fork intentionally diverges: do not routinely merge or rebase `upstream`; selectively port relevant fixes through a feature branch and PR. **Never push or open a PR against `upstream`.**
- The default branch is **`master`** (not `main`). Fetch `origin`, then create feature branches directly from `origin/master`; a local `master` must track `origin/master`, never `upstream/master`. All changes go through PRs, and the user squash-merges on GitHub.
- GitHub permits squash merge only and protects `master` with a PR-only ruleset. Automatic head-branch deletion stays disabled because this repository uses stacked PRs.
- Branch prefixes follow the global convention (`feat/`/`fix/`/`docs/`/`refactor/`/`chore/`), Conventional Commits in English, no auto-merge, no force-push.
- `gh` does not reliably infer the fork as default repo (two remotes); it is pinned via `gh repo set-default Habit130/squirrel`. Verify with `gh repo set-default --view` before any write — see `docs/agents/issue-tracker.md`.

## Plugin source repository

The candidate-reranking plugin implementation, including later-phase tickets tracked in this repo, is **not** in this repo and is not a submodule of it. Its source repo is **`Habit130/librime-llm-rerank`**, created by #17. Two ways to get the plugin binary, one per build path:

- **Fast path**: `action-install.sh` downloads a **pinned release artifact** — a universal `librime-llm-rerank.dylib` built by that repo's tag-triggered release workflow against the exact librime revision pinned here (`rime_version`/`rime_git_hash`), verified by pinned sha256 — and drops it into `lib/rime-plugins/`.
- **From-source path**: `librime/install-plugins.sh Habit130/librime-llm-rerank`, which strips the `librime-` prefix and lands it at `librime/plugins/llm-rerank`, where librime's CMake auto-discovers it.

- **Code PRs go to that repo**; issues, the map, the spec and all blocking edges stay on `Habit130/squirrel` (`docs/agents/issue-tracker.md`).
- The same git-flow convention applies inside it (prefix branches, Conventional Commits, PR against its default branch, no auto-merge, no force-push).
- It must carry its own agent-instruction file (an acceptance item of #17) — the scope constraint (简体 only), the code-style precedents, the `make librime` rule, and pointers back here for `CONTEXT.md` vocabulary and the issue tracker. A session working there does not get this file.

## Build

There are two very different build paths. Know which one a task needs:

**Fast path — prebuilt librime (what CI and most day-to-day frontend work use):**

```sh
./action-install.sh   # downloads a prebuilt librime.1.dylib + Sparkle.framework release into lib/ and Frameworks/,
                      # plus the pinned librime-llm-rerank.dylib release artifact into lib/rime-plugins/
make                   # = make release; links against the prebuilt dylib, does NOT compile librime/ at all
```

`make`'s dependency rule for the dylib (`$(RIME_LIBRARY)`) has no prerequisites, so it only checks whether `lib/librime.1.dylib` exists — not whether `librime/` source changed. **Editing files under `librime/` has zero effect on the built app on this path.** The same holds for the llm-rerank plugin: the fast path always uses the pinned release artifact from `action-install.sh`, so plugin source changes only take effect on this path after a new plugin release is tagged and the pin in `action-install.sh` is bumped (`llm_rerank_version`/`llm_rerank_sha256`).

**From-source path — required for any librime/engine change (this includes ranking-algorithm work):**

```sh
git submodule update --init --recursive librime plum   # BOTH — plum is not optional here, see below
export BOOST_ROOT=/opt/homebrew/opt/boost   # `brew install boost` is enough for local dev; see INSTALL.md for the portable/universal option
export MACOSX_DEPLOYMENT_TARGET=13.0        # NOT optional on recent Xcode — see gotcha below
make clean               # required if action-install.sh ran before and left a prebuilt lib/librime.1.dylib
make                     # $(RIME_LIBRARY) is now missing, so the `librime` target builds it from submodule source
                          # (make -C librime deps && make -C librime release install), then copies it into lib/, bin/
```

**`plum` must be initialized on this path even when you have no intention of touching schema data.** `make clean` deletes `data/plum/*` and `bin/*` (`Makefile:178-185`), and `bin/rime-install` plus three `data/plum/` files *are* `$(PLUM_DATA)` (`Makefile:17-20`), which `$(DEPS_CHECK)` requires (`Makefile:26`). With those files gone the next `make` runs the `plum-data` target, which shells out to `make -C plum` (`Makefile:60-71`) — and that fails outright if `plum/` is an empty submodule directory. Since `make clean` is a required step above, `plum` is a required checkout. (An already-populated `plum/` masks this, which is why a machine that once ran the fast path can build without noticing.)

Other targets: `make debug`, `make package` (produces a `.pkg`; set `DEV_ID` for codesigning/notarization), `make install` / `make install-debug` / `make install-release` (installs to `/Library/Input Methods/Squirrel.app`; needs sudo on first install), `make clean` / `make clean-deps` / `make clean-package`.

### From-source build gotchas (verified against Xcode 27 beta / macOS 27 SDK)

These bit a real from-source build attempt and cost significant time to root-cause. All stem from Make's dependency checks being file-existence-only, and CMake caching configure-time values — neither notices when *inputs* change if the *output* is already there.

- **`librime/Makefile` defaults `MACOSX_DEPLOYMENT_TARGET ?= 10.15`.** Recent Xcode/macOS SDKs have dropped libc++ support below macOS 11.0, and `leveldb`'s vendored CMake build enables `-Werror`, so the resulting availability warning becomes a hard compile error (`"The selected platform is no longer supported by libc++."`) — while `glog`/`googletest` silently only warn, hiding the same problem. Fix: always `export MACOSX_DEPLOYMENT_TARGET=13.0` (matching the project's own supported floor) before building librime from source.
- **CMake caches the deployment target per dependency on first configure.** If a `librime/deps/<dep>/build/` directory was already configured once (e.g. from a failed attempt before the env var was set correctly), re-running `make` with the env var fixed will *not* retroactively fix it — `cmake .` reuses the existing `CMakeCache.txt`. Fix: `make -C librime -f deps.mk clean-src` (wipes `deps/*/build/` only, not the installed `librime/lib`/`librime/include` outputs) before rebuilding.
- **`librime`/`copy-rime-binaries` are `.PHONY`, but the top-level `$(RIME_LIBRARY)` prerequisite check is not.** Once `lib/librime.1.dylib` exists, plain `make`/`make debug` will skip the entire librime build+copy step again — even after you change librime source or add plugins. Force it with `make librime` directly.
- **Plugins need two separate fetch steps, not one.** `librime/install-plugins.sh <owner>/librime-<name> ...` clones each plugin into `librime/plugins/<name>`, which librime's CMake auto-discovers (`file(GLOB ...)` in `librime/plugins/CMakeLists.txt`) and builds into `lib/rime-plugins/*.dylib` — but only on a build that actually re-enters `make librime` (see previous point). `librime-lua` additionally vendors its Lua 5.4 source on a separate `thirdparty` git branch of the same repo; run `(cd librime/plugins/lua && bash action-install.sh)` after cloning it, or its CMake configure fails to find a Lua to link against. On the fast path these two fetch steps don't apply at all — `action-install.sh` installs the prebuilt plugins from the librime release, and `librime-llm-rerank` specifically from its pinned release artifact (see "Plugin source repository").

## Lint and validation

```sh
swiftlint                              # lints sources/ per .swiftlint.yml; required by CI
periphery scan --relative-results --skip-build --index-store-path build/Index.noindex/DataStore   # dead-code scan; run after a make build (index store is always on)
```

There is no unit test target in the Xcode project (IMK apps are hard to unit-test in isolation). Validation is `swiftlint` + `periphery` + a full Xcode build + manually exercising the input method — see SKILL.md's "Validation Checklist" for the specific scenarios (activation/deactivation, ASCII toggle, schema switching, candidate selection/paging, inline/non-inline preedit, vertical/linear layout, deploy/sync, quit/logout cleanup). CI (`.github/workflows/`) runs exactly: swiftlint → `./action-build.sh package` → periphery, on macos-26 / Xcode 26.5.

To run it live: `make install-debug` or `make install-release`, then select "鼠鬚管" in System Settings > Keyboard > Input Sources. macOS (not Xcode) launches the IMKServer process, so use Xcode's Debug > Attach to Process on the running Squirrel process rather than Run.

## Architecture

For the detailed Swift/IMK frontend architecture — process startup, session lifecycle, the `handle()` key-event loop, marked-text/commit rules, candidate panel flow, config model, notifications — **read `SKILL.md` at the repo root**; it's accurate and detailed. One correction: SKILL.md's file paths use a stale `Squirrel/Sources/*.swift` prefix from before a rename; the real location is `sources/*.swift` (no `Squirrel/` prefix).

Layering, top to bottom:

- **`sources/*.swift`** — the whole frontend: IMK controller, candidate panel, theme/config, key mapping. UI, key-handling, and display-formatting changes go here.
- **`librime/`** — git submodule, the Rime engine (C++). Dictionaries, user dictionaries, translators, and candidate scoring/ranking all live here. Not checked out by default (see Build).
- **`plum/`** — git submodule, Rime's schema/data package manager (`rime-install`). Fetches input schemas and data recipes, e.g. `data/plum/default.yaml` and the grammar-model data package used by octagram (see below).
- **`data/squirrel.yaml`** — checked-in default frontend settings (panel style, keyboard layout, notifications). `data/plum/` and `data/opencc/` are gitignored build outputs populated by `make data` / `action-install.sh`.
- **`lib/`, `bin/`, `Frameworks/`** — gitignored, populated by the build (librime dylib + plugins, `rime_deployer`/`rime_dict_manager`, Sparkle.framework).

## Where candidate ranking actually lives

Nothing in `sources/` reorders candidates. For ranking work, the relevant layers — all outside this repo's Swift code — are:

1. **librime core** (the `librime` submodule) — base dictionary/user-dictionary weights and candidate merging. Needs the from-source build above to iterate on.
2. **librime-octagram** — the grammar/n-gram reranking plugin. Three separate pieces all need to be present to matter: the plugin binary (bundled in the prebuilt librime release per CHANGELOG: "compiled with lua, octagram and predict plugins"), the grammar data (`action-build.sh`'s `SQUIRREL_BUNDLED_RECIPES` installs `lotem/rime-octagram-data` for both Hans and Hant), and a schema that actually enables the grammar. This is the closest existing prior art for "improve candidate ordering" and is worth reading first.
3. **librime-lua** — also bundled by default; lets you write a Lua `filter`/`translator` that reorders the candidate list from schema config, without recompiling C++. Likely the lowest-friction place to prototype a new algorithm.
4. **librime-predict** — bundled next-word-prediction plugin.

None of plugins 2-4's source lives in this repository; they're separate repos, normally installed as prebuilt binaries into `lib/rime-plugins/` (fast path) or via `librime/install-plugins.sh <repo-slug>` for a source build (see INSTALL.md).

The only ranking-adjacent surface on the Squirrel side is `sources/ReservedProperty.swift`: a librime→frontend property protocol plugins use to send UI *hints* (e.g. `_comment_highlight`/`_comment_warning` to color specific candidate indices by index). It's cosmetic and doesn't affect order — it just reflects whatever a plugin's reranking already decided.

## Session roles for issue delivery

Long implementation trains may designate one session as the **orchestrator**. That session inventories the issue frontier, checks dependencies and shared-state ownership, classifies each ticket by the autonomy its executor needs, writes the execution prompt, and independently accepts the result. It does not implement the dispatched ticket or treat the executor's summary as proof.

Execution difficulty is about unresolved implementation judgment at handoff, not estimated effort:

- **Easy**: the issue and existing precedents already determine the seam, behavior, important edge cases, and verification path. The executor mainly carries out known work.
- **Hard**: the executor must still explore alternatives, choose seams, reconcile constraints, or design substantial tests while implementing. The prompt must explicitly grant that autonomy and identify the decisions that remain local to the ticket.

Do not classify by line count, number of files, wall-clock time, or domain sophistication. `ready-for-agent` and difficulty are independent: the label says unattended execution is allowed, while easy/hard selects how much autonomous judgment that execution needs. If a product or specification decision is still open, the ticket is not merely hard; it is not ready for AFK execution and must return to a HITL planning step. See `docs/agents/issue-tracker.md` for the dispatch and acceptance workflow.

## Parallel dispatch: machine-level shared state

Sessions working different tickets in parallel contend on state that git does not track. Before dispatching more than one at a time, assign each of these to exactly one session:

- **The librime build tree** (`librime/build/`, `librime/plugins/`, `lib/`, `bin/`) — owned exclusively by whichever ticket runs `install-plugins.sh` or `make librime`. Anything that merely *uses* a built binary (e.g. `rime_api_console`) must copy it out first, or it gets swapped mid-run. Remember `$(RIME_LIBRARY)` is an existence-only check: once `lib/librime.1.dylib` exists, plain `make` silently skips the librime and plugin build entirely, so plugin work must invoke `make librime` explicitly.
- **`~/Library/Rime`** — the live deployment. `luna_pinyin.userdb` mutates on every keystroke, and a redeploy rewrites `build/*.schema.yaml` under any session that is mid-verification. Eval and baseline work deploys into its own throwaway `rime_dir`; only live-typing verification touches the real one, and never while another session is redeploying.
- **A quiet machine, for timing numbers only** — a latency measurement taken while a 10-core librime build is running is contaminated in the pessimistic direction. Any ticket whose deliverable is a duration gets the machine to itself.

## Agent skills config

- **Issue tracker**: GitHub Issues on `origin` (`Habit130/squirrel`) via the `gh` CLI — never `upstream`. See `docs/agents/issue-tracker.md`.
- **Triage labels**: the five canonical roles, label strings unchanged. See `docs/agents/triage-labels.md`.
- **Domain docs**: single-context — `CONTEXT.md` (候选词排序 vocabulary, scoped to ranking only) + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
