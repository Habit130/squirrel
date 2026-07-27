#!/usr/bin/env python3
"""Headless top-1/top-5/MRR eval for librime's luna_pinyin candidate ordering.

Drives librime/build/bin/rime_api_console against an isolated, disposable
rime_dir (never ~/Library/Rime) and scores whole-sentence pinyin -> hanzi
reconstruction. See scripts/eval/README.md for the protocol and caveats.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    sys.exit(
        "error: pypinyin not importable. Run this via scripts/eval/run.sh "
        "(it provisions a local venv), not with a bare python3."
    )

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_FILES = [
    "default.yaml",
    "luna_pinyin.schema.yaml",
    "luna_pinyin.dict.yaml",
    "essay.txt",
    "symbols.yaml",
    "cangjie5.schema.yaml",
    "cangjie5.dict.yaml",
]
# LineEditor's input buffer caps a single line at 99 chars (line_editor.h);
# keep well under that so pinyin for one sentence is never silently truncated.
MAX_PINYIN_LEN = 90
HAN_RE = re.compile(r"^[㐀-䶿一-鿿]+$")
MARKER = "__eval_marker__"
CANDIDATE_RE = re.compile(r"^(\d+)\. (.*)$")
COMMENT_RE = re.compile(r"^(.*) \((.*)\)$")
BRACKET_RE = re.compile(r"^〔(.*)〕$")  # 〔...〕


def parse_dict(dict_path):
    """Return (set of every dict word key, char -> set of its dict readings)."""
    dict_keys = set()
    char_readings = {}
    started = False
    with dict_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not started:
                if line == "...":
                    started = True
                continue
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            word, pinyin = parts[0], parts[1]
            dict_keys.add(word)
            if len(word) == 1 and " " not in pinyin:
                char_readings.setdefault(word, set()).add(pinyin)
    return dict_keys, char_readings


def load_corpus(corpus_path, char_readings):
    """Yield (sentence, pinyin) pairs, skipping anything unsuitable and
    reporting why (OOV char, a reading absent from the dict, too long for
    one input line).

    Pinyin comes from pypinyin (sentence-level, context-aware polyphone
    disambiguation, e.g. 银行 -> yin hang) rather than the dict's own
    per-character weights: this minimal dict's weightless multi-reading
    rows don't reliably rank the common reading first (e.g. 开's rows are
    bing/jian/kai/yan with no weight on any of them), so picking straight
    from the dict silently generated wrong pinyin for common characters.
    Each char's pypinyin reading is still validated against the dict's
    own reading set for that char, so nothing round-trip-impossible slips
    through.
    """
    cases = []
    skipped = []
    with corpus_path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not HAN_RE.match(line):
                skipped.append((lineno, line, "non-Han content"))
                continue
            oov = [c for c in line if c not in char_readings]
            if oov:
                skipped.append((lineno, line, f"OOV char(s): {''.join(sorted(set(oov)))}"))
                continue
            syllables = lazy_pinyin(line, style=Style.NORMAL)
            bad = [
                f"{c}({s})"
                for c, s in zip(line, syllables)
                if s not in char_readings.get(c, ())
            ]
            if bad:
                skipped.append((lineno, line, f"reading not in dict: {', '.join(bad)}"))
                continue
            pinyin = "".join(syllables)
            if len(pinyin) > MAX_PINYIN_LEN:
                skipped.append((lineno, line, f"pinyin too long ({len(pinyin)} chars)"))
                continue
            cases.append((line, pinyin))
    return cases, skipped


def build_rime_dir(template_dir):
    tmp = Path(tempfile.mkdtemp(prefix="squirrel-eval-"))
    for name in TEMPLATE_FILES:
        src = template_dir / name
        if src.exists():
            shutil.copy(src, tmp / name)
    return tmp


def build_script(cases):
    lines = ["set option zh_simp"]
    for _, pinyin in cases:
        lines.append("{Escape}")
        lines.append(pinyin)
        lines.append("print candidate list")
        lines.append(f"set option {MARKER}")
    lines.append("exit")
    return "\n".join(lines) + "\n"


def parse_candidates(block_lines):
    """Numbered lines restart at 1 once per 'print candidate list' reply; the
    auto-printed (page-capped) block from the pinyin line comes first, so the
    last run starting at 1 is the unbounded list we actually want."""
    candidates = []
    for line in block_lines:
        m = CANDIDATE_RE.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        rest = m.group(2)
        if idx == 1:
            candidates = []
        text, comment = rest, None
        cm = COMMENT_RE.match(rest)
        if cm:
            text, comment = cm.group(1), cm.group(2)
        candidates.append((text, comment))
    return candidates


def split_into_blocks(stdout_text, expected_count):
    blocks = []
    current = []
    for line in stdout_text.splitlines():
        if line == f"{MARKER} set on.":
            blocks.append(current)
            current = []
        else:
            current.append(line)
    if len(blocks) != expected_count:
        sys.exit(
            f"error: expected {expected_count} test-case blocks from rime_api_console, "
            f"got {len(blocks)} -- output didn't parse as expected, refusing to report "
            "numbers against misaligned data. Rerun with --keep-tmp and inspect stdout."
        )
    return blocks


def classify_rank1(text, comment, dict_keys):
    if text in dict_keys:
        return "word"
    if comment:
        bm = BRACKET_RE.match(comment)
        if bm and bm.group(1) in dict_keys:
            return "word"
    return "non_word"


def run(console_path, rime_dir, cases):
    script = build_script(cases)
    proc = subprocess.run(
        [str(console_path)],
        cwd=rime_dir,
        input=script,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return proc.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--console", type=Path,
                     default=REPO_ROOT / "librime/build/bin/rime_api_console")
    ap.add_argument("--template-dir", type=Path,
                     default=REPO_ROOT / "librime/build/bin")
    ap.add_argument("--corpus", type=Path,
                     default=REPO_ROOT / "scripts/eval/corpus/sentences.txt")
    ap.add_argument("--keep-tmp", action="store_true",
                     help="don't delete the isolated rime_dir afterwards (debugging)")
    args = ap.parse_args()

    if not args.console.exists():
        sys.exit(
            f"error: {args.console} not found.\n"
            "Build it first (from-source build path in CLAUDE.md builds "
            "librime/build/bin/rime_api_console alongside the minimal data files)."
        )
    dict_src = args.template_dir / "luna_pinyin.dict.yaml"
    if not dict_src.exists():
        sys.exit(f"error: {dict_src} not found (needed to derive corpus pinyin).")

    dict_keys, char_readings = parse_dict(dict_src)
    cases, skipped = load_corpus(args.corpus, char_readings)
    if not cases:
        sys.exit("error: no usable test cases after filtering the corpus.")

    rime_dir = build_rime_dir(args.template_dir)
    try:
        stdout = run(args.console, rime_dir, cases)
    finally:
        if args.keep_tmp:
            print(f"(kept isolated rime_dir at {rime_dir})", file=sys.stderr)
        else:
            shutil.rmtree(rime_dir, ignore_errors=True)

    blocks = split_into_blocks(stdout, len(cases))

    top1 = top5 = 0
    reciprocal_ranks = []
    rank1_categories = {"word": 0, "non_word": 0}
    not_found = 0
    for (sentence, pinyin), block in zip(cases, blocks):
        candidates = parse_candidates(block)
        rank = None
        for i, (text, _comment) in enumerate(candidates, 1):
            if text == sentence:
                rank = i
                break
        if candidates:
            cat = classify_rank1(candidates[0][0], candidates[0][1], dict_keys)
            rank1_categories[cat] += 1
        if rank is None:
            not_found += 1
            reciprocal_ranks.append(0.0)
            continue
        reciprocal_ranks.append(1.0 / rank)
        if rank == 1:
            top1 += 1
        if rank <= 5:
            top5 += 1

    n = len(cases)
    mrr = sum(reciprocal_ranks) / n
    rank1_total = sum(rank1_categories.values())
    non_word_rate = rank1_categories["non_word"] / rank1_total if rank1_total else float("nan")

    print(f"cases evaluated:        {n}")
    print(f"cases skipped:          {len(skipped)}")
    for lineno, line, reason in skipped:
        print(f"  corpus/sentences.txt:{lineno}: {line!r} - {reason}", file=sys.stderr)
    print(f"not found in dump:      {not_found}")
    print(f"top-1:                  {top1}/{n} = {top1 / n:.3f}")
    print(f"top-5:                  {top5}/{n} = {top5 / n:.3f}")
    print(f"MRR:                    {mrr:.3f}")
    print(f"rank-1 non-word rate:   {rank1_categories['non_word']}/{rank1_total} = {non_word_rate:.3f}")


if __name__ == "__main__":
    main()
