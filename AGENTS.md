# AGENTS.md

Local OpenCode sessions inherit `~/.config/opencode/AGENTS.md`. This file contains only
Squirrel-specific boundaries, workflow rules, review invariants, and context routing.
`CLAUDE.md` points here.

## Repository boundary

- Squirrel is the macOS Swift/AppKit frontend for Rime. It receives an already-ranked candidate list from librime and renders, paginates, and highlights it.
- Candidate generation, scoring, and reranking do not belong in `sources/`. Read `docs/agents/domain.md` before ranking work.
- The custom reranker is implemented in `Habit130/librime-llm-rerank`, not in this repository or a submodule. Issues, specifications, decisions, and dependency edges remain in `Habit130/squirrel`; code PRs go to the plugin repository.

## Session roles

- Every writing session declares one role in its initiating prompt: **Orchestration**, **Execution**, or **Acceptance**.
- **Orchestration** owns an explicit issue scope and may write only governance artifacts. It freezes contracts and handoffs; it does not implement or repair product code.
- **Execution** owns one issue, branch/worktree, delivery surface, and active writer. It implements and self-verifies the frozen issue contract, then returns a criterion/evidence matrix.
- **Acceptance** is conditionally required and independently checks the same frozen contract. It writes acceptance records only and never fixes the delivery.
- habit starts Execution and Acceptance and is the sole squash-merge authority. See `docs/agents/delivery.md` for dispatch, Codex, handoff, acceptance, and repair protocol.

## Git remotes and workflow

- `origin` = `https://github.com/Habit130/squirrel`, the only write remote and PR target.
- `upstream` = `https://github.com/rime/squirrel`, read-only reference. Never push or open a PR against it; do not routinely merge or rebase it into this intentionally divergent fork.
- The protected default branch is `master`. Fetch `origin`, then create feature branches from `origin/master` using `<type>/<kebab-slug>`; local `master` tracks `origin/master`, never `upstream/master`.
- Do not use stacked PRs. Parallel issues use separate worktrees.
- Every post-bootstrap change has a frozen issue contract and is delivered through one feature branch and one PR.
- Use English Conventional Commits. PR descriptions contain Motivation, Changes, and Verification.
- Agents may branch, commit, push, and create/update PRs. They leave the PR open and do not merge, enable auto-merge, or rewrite remote history.
- habit squash-merges. GitHub deletes the merged head branch. Completion is recorded only after the result is verified on `origin/master`.
- Before any `gh` write, run `gh repo set-default --view`; it must report `Habit130/squirrel`. See `docs/agents/issue-tracker.md`.

## Code Review Rules

- Report a finding only when the delivery introduces a concrete P0/P1 in a supported path. State the trigger, impact, primary evidence, and safe path or exception. Treat style, optional refactors, and stronger-than-contract tests as non-blocking follow-up.
- Flag a change that can lose, corrupt, duplicate, or fail to commit user text, or leave composition or marked text stranded with no documented fallback. Safe path: follow `SKILL.md` commit, marked-text, and deactivation rules.
- Flag candidate generation, scoring, or reranking in `sources/`. Safe path: implement ranking in `Habit130/librime-llm-rerank`; Squirrel may only render the already-ranked list and apply reserved-property UI hints.

## Agent skills

Load detailed guidance only when the task triggers it:

| Task | Required context |
| --- | --- |
| Issue tracker operations | `docs/agents/issue-tracker.md` |
| Triage or tracker labels | `docs/agents/triage-labels.md` |
| Planning, dispatch, handback, Acceptance, repair, or parallel delivery | `docs/agents/delivery.md` |
| Build, dependency, plugin installation, packaging, manifests, or CI validation | `docs/agents/build.md` |
| Domain terms, boundaries, or architectural decisions | `docs/agents/domain.md`, then relevant `CONTEXT.md`, `docs/adr/`, and `docs/reranker-public-contract.md` |
| Swift/IMK frontend, lifecycle, key handling, candidate UI, or manual validation | `SKILL.md` |
| `data/luna_pinyin.custom.yaml` | Read that file's constraint header before editing; it is the deployment truth source |

Follow only the rows relevant to the current task and any further pointers they contain.

## Shared-state gate

Parallel Execution uses a separate worktree per issue. Before dispatch, Orchestration allocates exclusive ownership of every applicable machine-level shared resource:

- **librime build tree** (`librime/build/`, `librime/plugins/`, `lib/`, `bin/`): one owner for `install-plugins.sh` or `make librime`. A consumer that only needs a built binary copies it out first.
- **live Rime deployment** (`~/Library/Rime`): one owner for deployment or live-input verification. Eval and baseline work uses a throwaway `rime_dir`.
- **quiet machine**: one owner when the deliverable includes latency or timing measurements.

Do not start concurrent work while an ownership edge is unresolved. Instance paths live in `.local/agent-context.md`.
