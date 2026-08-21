# AGENTS.md

The machine-global `~/.config/opencode/AGENTS.md` applies. This file contains only Squirrel-specific boundaries, role overrides, and context routing. `CLAUDE.md` points here.

## Repository boundary

- Squirrel is the macOS Swift/AppKit frontend for Rime. It receives an already-ranked candidate list from librime and renders, paginates, and highlights it.
- Candidate generation, scoring, and reranking do not belong in `sources/`. Read `docs/agents/domain.md` before ranking work.
- The custom reranker is implemented in `Habit130/librime-llm-rerank`, not in this repository or a submodule. Issues, specifications, decisions, and dependency edges remain in `Habit130/squirrel`; code PRs go to the plugin repository.

## Session roles

Squirrel issue delivery overrides the global single-Agent division of work. A writing session must have one of these roles in its initiating prompt:

- **Orchestration (main) session**: maintains an owner-confirmed scope and may write only orchestration artifacts: issues and tracker state, specifications, ADRs, roadmaps, Agent guidance, execution prompts, handback records, and acceptance records. It never implements or repairs a dispatched product-code issue.
- **Execution session**: is started by the owner from a frozen execution prompt, handles one issue, and is the only active writer for that issue's branch and PR. Frozen prompts live at `docs/orchestration/execution-prompts/`; the issue records the filename and SHA-256.

An acceptance subagent is an optional read-only helper of the orchestration session, not a third delivery role. The orchestration session decides before dispatch whether to use one, records the reason, and remains the final decision-maker. Review depth may increase; the frozen acceptance standard may not.

If a writing task's role is unclear, resolve the role with the owner before editing. Read `docs/agents/issue-tracker.md` for the complete dispatch, frozen-contract, handback, acceptance, and escalation protocol.

## Git remotes and workflow

- `origin` = `https://github.com/Habit130/squirrel`, the only write remote and PR target.
- `upstream` = `https://github.com/rime/squirrel`, read-only reference. Never push or open a PR against it; do not routinely merge or rebase it into this intentionally divergent fork.
- The protected default branch is `master`. Fetch `origin`, then create feature branches from `origin/master`; local `master` tracks `origin/master`, never `upstream/master`.
- All changes use feature branches and PRs. The owner squash-merges on GitHub; no auto-merge or force-push. Automatic head-branch deletion stays disabled because stacked PRs are used.
- If the current branch holds a complete work unit without an open PR, open that PR before stacking new work on it. Branch from `origin/master` only after the prior work is merged.
- Follow the global branch prefixes and English Conventional Commits.
- Before any `gh` write, run `gh repo set-default --view`; it must report `Habit130/squirrel`. See `docs/agents/issue-tracker.md`.

## Context router

Load detailed guidance only when the task triggers it:

| Task | Required context |
| --- | --- |
| Issue shaping, dispatch, handback, acceptance, escalation, or parallel execution | `docs/agents/issue-tracker.md` |
| Triage or tracker labels | `docs/agents/triage-labels.md` |
| Build, dependency, plugin installation, packaging, manifests, or CI validation | `docs/agents/build.md` |
| Swift/IMK frontend, lifecycle, key handling, candidate UI, or manual validation | `SKILL.md` |
| Candidate ranking, semantic memory, LM integration, or plugin/frontend boundaries | `docs/agents/domain.md`, then the relevant parts of `CONTEXT.md` and `docs/adr/` |
| `data/luna_pinyin.custom.yaml` | Read that file's constraint header before editing; it is the deployment truth source |

Do not preload every linked document. Follow the row that matches the work and any further required-reading instructions it contains.

## Shared-state gate

Before parallel dispatch, the orchestration session must allocate separate worktrees and exclusive ownership of every applicable machine-level resource documented in `docs/agents/issue-tracker.md`. Do not run concurrent work until those allocations are explicit.
