# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires owner/HITL action                |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

`ready-for-agent` records readiness, not difficulty. A dispatchable ticket can be easy or hard depending on how much implementation judgment remains; classify that in the execution prompt using `docs/agents/issue-tracker.md`, not with another tracker label.

`ready-for-human` covers the next required substantive human action: an owner decision, HITL planning, or human implementation. Record which action is needed in an issue comment; the label alone does not imply that implementation by a human is always required.
