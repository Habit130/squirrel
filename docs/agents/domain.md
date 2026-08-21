# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Load only the relevant context

- For candidate ranking, semantic memory, or LM integration, read **`CONTEXT.md`** and the relevant decisions under **`docs/adr/`**.
- For Swift/IMK frontend behavior, read **`SKILL.md`**. Load ranking context only when the frontend change crosses that boundary.
- For work spanning both areas, read all applicable sources and preserve each area's vocabulary and ownership boundary.

The required sources above are part of this repository. If an applicable one is missing, report the missing context instead of silently inventing a replacement.

## File structure

This repo is **single-context**:

```
/
├── CONTEXT.md
└── docs/adr/
    ├── 0001-inference-process-boundary.md
    ├── 0002-windowed-stateless-scoring.md
    └── 0003-candidate-conditioned-semantic-representation.md
```

## Use the glossary's vocabulary — within its scope

**`CONTEXT.md` here is deliberately narrow.** It covers one area only: **candidate ranking after the candidates have been produced**. It says so in its own opening line. It is not a glossary for the repository as a whole.

**Inside that scope** — reranking, candidate ordering, weights, the scoring pipeline, the language-model integration — use the terms as defined, and don't drift to synonyms the glossary explicitly lists under `_Avoid_`. If a ranking concept you need isn't there yet, that *is* a signal: either you're inventing language the project doesn't use (reconsider), or there's a real gap (note it for `/domain-modeling`).

**Outside that scope, the absence of a term means nothing.** Squirrel's frontend concerns — IMK session lifecycle, the key-event loop, marked text and commit rules, candidate-panel layout and theming, schema and config handling, notifications, deployment — have their own established vocabulary that `CONTEXT.md` never set out to cover. For those, `SKILL.md` and the surrounding code are the authority. Do **not** treat a missing term as invented language, and do not file glossary gaps for concepts the glossary was never scoped to hold.

If a piece of work straddles both (say, a ranking change that needs a new frontend hint), apply the glossary to the ranking half and follow existing code vocabulary for the rest.

## Route ranking work to the owning layer

Squirrel receives librime's already-ranked candidate list through `get_context`; code under `sources/` renders, paginates, and highlights that order. It does not generate candidates or compare their ranking weights.

The relevant ranking layers are:

1. **librime core**: dictionary and user-dictionary weights, candidate merging, and sentence composition.
2. **librime-octagram**: grammar/n-gram reranking. It needs the plugin binary, grammar data, and a schema that enables it; the presence of only one component has no ranking effect. The clean bundled-data path installs `grammar.yaml` plus the zh-hant gram files; it does not provide a zh-hans gram package.
3. **librime-lua**: schema-configured Lua filters and translators, useful for prototypes that should not require a new C++ build.
4. **librime-predict**: next-word prediction rather than Squirrel-side candidate ordering.
5. **Habit130/librime-llm-rerank**: this fork's custom reranking and semantic-memory plugin. Its code is delivered in that repository; the issues, specifications, decisions, and dependency map remain in `Habit130/squirrel`.

The closest Squirrel-side integration surface is `sources/ReservedProperty.swift`. Reserved properties such as `_comment_highlight` and `_comment_warning` let plugins attach UI hints to candidate indices. They are cosmetic and never reorder candidates.

For plugin acquisition and the distinction between prebuilt and source builds, read `docs/agents/build.md`.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-NNNN (<decision title>) — but worth reopening because…_
