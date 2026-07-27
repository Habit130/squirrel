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
    """Return ([(sentence, syllables), ...], skipped) -- syllables is a
    per-character list, kept (rather than joined) so derive_word_cases can
    slice out sub-words with their in-context reading.

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
            if len("".join(syllables)) > MAX_PINYIN_LEN:
                skipped.append((lineno, line, f"pinyin too long ({len(''.join(syllables))} chars)"))
                continue
            cases.append((line, syllables))
    return cases, skipped


def derive_word_cases(sentence_cases, dict_keys, lengths=(1, 2, 3, 4)):
    """Pull out every dict-word substring of each sentence as its own
    standalone test case: type just that word's pinyin (matching #2's
    real usage pattern -- one or two words at a time, then pick from the
    list -- rather than a whole continuous sentence) and expect it at
    rank 1. Deduped by word text across the whole corpus, so this scales
    for free as sentences are added. Includes single characters: a bare
    homophone like 他/她/它 sharing "ta" is the same rerank-group-ceiling
    question as a multi-char word, and it's #2's central motivating case.
    """
    words = {}
    for sentence, syllables in sentence_cases:
        n = len(sentence)
        for length in lengths:
            for i in range(0, n - length + 1):
                word = sentence[i:i + length]
                if word in dict_keys and word not in words:
                    words[word] = syllables[i:i + length]
    return sorted(words.items())


def build_rime_dir(template_dir):
    tmp = Path(tempfile.mkdtemp(prefix="squirrel-eval-"))
    for name in TEMPLATE_FILES:
        src = template_dir / name
        if src.exists():
            shutil.copy(src, tmp / name)
    return tmp


def build_script(cases):
    lines = ["set option zh_simp"]
    for _, syllables in cases:
        lines.append("{Escape}")
        lines.append("".join(syllables))
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
    sentence_cases, skipped = load_corpus(args.corpus, char_readings)
    if not sentence_cases:
        sys.exit("error: no usable test cases after filtering the corpus.")
    word_cases = derive_word_cases(sentence_cases, dict_keys)

    # One subprocess, one deploy, both case sets -- sentence cases first,
    # word cases second, tagged so the report can split them.
    tagged = [("sentence", s, syl) for s, syl in sentence_cases] + \
             [("word", w, syl) for w, syl in word_cases]
    run_cases = [(text, syl) for _kind, text, syl in tagged]

    rime_dir = build_rime_dir(args.template_dir)
    try:
        stdout = run(args.console, rime_dir, run_cases)
    finally:
        if args.keep_tmp:
            print(f"(kept isolated rime_dir at {rime_dir})", file=sys.stderr)
        else:
            shutil.rmtree(rime_dir, ignore_errors=True)

    blocks = split_into_blocks(stdout, len(run_cases))

    results = {"sentence": [], "word": []}
    for (kind, target, _syl), block in zip(tagged, blocks):
        candidates = parse_candidates(block)
        rank = None
        for i, (text, _comment) in enumerate(candidates, 1):
            if text == target:
                rank = i
                break
        cat = classify_rank1(*candidates[0], dict_keys) if candidates else None
        results[kind].append((rank, cat))

    print(f"cases skipped:          {len(skipped)}")
    for lineno, line, reason in skipped:
        print(f"  corpus/sentences.txt:{lineno}: {line!r} - {reason}", file=sys.stderr)
    print()

    for kind, label in (("sentence", "sentence-level (whole-sentence reconstruction)"),
                         ("word", "word-level (single dict-word burst, #2's real usage pattern)")):
        rows = results[kind]
        n = len(rows)
        top1 = sum(1 for rank, _ in rows if rank == 1)
        top5 = sum(1 for rank, _ in rows if rank is not None and rank <= 5)
        not_found = sum(1 for rank, _ in rows if rank is None)
        mrr = sum((1.0 / rank if rank else 0.0) for rank, _ in rows) / n
        cats = [cat for _, cat in rows if cat is not None]
        non_word = cats.count("non_word")
        non_word_rate = non_word / len(cats) if cats else float("nan")

        print(f"=== {label}: {n} cases ===")
        print(f"not found in dump:      {not_found}")
        print(f"top-1:                  {top1}/{n} = {top1 / n:.3f}")
        print(f"top-5:                  {top5}/{n} = {top5 / n:.3f}")
        print(f"MRR:                    {mrr:.3f}")
        print(f"rank-1 non-word rate:   {non_word}/{len(cats)} = {non_word_rate:.3f}")
        print()


if __name__ == "__main__":
    main()
