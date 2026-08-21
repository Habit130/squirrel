# Execution prompts

This directory is the project location for frozen execution and repair prompts. The owner starts an execution session from the file named on the issue.

Protocol: [`docs/agents/issue-tracker.md`](../../agents/issue-tracker.md).

Filenames:

```text
AC-<issue>-v<n>-execution-prompt.md
AC-<issue>-v<n>-repair-prompt.md
```

Prompt bodies are gitignored. After freezing a prompt, record the repository-relative path and SHA-256 on the GitHub issue. Do not overwrite a file after its hash has been published; a new contract version gets a new filename.
