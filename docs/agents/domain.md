# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.
- **`SKILL.md`** at the repo root — the detailed Swift/IMK frontend architecture.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

This repo is **single-context**:

```
/
├── CONTEXT.md
└── docs/adr/
    ├── 0001-inference-process-boundary.md
    └── 0002-windowed-stateless-scoring.md
```

## Use the glossary's vocabulary — within its scope

**`CONTEXT.md` here is deliberately narrow.** It covers one area only: **candidate ranking after the candidates have been produced**. It says so in its own opening line. It is not a glossary for the repository as a whole.

**Inside that scope** — reranking, candidate ordering, weights, the scoring pipeline, the language-model integration — use the terms as defined, and don't drift to synonyms the glossary explicitly lists under `_Avoid_`. If a ranking concept you need isn't there yet, that *is* a signal: either you're inventing language the project doesn't use (reconsider), or there's a real gap (note it for `/domain-modeling`).

**Outside that scope, the absence of a term means nothing.** Squirrel's frontend concerns — IMK session lifecycle, the key-event loop, marked text and commit rules, candidate-panel layout and theming, schema and config handling, notifications, deployment — have their own established vocabulary that `CONTEXT.md` never set out to cover. For those, `SKILL.md` and the surrounding code are the authority. Do **not** treat a missing term as invented language, and do not file glossary gaps for concepts the glossary was never scoped to hold.

If a piece of work straddles both (say, a ranking change that needs a new frontend hint), apply the glossary to the ranking half and follow existing code vocabulary for the rest.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-NNNN (<decision title>) — but worth reopening because…_
