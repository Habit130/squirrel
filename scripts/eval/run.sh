#!/bin/sh
# One-command entry point for the headless candidate-ranking eval.
# Usage: scripts/eval/run.sh [extra args passed through to run_eval.py]
#
# Bootstraps a local venv (scripts/eval/.venv, gitignored) on first run so
# corpus generation can use pypinyin for sentence-level pinyin (context-aware
# polyphone disambiguation, e.g. 银行 -> yin hang, not just per-character
# dict weight). Nothing outside scripts/eval/.venv is touched.
set -eu

script_dir=$(cd "$(dirname "$0")" && pwd)
venv_dir="$script_dir/.venv"

if [ ! -x "$venv_dir/bin/python3" ]; then
  python_bin=$(command -v python3.11 || command -v python3)
  "$python_bin" -m venv "$venv_dir"
  "$venv_dir/bin/pip" install --quiet -r "$script_dir/requirements.txt"
fi

exec "$venv_dir/bin/python3" "$script_dir/run_eval.py" "$@"
