#!/usr/bin/env python3
"""Check AC-203-v1 current-action frontend timing against the accepted collector.

This script compiles the production Squirrel controller/archive/text-client and
librime seam from an isolated export of the committed head, drives the declared
TIME203 cases into a genuine collector, and verifies persisted/query results.
It does not implement a second frontend or a second archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

CONTRACT = "AC-203-v1"
BACKEND_COMMIT = "1fdc1f6656a98ee60e0d704effdbe782a875c78b"
BACKEND_TREE = "8a94bab5dc124a8cbba9ae414d4980ee47f6c941"
FRONTEND_BASE = "25dcef379ce6954a2a4274560c9ec85bb13ed999"
WATCHDOG_MS = 2000
# The backend export's own ignored work root is generated checker state, not
# part of the tracked export identity.
EXPORT_IGNORED_ENTRIES = {".local-work"}
HARNESS_PATH = "probes/input_archive_frontend_harness.swift"
DOCS_PATH = "docs/input-archive-frontend.md"
REQUIRED_CASES = (
    "barrier_no_sample_before_release",
    "barrier_correct_interval",
    "panel_endpoint",
    "marked_text_endpoint",
    "commit_call_separate",
    "raw_finalization_unknown_primary",
    "identity_equal_text_distinct",
    "identity_commit_process_cut",
    "identity_raw_then_next_key",
    "identity_retarget_segment",
    "nested_single_sample",
    "unknown_idle_command_unavailable",
    "numeric_conversion_self_test",
    "exclusions_pause_resume",
    "exclusions_secure_schema_stale",
    "fault_absent_collector",
    "fault_held_collector",
    "behavior_capture_parity",
    "five_probes",
    "privacy_canary_and_schema_docs",
)
PROBES = (
    ("app_retarget", "sources/AppRetarget.swift", "probes/app_retarget_probe.swift", []),
    ("composition_finalization", "sources/CompositionFinalization.swift", "probes/composition_finalization_probe.swift", []),
    ("modifier_physical_keys", "sources/ModifierPhysicalKeys.swift", "probes/modifier_physical_keys_probe.swift", ["-framework", "AppKit", "-framework", "Carbon"]),
    ("paging_hit_paths", "sources/PagingHitPaths.swift", "probes/paging_hit_paths_probe.swift", ["-framework", "CoreGraphics"]),
    ("cli_build_status", "sources/CLIBuildStatus.swift", "probes/cli_build_status_probe.swift", []),
)
CANARIES = ("你好", "甲正", "甲敏", "甲斥", "jiazheng", "jiamin", "jiachi", "INV-")
TIMING_OBJECT_KEYS = {
    "version", "action_id", "action", "operation", "clock", "event_queue_wait",
    "nested_actions", "continuity_cut", "association", "update_calls", "endpoint",
    "entry_ticks", "endpoint_ticks", "duration_ns", "validity", "unknown_reason",
    "commit_call",
}
CONTENT_KEY_NAMES = {
    "text", "preedit", "candidates", "comments", "key", "keys", "host", "document",
    "committed", "input", "selection",
}
DOC_FIELDS = (
    "frontend_timing", "version", "entry_ticks", "endpoint_ticks", "duration_ns",
    "validity", "unknown_reason", "commit_call", "mach_absolute_time", "action_id",
    "continuity_segment_id", "event_queue_wait",
)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_oid(path):
    with open(path, "rb") as handle:
        content = handle.read()
    return hashlib.sha1(b"blob %d\0" % len(content) + content).digest()


def git_tree_oid(path, top=True):
    entries = []
    with os.scandir(path) as iterator:
        for item in iterator:
            if top and item.name in EXPORT_IGNORED_ENTRIES:
                continue
            info = item.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise RuntimeError("backend export contains a symlink: %s" % item.path)
            if stat.S_ISDIR(info.st_mode):
                mode = b"40000"
                oid = bytes.fromhex(git_tree_oid(item.path, top=False))
                sort_name = os.fsencode(item.name) + b"/"
            elif stat.S_ISREG(info.st_mode):
                mode = b"100755" if info.st_mode & 0o111 else b"100644"
                oid = git_blob_oid(item.path)
                sort_name = os.fsencode(item.name) + b"\0"
            else:
                raise RuntimeError("backend export contains a non-file entry: %s" % item.path)
            entries.append((sort_name, mode, os.fsencode(item.name), oid))
    entries.sort(key=lambda value: value[0])
    payload = b"".join(mode + b" " + name + b"\0" + oid for _, mode, name, oid in entries)
    return hashlib.sha1(b"tree %d\0" % len(payload) + payload).hexdigest()


def backend_file_count(path):
    count = 0
    for _, dirs, files in os.walk(path, followlinks=False):
        if _ == path:
            dirs[:] = [name for name in dirs if name not in EXPORT_IGNORED_ENTRIES]
        if any(os.path.islink(os.path.join(_, name)) for name in dirs):
            raise RuntimeError("backend export contains a symlink directory")
        count += len(files)
    return count


def validate_backend(path):
    if not os.path.isdir(path) or os.path.islink(path):
        raise RuntimeError("backend export is unavailable")
    count = backend_file_count(path)
    tree = git_tree_oid(path)
    if tree != BACKEND_TREE:
        raise RuntimeError("backend export identity mismatch: files=%s tree=%s" % (count, tree))
    return {"files": count, "tree": tree}


def reject_symlink_components(path):
    current = os.path.sep
    for component in os.path.abspath(path).split(os.path.sep):
        if not component:
            continue
        current = os.path.join(current, component)
        if not os.path.lexists(current):
            break
        if stat.S_ISLNK(os.lstat(current).st_mode):
            raise RuntimeError("output path contains a symlink: %s" % current)


def private_dir(path):
    path = os.path.abspath(path)
    reject_symlink_components(path)
    if os.path.lexists(path):
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RuntimeError("private output path is not a real directory: %s" % path)
        if info.st_uid != os.geteuid():
            raise RuntimeError("private output directory is not owned by this user: %s" % path)
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError("private output directory mode is not 0700: %s" % path)
        return
    os.makedirs(path, mode=0o700, exist_ok=False)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("private output directory creation failed: %s" % path)


def write_private(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    reject_symlink_components(parent)
    parent_info = os.lstat(parent)
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode) or parent_info.st_uid != os.geteuid():
        raise RuntimeError("private output parent is not a real directory: %s" % parent)
    flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    if stat.S_IMODE(os.lstat(path).st_mode) != 0o600:
        raise RuntimeError("private output file mode is not 0600: %s" % path)


def run(command, cwd=None, env=None, timeout=180):
    merged = os.environ.copy()
    merged["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        merged.update(env)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return completed.returncode, completed.stdout, completed.stderr


def runtime_facts():
    facts = {
        "python": sys.version,
        "python_executable": os.path.realpath(sys.executable),
        "os_version": platform.mac_ver()[0],
        "architecture": platform.machine(),
    }
    for name, command in (
        ("xcode", ["xcodebuild", "-version"]),
        ("swiftc", ["xcrun", "swiftc", "--version"]),
    ):
        code, out, err = run(command, timeout=30)
        if code != 0:
            raise RuntimeError("could not identify %s runtime" % name)
        facts[name] = out.strip()
    return facts


def compiled_source_hashes(source_root):
    sources = sorted(
        os.path.join("sources", name)
        for name in os.listdir(os.path.join(source_root, "sources"))
        if name.endswith(".swift") and name != "Main.swift"
    )
    paths = sources + ["sources/Squirrel-Bridging-Header.h", HARNESS_PATH]
    return {path: sha256(os.path.join(source_root, path)) for path in paths}


def source_digest(source_hashes):
    content = "".join("%s\0%s\n" % (path, source_hashes[path]) for path in sorted(source_hashes))
    return hashlib.sha256(content.encode()).hexdigest()


def export_isolated_checkout(destination, source_root):
    code, head, err = run(["git", "rev-parse", "HEAD"], cwd=source_root)
    if code != 0:
        raise RuntimeError("cannot identify HEAD: %s" % err)
    head = head.strip()
    code, dirty, err = run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source_root)
    if code != 0:
        raise RuntimeError("cannot read delivery tree status: %s" % err)
    if dirty.strip():
        raise RuntimeError("isolated checkout requires a clean delivery tree")
    private_dir(destination)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", head],
        cwd=source_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if archive.returncode != 0:
        raise RuntimeError("git archive failed: %s" % archive.stderr.decode("utf-8", "replace"))
    extract = subprocess.run(
        ["tar", "-x", "-C", destination],
        input=archive.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if extract.returncode != 0:
        raise RuntimeError("isolated extract failed: %s" % extract.stderr.decode("utf-8", "replace"))
    if not os.path.isfile(os.path.join(destination, "sources", "SquirrelInputController.swift")):
        raise RuntimeError("isolated checkout is missing the frontend seam")
    if not os.path.isfile(os.path.join(destination, HARNESS_PATH)):
        raise RuntimeError("isolated checkout is missing the timing harness")
    return destination, head


def stage_include_headers(source_root, destination):
    headers = (
        "rime_api_stdbool.h", "rime_api.h", "rime/key_table.h",
        "X11/keysymdef.h", "X11/keysym.h",
    )
    candidates = {
        "rime_api_stdbool.h": ("librime/dist/include/rime_api_stdbool.h", "librime/src/rime_api_stdbool.h"),
        "rime_api.h": ("librime/dist/include/rime_api.h", "librime/src/rime_api.h"),
        "rime/key_table.h": ("librime/dist/include/rime/key_table.h", "librime/src/rime/key_table.h"),
        "X11/keysymdef.h": ("librime/include/X11/keysymdef.h",),
        "X11/keysym.h": ("librime/include/X11/keysym.h",),
    }
    if not os.path.isdir(destination):
        private_dir(destination)
    hashes = {}
    for relative in headers:
        original = None
        for candidate in candidates[relative]:
            path = os.path.join(source_root, candidate)
            if os.path.isfile(path):
                original = path
                break
        if original is None:
            raise RuntimeError("pinned librime header is unavailable: %s" % relative)
        info = os.lstat(original)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RuntimeError("librime header is not a regular file: %s" % relative)
        hashes[relative] = sha256(original)
        target = os.path.join(destination, relative)
        if os.path.lexists(target):
            if os.path.islink(target) or sha256(target) != hashes[relative]:
                raise RuntimeError("private librime header copy mismatch: %s" % relative)
            continue
        private_dir(os.path.dirname(target))
        with open(original, "rb") as incoming:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(target, flags, 0o600)
            with os.fdopen(fd, "wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
        if sha256(target) != hashes[relative] or stat.S_IMODE(os.lstat(target).st_mode) != 0o600:
            raise RuntimeError("private librime header staging failed: %s" % relative)
    return hashes


def compile_harness(probes, source_root, library_dir, include_dir):
    private_dir(probes)
    app = os.path.join(probes, "Harness.app", "Contents", "MacOS")
    private_dir(app)
    plist = os.path.join(probes, "Harness.app", "Contents", "Info.plist")
    write_private(plist, """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.ac203.harness</string>
<key>CFBundleExecutable</key><string>harness</string>
<key>CFBundleVersion</key><string>203</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
</dict></plist>
""")
    sources = sorted(
        os.path.join("sources", name)
        for name in os.listdir(os.path.join(source_root, "sources"))
        if name.endswith(".swift") and name != "Main.swift"
    )
    binary = os.path.abspath(os.path.join(app, "harness"))
    command = [
        "xcrun", "swiftc", "-parse-as-library", "-swift-version", "5",
        "-enable-bare-slash-regex", "-O",
        "-import-objc-header", "sources/Squirrel-Bridging-Header.h",
        "-I", os.path.abspath(include_dir), "-L", os.path.abspath(library_dir), "-lrime.1",
        "-Xlinker", "-rpath", "-Xlinker", os.path.abspath(library_dir),
        "-framework", "AppKit", "-framework", "InputMethodKit",
        "-framework", "Carbon", "-framework", "UserNotifications",
        "-framework", "CoreGraphics",
    ] + sources + [HARNESS_PATH, "-o", binary]
    if os.path.lexists(binary):
        raise RuntimeError("harness output already exists: %s" % binary)
    code, out, err = run(command, cwd=source_root, timeout=600)
    if code != 0:
        sys.stderr.write(err)
        raise SystemExit(code)
    os.chmod(binary, 0o700)
    return binary


def write_schema(shared, user, socket):
    private_dir(shared)
    private_dir(user)
    schema = """schema:
  schema_id: luna_pinyin
  name: invented
version: "1"
engine:
  processors:
    - ascii_composer
    - recognizer
    - key_binder
    - speller
    - punctuator
    - selector
    - navigator
    - express_editor
  segmentors:
    - ascii_segmentor
    - matcher
    - abc_segmentor
    - punct_segmentor
    - fallback_segmentor
  translators:
    - punct_translator
    - script_translator
speller:
  alphabet: zyxwvutsrqponmlkjihgfedcba
  delimiter: " '"
translator:
  dictionary: luna_pinyin
"""
    dictionary = """---
name: luna_pinyin
version: "1"
sort: original
...
你\tni
泥\tni
呢\tni
拟\tni
逆\tni
腻\tni
尼\tni
倪\tni
好\thao
号\thao
豪\thao
你好\tnihao
甲正\tjiazheng
甲斥\tjiachi
甲敏\tjiamin
"""
    other = """schema:
  schema_id: other_schema
  name: other
version: "1"
engine:
  processors:
    - ascii_composer
    - recognizer
    - key_binder
    - speller
    - punctuator
    - selector
    - navigator
    - express_editor
  segmentors:
    - ascii_segmentor
    - matcher
    - abc_segmentor
    - punct_segmentor
    - fallback_segmentor
  translators:
    - script_translator
speller:
  alphabet: zyxwvutsrqponmlkjihgfedcba
translator:
  dictionary: other_schema
"""
    write_private(os.path.join(shared, "default.yaml"), "schema_list:\n  - schema: luna_pinyin\n  - schema: other_schema\nmenu:\n  page_size: 5\n")
    write_private(os.path.join(shared, "luna_pinyin.schema.yaml"), schema)
    write_private(os.path.join(shared, "luna_pinyin.dict.yaml"), dictionary)
    write_private(os.path.join(shared, "other_schema.schema.yaml"), other)
    write_private(os.path.join(shared, "other_schema.dict.yaml"), "---\nname: other_schema\nversion: \"1\"\nsort: original\n...\n测\tce\n甲斥\tjiachi\n")
    write_private(
        os.path.join(user, "squirrel.yaml"),
        "config_version: \"1\"\ninput_archive:\n  socket: \"%s\"\nstyle:\n  inline_preedit: true\n" % socket,
    )


def collector_command(root, socket, *extra):
    return ["/usr/bin/python3", "-m", "archive.cli", "--root", root, "--socket", socket, *extra]


def start_collector(backend, root, socket, **limits):
    command = collector_command(root, socket, "collector", "start")
    for key, value in limits.items():
        command.extend(["--" + key.replace("_", "-"), str(value)])
    code, out, err = run(command, env={"PYTHONPATH": backend})
    if code != 0:
        sys.stderr.write(err or out)
        raise SystemExit(code)
    return out


def stop_collector(backend, root, socket):
    run(collector_command(root, socket, "collector", "stop"), env={"PYTHONPATH": backend})


def policy(backend, socket, action, expect_revision=None):
    command = ["/usr/bin/python3", "-m", "archive.cli", "--socket", socket, "policy", action]
    if expect_revision is not None:
        command.extend(["--expect-revision", str(expect_revision)])
    code, out, err = run(command, env={"PYTHONPATH": backend})
    return code, out + err


def cli(backend, socket, *args):
    code, out, err = run(
        ["/usr/bin/python3", "-m", "archive.cli", "--socket", socket, "--json", *args],
        env={"PYTHONPATH": backend},
    )
    if code != 0:
        return code, {}, err
    try:
        return code, json.loads(out), err
    except json.JSONDecodeError:
        return code, {}, out + err


def query_timeline(backend, socket):
    rows = []
    cursor = ""
    while True:
        args = ["query", "timeline", "--page-size", "50"]
        if cursor:
            args.extend(["--cursor", cursor])
        code, body, err = cli(backend, socket, *args)
        if code != 0:
            return code, rows, err
        page = body.get("body") or {}
        rows.extend(page.get("observations") or [])
        next_cursor = page.get("next_cursor")
        if next_cursor in (None, ""):
            break
        next_cursor = str(next_cursor)
        if next_cursor == cursor:
            return 1, rows, "timeline cursor did not advance"
        cursor = next_cursor
    return 0, rows, ""


def query_process_detail(backend, socket, process_id):
    rows = []
    cursor = ""
    while True:
        args = ["query", "process", "--process-id", process_id, "--private-detail", "--page-size", "50"]
        if cursor:
            args.extend(["--cursor", cursor])
        code, page, err = cli(backend, socket, *args)
        if code != 0:
            return code, rows, err
        body = page.get("body") or {}
        rows.extend(body.get("observations") or [])
        next_cursor = body.get("next_cursor")
        if next_cursor in (None, ""):
            break
        next_cursor = str(next_cursor)
        if next_cursor == cursor:
            return 1, rows, "process cursor did not advance"
        cursor = next_cursor
    return 0, rows, ""


def timing_rows(rows):
    return [
        row for row in rows
        if row.get("observation_kind") == "provenance" and row.get("stage") == "frontend_timing"
    ]


def rows_in_range(rows, sequence_before, sequence_after, source=None):
    selected = []
    for row in rows:
        if source and row.get("source_instance_id") != source:
            continue
        if isinstance(row.get("source_local_sequence"), int) \
                and int(sequence_before) < row["source_local_sequence"] <= int(sequence_after):
            selected.append(row)
    return selected


def wait_for_durable(backend, socket, source, sequence_after, timeout=6.0):
    """Wait until the collector has checkpointed observations up to the run's
    last admitted sequence. Durable visibility lags admission."""
    if not source or not isinstance(sequence_after, int) or sequence_after <= 0:
        time.sleep(0.3)
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        code, rows, err = query_timeline(backend, socket)
        if code == 0 and any(
            row.get("source_instance_id") == source
            and isinstance(row.get("source_local_sequence"), int)
            and row["source_local_sequence"] >= sequence_after
            for row in rows
        ):
            return True
        time.sleep(0.1)
    return False


def harness(binary, shared, user, log, socket, scenario, report, extra=()):
    code, out, err = run(
        [binary, "--shared", shared, "--user", user, "--log", log, "--socket", socket,
         "--scenario", scenario, "--report", report, *extra],
        timeout=600,
    )
    leaked = any(token in out or token in err for token in CANARIES)
    return code, out, err, leaked


def harness_process(binary, shared, user, log, socket, scenario, report, extra=()):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.Popen(
        [binary, "--shared", shared, "--user", user, "--log", log, "--socket", socket,
         "--scenario", scenario, "--report", report, *extra],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def read_report(path):
    if not os.path.isfile(path):
        return {}
    with open(path) as handle:
        return json.load(handle)


def harness_failures(report):
    return list(report.get("failures") or [])


def recursive_content_violation(value, canaries=CANARIES, forbidden_keys=CONTENT_KEY_NAMES):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in forbidden_keys:
                return "forbidden_key:%s" % key
            violation = recursive_content_violation(item, canaries, forbidden_keys)
            if violation:
                return violation
    elif isinstance(value, list):
        for item in value:
            violation = recursive_content_violation(item, canaries, forbidden_keys)
            if violation:
                return violation
    elif isinstance(value, str):
        for token in canaries:
            if token in value:
                return "canary:%s" % token
    return None


def timing_object_violation(payload):
    if not isinstance(payload, dict):
        return "payload_not_object"
    if set(payload.keys()) != {"frontend_timing"}:
        return "payload_extra_keys"
    timing = payload.get("frontend_timing")
    if not isinstance(timing, dict):
        return "timing_not_object"
    extra = set(timing.keys()) - TIMING_OBJECT_KEYS
    if extra:
        return "timing_extra_keys:%s" % ",".join(sorted(extra))
    return recursive_content_violation(timing)


def interval_ns(start, end, numer, denom):
    if not isinstance(start, int) or not isinstance(end, int) or start <= 0 or end <= start:
        return None
    if not isinstance(numer, int) or not isinstance(denom, int) or numer <= 0 or denom <= 0:
        return None
    ticks = end - start
    return (ticks // denom) * numer + ((ticks % denom) * numer) // denom


class CaseResults:
    def __init__(self):
        self.cases = {}

    def record(self, case_id, failed, evidence=None):
        self.cases[case_id] = {
            "result": "pass" if not failed else "fail",
            "failed": failed,
            "evidence": evidence or {},
        }

    def failures(self):
        result = []
        for case_id, case in self.cases.items():
            result.extend("%s:%s" % (case_id, code) for code in case["failed"])
        return result


def case_failure(case_id, codes):
    return [code for code in codes if code]


def self_test():
    failures = []
    # Timing-object content controls: a text-bearing payload must be rejected and
    # a real timing object must pass.
    if timing_object_violation({"frontend_timing": {"version": 1, "text": "你好"}}) is None:
        failures.append("timing_content_positive")
    if timing_object_violation({"frontend_timing": {"version": 1, "endpoint": "panel_update"}, "text": "x"}) is None:
        failures.append("payload_extra_positive")
    if timing_object_violation({"frontend_timing": {"version": 1, "action_id": "act1", "validity": "valid"}}) is not None:
        failures.append("timing_clean_negative")
    if recursive_content_violation({"a": ["你好"]}) is None:
        failures.append("canary_positive")
    if recursive_content_violation({"a": ["clean"]}) is not None:
        failures.append("canary_negative")
    # Interval consistency: the checker recomputes the archived duration.
    if interval_ns(100, 200, 125, 3) != (100 // 3) * 125 + ((100 % 3) * 125) // 3:
        failures.append("interval_consistency")
    for start, end in ((0, 100), (100, 100), (200, 100)):
        if interval_ns(start, end, 125, 3) is not None:
            failures.append("interval_invalid_positive")
            break
    if interval_ns(1, 2, 0, 3) is not None:
        failures.append("interval_zero_timebase")
    if not REQUIRED_CASES or len(set(REQUIRED_CASES)) != len(REQUIRED_CASES):
        failures.append("case_declaration")
    if WATCHDOG_MS != 2000:
        failures.append("watchdog_constant")
    if len(BACKEND_COMMIT) != 40 or len(BACKEND_TREE) != 40 or len(FRONTEND_BASE) != 40:
        failures.append("identity_constant")
    rows = [
        {"observation_kind": "provenance", "stage": "frontend_timing", "source_local_sequence": 5},
        {"observation_kind": "input_change", "stage": "frontend_update", "source_local_sequence": 6},
        {"observation_kind": "provenance", "stage": "other", "source_local_sequence": 7},
    ]
    if [row["source_local_sequence"] for row in timing_rows(rows)] != [5]:
        failures.append("timing_row_filter")
    if [row["source_local_sequence"] for row in rows_in_range(rows, 4, 6)] != [5, 6]:
        failures.append("range_filter")
    if failures:
        sys.stderr.write("self-test failed: %s\n" % ",".join(failures))
        return 1
    sys.stdout.write("self-test ok content_included=false\n")
    return 0


def docs_check(source_root):
    path = os.path.join(source_root, DOCS_PATH)
    if not os.path.isfile(path):
        return {"present": False, "missing_fields": list(DOC_FIELDS)}
    with open(path) as handle:
        text = handle.read()
    missing = [field for field in DOC_FIELDS if field not in text]
    return {"present": True, "missing_fields": missing, "sha256": sha256(path)}


def run_probes(probes_dir, source_root):
    private_dir(probes_dir)
    results = {}
    exits = {}
    for name, source, probe, frameworks in PROBES:
        binary = os.path.join(probes_dir, name)
        if os.path.lexists(binary):
            raise RuntimeError("probe binary path already exists: %s" % binary)
        code, out, err = run(
            ["xcrun", "swiftc", "-parse-as-library", source, probe, "-o", binary, *frameworks],
            cwd=source_root,
        )
        if code != 0:
            results[name] = "compile_failed"
            exits[name] = code
            continue
        os.chmod(binary, 0o700)
        code, out, err = run([binary], cwd=source_root)
        results[name] = "pass" if code == 0 else "fail"
        exits[name] = code
    return results, exits


def contract(args):
    results = CaseResults()
    commands = []
    artifacts = {}
    source_root = os.path.abspath(os.getcwd())
    backend_path = os.path.abspath(args.backend)
    library_dir = os.path.abspath(args.library_dir)
    root = os.path.abspath(args.root)
    private_dir(root)
    report_path = os.path.abspath(args.report)
    if os.path.lexists(report_path):
        raise RuntimeError("report path already exists: %s" % report_path)

    backend_identity = validate_backend(backend_path)
    facts = runtime_facts()
    iso_root, head = export_isolated_checkout(os.path.join(root, "source"), source_root)
    source_hashes = compiled_source_hashes(iso_root)
    source_digest_value = source_digest(source_hashes)
    # Headers come from the delivery's own checked-out librime submodule; the
    # isolated export intentionally contains only tracked Squirrel files.
    include_hashes = stage_include_headers(source_root, os.path.join(root, "include"))
    librime_library = os.path.join(library_dir, "librime.1.dylib")
    if not os.path.isfile(librime_library):
        raise RuntimeError("own librime library is unavailable: %s" % librime_library)
    library_hash = sha256(librime_library)

    plan = {
        "contract": CONTRACT,
        "head": head,
        "frontend_base": FRONTEND_BASE,
        "backend": {"commit": BACKEND_COMMIT, **backend_identity, "path": backend_path},
        "library": {"path": librime_library, "sha256": library_hash},
        "source_digest_sha256": source_digest_value,
        "header_hashes": include_hashes,
        "runtime": facts,
        "watchdog_ms": WATCHDOG_MS,
        "required_cases": list(REQUIRED_CASES),
        "content_included": False,
    }
    write_private(os.path.join(root, "plan.json"), json.dumps(plan, indent=2, sort_keys=True) + "\n")
    sys.stdout.write("plan declared cases=%d watchdog_ms=%d content_included=false\n" % (
        len(REQUIRED_CASES), WATCHDOG_MS
    ))

    shared = os.path.join(root, "rime-shared")
    user = os.path.join(root, "rime-user")
    log = os.path.join(root, "rime-log")
    collector_root = os.path.join(root, "collector")
    socket = os.path.join(collector_root, "s")
    if len(os.fsencode(socket)) > 103:
        raise RuntimeError("collector socket path exceeds macOS sun_path")
    write_schema(shared, user, socket)
    private_dir(collector_root)
    start_collector(backend_path, collector_root, socket)
    commands.append({"argv": ["collector", "start"], "exit": 0})
    code, out = policy(backend_path, socket, "enable", expect_revision=0)
    commands.append({"argv": ["policy", "enable"], "exit": code})
    if code != 0:
        raise RuntimeError("collector policy enable failed")

    binary = compile_harness(os.path.join(root, "probes"), iso_root, library_dir, os.path.join(root, "include"))
    commands.append({"argv": ["swiftc", "harness"], "exit": 0})
    artifacts["harness_sha256"] = sha256(binary)
    artifacts["harness_path"] = binary

    try:
        # --- numeric conversion self-tests (production builder) ---
        report = os.path.join(root, "timing-numeric.json")
        code, out, err, leaked = harness(binary, shared, user, log, socket, "timing-numeric", report)
        commands.append({"argv": ["harness", "timing-numeric"], "exit": code})
        numeric = read_report(report)
        failures = harness_failures(numeric)
        timing_numeric = numeric.get("timing_numeric") or {}
        if code != 0:
            failures.append("harness_exit")
        for key in (
            "normal_matches", "overflow_rejected", "zero_length_rejected",
            "nonmonotone_rejected", "absent_start_rejected", "unrepresentable_rejected",
        ):
            if timing_numeric.get(key) is not True:
                failures.append(key)
        if timing_numeric.get("valid_version") != 1:
            failures.append("valid_version")
        if timing_numeric.get("valid_duration") != timing_numeric.get("valid_expected_duration"):
            failures.append("valid_duration")
        if timing_numeric.get("valid_update_calls") != 2:
            failures.append("valid_update_calls")
        if timing_numeric.get("unknown_validity") != "unknown" or timing_numeric.get("unknown_reason") != "no_update_call":
            failures.append("unknown_semantics")
        if timing_numeric.get("unknown_has_duration") is not False:
            failures.append("unknown_duration")
        if timing_numeric.get("unknown_commit_validity") != "valid":
            failures.append("unknown_commit_call")
        if timing_numeric.get("invalid_validity") != "invalid" or timing_numeric.get("invalid_reason") != "nonmonotone_endpoint":
            failures.append("invalid_semantics")
        if timing_numeric.get("invalid_has_duration") is not False:
            failures.append("invalid_duration")
        if leaked:
            failures.append("content_leak")
        results.record("numeric_conversion_self_test", case_failure("numeric", failures), {"numeric": timing_numeric})

        # --- controlled callback barrier ---
        held = os.path.join(root, "barrier-held.json")
        release = os.path.join(root, "barrier-release")
        barrier_report = os.path.join(root, "timing-barrier.json")
        process = harness_process(
            binary, shared, user, log, socket, "timing-barrier", barrier_report,
            ("--barrier-held", held, "--barrier-release", release),
        )
        deadline = time.time() + 90
        while not os.path.lexists(held) and process.poll() is None and time.time() < deadline:
            time.sleep(0.01)
        if not os.path.lexists(held):
            process.kill()
            process.communicate()
            results.record("barrier_no_sample_before_release", ["barrier_not_reached"])
            results.record("barrier_correct_interval", ["barrier_not_reached"])
        else:
            marker = read_report(held)
            code, held_rows, err = query_timeline(backend_path, socket)
            before_release = [
                row for row in timing_rows(held_rows)
                if row.get("source_instance_id") == marker.get("source_instance_id")
                and isinstance(row.get("source_local_sequence"), int)
                and row["source_local_sequence"] > int(marker.get("sequence_before", 0))
            ]
            release_failures = []
            if code != 0:
                release_failures.append("query_failed")
            if before_release:
                release_failures.append("sample_before_release")
            if marker.get("timing_records_before") != 0:
                release_failures.append("marker_identity")
            write_private(release, "release\n")
            out, err = process.communicate(timeout=120)
            barrier = read_report(barrier_report)
            failures = harness_failures(barrier)
            if process.returncode != 0:
                failures.append("harness_exit")
            if leaked:
                failures.append("content_leak")
            results.record(
                "barrier_no_sample_before_release",
                case_failure("barrier", release_failures + failures),
                {"marker": marker, "timing_rows_before_release": len(before_release)},
            )
            interval_failures = []
            barrier_case = barrier.get("timing_barrier") or {}
            wait_for_durable(
                backend_path, socket,
                barrier_case.get("source_instance_id") or marker.get("source_instance_id"),
                int(barrier_case.get("sequence_after", 0) or 0),
            )
            code, rows, err = query_timeline(backend_path, socket)
            if code != 0:
                interval_failures.append("query_failed")
            action_id = barrier_case.get("action_id") or marker.get("action_id") or ""
            candidates = [
                row for row in timing_rows(rows)
                if row.get("source_instance_id") == (barrier_case.get("source_instance_id") or marker.get("source_instance_id"))
                and row.get("source_local_sequence") is not None
                and int(barrier_case.get("sequence_before", 0)) < int(row["source_local_sequence"]) <= int(barrier_case.get("sequence_after", 0))
            ]
            if len(candidates) != 1:
                interval_failures.append("timing_row_count")
            payload = None
            if len(candidates) == 1:
                detail_code, detail_rows, detail_err = query_process_detail(
                    backend_path, socket, candidates[0].get("process_id")
                )
                if detail_code != 0:
                    interval_failures.append("detail_query_failed")
                for detail in detail_rows:
                    if detail.get("source_local_sequence") == candidates[0].get("source_local_sequence") \
                            and detail.get("observation_kind") == "provenance":
                        payload = detail.get("payload")
                        break
                timing = (payload or {}).get("frontend_timing") if isinstance(payload, dict) else None
                if not isinstance(timing, dict):
                    interval_failures.append("timing_object_missing")
                else:
                    if timing.get("action_id") != action_id:
                        interval_failures.append("action_identity")
                    if timing.get("version") != 1:
                        interval_failures.append("version")
                    if timing.get("validity") != "valid":
                        interval_failures.append("validity")
                    if timing.get("endpoint") not in ("marked_text", "panel_update"):
                        interval_failures.append("endpoint")
                    clock = timing.get("clock") or {}
                    numer = clock.get("timebase_numer")
                    denom = clock.get("timebase_denom")
                    if clock.get("domain") != "mach_absolute_time" or clock.get("unit") != "nanoseconds":
                        interval_failures.append("clock_domain")
                    entry = timing.get("entry_ticks")
                    endpoint = timing.get("endpoint_ticks")
                    expected = interval_ns(entry, endpoint, numer, denom)
                    if expected is None or timing.get("duration_ns") != expected:
                        interval_failures.append("duration_consistency")
                    before_ticks = barrier_case.get("before_ticks")
                    marked_ticks = barrier_case.get("marked_ticks")
                    after_ticks = barrier_case.get("after_ticks")
                    if not all(isinstance(value, int) for value in (before_ticks, marked_ticks, after_ticks)):
                        interval_failures.append("harness_ticks")
                    elif not (before_ticks <= entry <= marked_ticks <= endpoint <= after_ticks):
                        interval_failures.append("interval_bracketing")
                    calls = timing.get("update_calls") or []
                    call_names = [call.get("endpoint") for call in calls if isinstance(call, dict)]
                    if "marked_text" not in call_names or timing.get("endpoint") not in call_names:
                        interval_failures.append("update_calls")
                    if timing_object_violation(payload) is not None:
                        interval_failures.append("timing_content")
            results.record(
                "barrier_correct_interval",
                case_failure("barrier_interval", interval_failures),
                {"timing_row_count": len(candidates), "timing_object": payload if len(candidates) == 1 else {}},
            )

        # --- endpoint controls ---
        report = os.path.join(root, "timing-endpoints.json")
        code, out, err, leaked = harness(binary, shared, user, log, socket, "timing-endpoints", report)
        commands.append({"argv": ["harness", "timing-endpoints"], "exit": code})
        endpoints = read_report(report)
        failures = harness_failures(endpoints)
        if code != 0:
            failures.append("harness_exit")
        if leaked:
            failures.append("content_leak")
        wait_for_durable(
            backend_path, socket,
            (endpoints.get("timing_endpoints") or {}).get("panel", {}).get("source_instance_id"),
            int((endpoints.get("timing_endpoints") or {}).get("unavailable", {}).get("sequence_after", 0) or 0),
        )
        code, rows, err = query_timeline(backend_path, socket)
        if code != 0:
            failures.append("query_failed")
        endpoint_cases = endpoints.get("timing_endpoints") or {}
        case_rows = {}
        for name, case in endpoint_cases.items():
            if not isinstance(case, dict):
                continue
            case_rows[name] = rows_in_range(
                timing_rows(rows),
                case.get("sequence_before", 0),
                case.get("sequence_after", 0),
                case.get("source_instance_id"),
            )
        payloads = {}
        for name, selected in case_rows.items():
            payloads[name] = []
            for row in selected:
                detail_code, detail_rows, detail_err = query_process_detail(backend_path, socket, row.get("process_id"))
                if detail_code != 0:
                    failures.append("detail_query_failed")
                    continue
                for detail in detail_rows:
                    if detail.get("source_local_sequence") == row.get("source_local_sequence") \
                            and detail.get("observation_kind") == "provenance":
                        payloads[name].append({"row": row, "payload": detail.get("payload")})
        panel_payloads = payloads.get("panel") or []
        if len(panel_payloads) != 1:
            failures.append("panel_row_count")
        else:
            timing = (panel_payloads[0]["payload"] or {}).get("frontend_timing") or {}
            if timing.get("endpoint") != "panel_update" or timing.get("validity") != "valid":
                failures.append("panel_endpoint")
            if timing_object_violation(panel_payloads[0]["payload"]) is not None:
                failures.append("panel_content")
        results.record("panel_endpoint", case_failure("panel", failures), {"rows": len(panel_payloads)})

        marked_failures = []
        marked_payloads = payloads.get("marked_text") or []
        if len(marked_payloads) != 1:
            marked_failures.append("row_count")
        else:
            timing = (marked_payloads[0]["payload"] or {}).get("frontend_timing") or {}
            calls = [call.get("endpoint") for call in timing.get("update_calls") or [] if isinstance(call, dict)]
            if timing.get("endpoint") != "marked_text" or "panel_update" in calls:
                marked_failures.append("marked_text_endpoint")
            if timing.get("validity") != "valid":
                marked_failures.append("validity")
            if timing_object_violation(marked_payloads[0]["payload"]) is not None:
                marked_failures.append("content")
        results.record("marked_text_endpoint", case_failure("marked_text", marked_failures), {"rows": len(marked_payloads)})

        commit_failures = []
        commit_payloads = payloads.get("commit") or []
        if len(commit_payloads) != 1:
            commit_failures.append("row_count")
        else:
            timing = (commit_payloads[0]["payload"] or {}).get("frontend_timing") or {}
            commit_call = timing.get("commit_call") or {}
            if commit_call.get("endpoint") != "insert_text" or commit_call.get("validity") != "valid":
                commit_failures.append("commit_call")
            duration = commit_call.get("duration_ns")
            if not isinstance(duration, int) or duration <= 0:
                commit_failures.append("commit_duration")
            if timing.get("endpoint") in ("insert_text",):
                commit_failures.append("primary_mislabel")
            if timing.get("validity") == "valid" and "endpoint_ticks" not in timing:
                commit_failures.append("primary_inconsistent")
            if timing.get("validity") == "unknown" and "duration_ns" in timing:
                commit_failures.append("unknown_duration")
            row = commit_payloads[0]["row"]
            terminal = [
                candidate for candidate in rows
                if candidate.get("observation_kind") == "commit_attempt"
                and candidate.get("commit_id") == row.get("commit_id")
                and candidate.get("process_id") == row.get("process_id")
            ]
            if not terminal:
                commit_failures.append("commit_relation")
            if timing_object_violation(commit_payloads[0]["payload"]) is not None:
                commit_failures.append("content")
        results.record("commit_call_separate", case_failure("commit", commit_failures), {"rows": len(commit_payloads)})

        raw_failures = []
        raw_payloads = payloads.get("raw") or []
        if len(raw_payloads) != 1:
            raw_failures.append("row_count")
        else:
            timing = (raw_payloads[0]["payload"] or {}).get("frontend_timing") or {}
            if timing.get("validity") != "unknown" or timing.get("unknown_reason") != "no_update_call":
                raw_failures.append("primary_semantics")
            if "duration_ns" in timing:
                raw_failures.append("fabricated_duration")
            commit_call = timing.get("commit_call") or {}
            if commit_call.get("validity") != "valid":
                raw_failures.append("commit_call")
            row = raw_payloads[0]["row"]
            terminal = [
                candidate for candidate in rows
                if candidate.get("observation_kind") == "raw_finalization"
                and candidate.get("commit_id") == row.get("commit_id")
                and candidate.get("process_id") == row.get("process_id")
            ]
            if not terminal:
                raw_failures.append("raw_relation")
            if timing_object_violation(raw_payloads[0]["payload"]) is not None:
                raw_failures.append("content")
        results.record("raw_finalization_unknown_primary", case_failure("raw", raw_failures), {"rows": len(raw_payloads)})

        unknown_failures = []
        if case_rows.get("command"):
            unknown_failures.append("command_row")
        if case_rows.get("idle"):
            unknown_failures.append("idle_row")
        command_case = endpoint_cases.get("command") or {}
        idle_case = endpoint_cases.get("idle") or {}
        command_refusals = sum(
            command_case.get(key + "_after", 0) - command_case.get(key + "_before", 0)
            for key in ("refused_gate", "refused_no_process", "refused_no_observation")
        )
        idle_refusals = sum(
            idle_case.get(key + "_after", 0) - idle_case.get(key + "_before", 0)
            for key in ("refused_gate", "refused_no_process", "refused_no_observation")
        )
        if command_refusals < 1:
            unknown_failures.append("command_counter")
        if idle_refusals < 1:
            unknown_failures.append("idle_counter")
        unavailable_payloads = payloads.get("unavailable") or []
        if len(unavailable_payloads) != 1:
            unknown_failures.append("unavailable_row_count")
        else:
            timing = (unavailable_payloads[0]["payload"] or {}).get("frontend_timing") or {}
            if timing.get("validity") != "unknown" or timing.get("unknown_reason") != "no_update_call":
                unknown_failures.append("unavailable_semantics")
            if "commit_call" in timing:
                unknown_failures.append("unavailable_commit")
            row = unavailable_payloads[0]["row"]
            terminal = [
                candidate for candidate in rows
                if candidate.get("observation_kind") == "unavailable_client"
                and candidate.get("process_id") == row.get("process_id")
            ]
            if not terminal:
                unknown_failures.append("unavailable_relation")
        results.record(
            "unknown_idle_command_unavailable",
            case_failure("unknown", unknown_failures),
            {"command_rows": len(case_rows.get("command") or []), "idle_rows": len(case_rows.get("idle") or []),
             "unavailable_rows": len(unavailable_payloads)},
        )

        # --- identities ---
        report = os.path.join(root, "timing-identities.json")
        code, out, err, leaked = harness(binary, shared, user, log, socket, "timing-identities", report)
        commands.append({"argv": ["harness", "timing-identities"], "exit": code})
        identities = read_report(report)
        identity_failures = harness_failures(identities)
        if code != 0:
            identity_failures.append("harness_exit")
        if leaked:
            identity_failures.append("content_leak")
        identity_waits = identities.get("timing_identities") or {}
        wait_for_durable(
            backend_path, socket,
            identity_waits.get("retarget", {}).get("source_instance_id"),
            int(identity_waits.get("retarget", {}).get("sequence_after", 0) or 0),
        )
        code, rows, err = query_timeline(backend_path, socket)
        if code != 0:
            identity_failures.append("query_failed")
        identity_report = identities.get("timing_identities") or {}
        detail = {}
        for name in ("equal_first", "equal_second", "next_key", "retarget"):
            case = identity_report.get(name) or {}
            detail[name] = rows_in_range(
                timing_rows(rows),
                case.get("sequence_before", 0),
                case.get("sequence_after", 0),
                case.get("source_instance_id"),
            )
        raw_case = identity_report.get("raw") or {}
        raw_rows = rows_in_range(
            timing_rows(rows),
            raw_case.get("sequence_before", 0),
            raw_case.get("sequence_after", 0),
            raw_case.get("source_instance_id"),
        )

        equal_failures = []
        first, second = detail.get("equal_first") or [], detail.get("equal_second") or []
        if len(first) != 1 or len(second) != 1:
            equal_failures.append("row_count")
        else:
            first_row, second_row = first[0], second[0]
            if first_row.get("process_id") == second_row.get("process_id"):
                equal_failures.append("process_reuse")
            if first_row.get("source_local_sequence") == second_row.get("source_local_sequence"):
                equal_failures.append("sequence_reuse")
            first_payload = fetch_payload(backend_path, socket, first_row)
            second_payload = fetch_payload(backend_path, socket, second_row)
            first_timing = (first_payload or {}).get("frontend_timing") or {}
            second_timing = (second_payload or {}).get("frontend_timing") or {}
            if first_timing.get("action_id") == second_timing.get("action_id"):
                equal_failures.append("action_reuse")
            if first_timing.get("association", {}).get("process_id") != first_row.get("process_id"):
                equal_failures.append("association_process")
        results.record("identity_equal_text_distinct", case_failure("equal", equal_failures), {"rows": [len(first), len(second)]})

        commit_cut_failures = []
        if len(first) != 1:
            commit_cut_failures.append("first_row_count")
        else:
            row = first[0]
            commits = [
                candidate for candidate in rows
                if candidate.get("observation_kind") == "commit_attempt" and candidate.get("process_id") == row.get("process_id")
            ]
            if not commits:
                commit_cut_failures.append("commit_relation")
            elif commits[0].get("commit_id") != row.get("commit_id"):
                commit_cut_failures.append("commit_identity")
        results.record("identity_commit_process_cut", case_failure("commit_cut", commit_cut_failures), {})

        raw_next_failures = []
        if len(raw_rows) != 1:
            raw_next_failures.append("raw_row_count")
        else:
            raw_row = raw_rows[0]
            if raw_row.get("process_id") != raw_case.get("process_before"):
                raw_next_failures.append("raw_process")
            raw_terminal = [
                candidate for candidate in rows
                if candidate.get("observation_kind") == "raw_finalization"
                and candidate.get("process_id") == raw_row.get("process_id")
            ]
            if not raw_terminal:
                raw_next_failures.append("raw_relation")
        next_rows = detail.get("next_key") or []
        if len(next_rows) != 1:
            raw_next_failures.append("next_row_count")
        else:
            next_row = next_rows[0]
            if len(raw_rows) == 1 and next_row.get("process_id") == raw_rows[0].get("process_id"):
                raw_next_failures.append("stale_process")
            next_case = identity_report.get("next_key") or {}
            next_pages = [
                row for row in rows
                if row.get("source_instance_id") == next_case.get("source_instance_id")
                and isinstance(row.get("source_local_sequence"), int)
                and int(next_case.get("sequence_before", 0)) < row["source_local_sequence"] <= int(next_case.get("sequence_after", 0))
                and row.get("observation_kind") in ("start", "input_change")
            ]
            if not next_pages or next_pages[0].get("process_id") != next_row.get("process_id"):
                raw_next_failures.append("next_process")
        results.record("identity_raw_then_next_key", case_failure("raw_next", raw_next_failures), {"raw_rows": len(raw_rows), "next_rows": len(next_rows)})

        retarget_failures = []
        retarget_rows = detail.get("retarget") or []
        if len(retarget_rows) != 1:
            retarget_failures.append("row_count")
        else:
            row = retarget_rows[0]
            payload = fetch_payload(backend_path, socket, row)
            timing = (payload or {}).get("frontend_timing") or {}
            if timing.get("continuity_cut") is not True:
                retarget_failures.append("cut_flag")
            association = timing.get("association") or {}
            if association.get("continuity_segment_id") != retarget_row_segment(row, rows):
                retarget_failures.append("segment_binding")
            if association.get("continuity_segment_id") == raw_case.get("segment_before"):
                retarget_failures.append("stale_segment")
        results.record("identity_retarget_segment", case_failure("retarget", retarget_failures), {"rows": len(retarget_rows)})

        # --- nested control ---
        report = os.path.join(root, "timing-nested.json")
        code, out, err, leaked = harness(binary, shared, user, log, socket, "timing-nested", report)
        commands.append({"argv": ["harness", "timing-nested"], "exit": code})
        nested = read_report(report)
        nested_failures = harness_failures(nested)
        if code != 0:
            nested_failures.append("harness_exit")
        if leaked:
            nested_failures.append("content_leak")
        nested_wait = nested.get("timing_nested") or {}
        wait_for_durable(
            backend_path, socket,
            nested_wait.get("source_instance_id"),
            int(nested_wait.get("sequence_after", 0) or 0),
        )
        code, rows, err = query_timeline(backend_path, socket)
        nested_report = nested.get("timing_nested") or {}
        nested_rows = rows_in_range(
            timing_rows(rows),
            nested_report.get("sequence_before", 0),
            nested_report.get("sequence_after", 0),
            nested_report.get("source_instance_id"),
        )
        if len(nested_rows) != 1:
            nested_failures.append("row_count")
        else:
            payload = fetch_payload(backend_path, socket, nested_rows[0])
            timing = (payload or {}).get("frontend_timing") or {}
            if timing.get("nested_actions") != 1:
                nested_failures.append("nested_count")
            if timing.get("action_id") != nested_report.get("action_id"):
                nested_failures.append("action_identity")
            if timing.get("validity") != "valid":
                nested_failures.append("validity")
        results.record("nested_single_sample", case_failure("nested", nested_failures), {"rows": len(nested_rows)})

        # --- behavior parity ---
        report = os.path.join(root, "timing-behavior.json")
        code, out, err, leaked = harness(binary, shared, user, log, socket, "timing-behavior", report)
        commands.append({"argv": ["harness", "timing-behavior"], "exit": code})
        behavior = read_report(report)
        behavior_failures = harness_failures(behavior)
        if code != 0:
            behavior_failures.append("harness_exit")
        if leaked:
            behavior_failures.append("content_leak")
        behavior_report = behavior.get("timing_behavior") or {}
        for key in ("arms_equal", "insert_once_ok", "marked_cleanup_ok", "commit_arm_equal", "page_arm_equal", "command_not_consumed"):
            if behavior_report.get(key) is not True:
                behavior_failures.append(key)
        results.record("behavior_capture_parity", case_failure("behavior", behavior_failures), behavior_report)

        # --- exclusion phases ---
        pause_resume_failures = []
        secure_schema_failures = []
        exclusion_evidence = {}
        phase_specs = (
            ("baseline", None, "baseline", pause_resume_failures),
            ("paused", "pause", "paused", pause_resume_failures),
            ("resumed", "resume", "resumed", pause_resume_failures),
            ("secure", None, "secure", secure_schema_failures),
            ("schema", None, "other_schema", secure_schema_failures),
        )
        for phase, policy_action, case_key, target_failures in phase_specs:
            if policy_action:
                code, out = policy(backend_path, socket, policy_action)
                commands.append({"argv": ["policy", policy_action], "exit": code})
                if code != 0:
                    target_failures.append("policy_%s" % phase)
            report = os.path.join(root, "timing-exclusions-%s.json" % phase)
            code, out, err, leaked = harness(binary, shared, user, log, socket, "timing-exclusions", report, ("--phase", phase))
            commands.append({"argv": ["harness", "timing-exclusions", phase], "exit": code})
            data = read_report(report)
            failures = harness_failures(data)
            if code != 0:
                failures.append("harness_exit")
            if leaked:
                failures.append("content_leak")
            target_failures.extend("%s:%s" % (phase, failure) for failure in failures)
            exclusion_report = data.get("timing_exclusions") or {}
            exclusion_evidence[phase] = {
                "observed_desired": exclusion_report.get("observed_desired"),
                "fresh": exclusion_report.get("fresh"),
                "timing_records_after": exclusion_report.get("timing_records_after"),
            }
            wait_for_durable(
                backend_path, socket,
                exclusion_report.get("source_instance_id"),
                int(exclusion_report.get("sequence_after", 0) or 0),
            )
            code, rows, err = query_timeline(backend_path, socket)
            if code != 0:
                target_failures.append("query_%s" % phase)
                continue
            source = exclusion_report.get("source_instance_id")
            case = exclusion_report.get(case_key) or {}
            selected = rows_in_range(
                timing_rows(rows),
                case.get("sequence_before", 0),
                case.get("sequence_after", 0),
                case.get("source_instance_id") or source,
            )
            if phase in ("paused", "secure", "schema"):
                if selected:
                    target_failures.append("%s:persisted" % phase)
            else:
                if len(selected) != 1:
                    target_failures.append("%s:row_count" % phase)
                elif (fetch_payload(backend_path, socket, selected[0]) or {}).get("frontend_timing", {}).get("validity") != "valid":
                    target_failures.append("%s:validity" % phase)
            if phase in ("secure", "schema"):
                healthy = exclusion_report.get("healthy") or {}
                healthy_rows = rows_in_range(
                    timing_rows(rows),
                    healthy.get("sequence_before", 0),
                    healthy.get("sequence_after", 0),
                    healthy.get("source_instance_id") or source,
                )
                if len(healthy_rows) != 1:
                    target_failures.append("%s:healthy_row_count" % phase)

        # --- stale policy: stop the collector, wait for freshness to expire ---
        stop_collector(backend_path, collector_root, socket)
        commands.append({"argv": ["collector", "stop"], "exit": 0})
        report = os.path.join(root, "timing-exclusions-stale.json")
        code, out, err, leaked = harness(binary, shared, user, log, socket, "timing-exclusions", report, ("--phase", "stale"))
        commands.append({"argv": ["harness", "timing-exclusions", "stale"], "exit": code})
        data = read_report(report)
        secure_schema_failures.extend(harness_failures(data))
        if code != 0:
            secure_schema_failures.append("stale:harness_exit")
        if leaked:
            secure_schema_failures.append("stale:content_leak")
        stale_report = data.get("timing_exclusions") or {}
        if stale_report.get("fresh") != "false":
            secure_schema_failures.append("stale:not_stale")
        exclusion_evidence["stale"] = {
            "observed_desired": stale_report.get("observed_desired"),
            "fresh": stale_report.get("fresh"),
            "timing_records_after": stale_report.get("timing_records_after"),
        }
        results.record("exclusions_pause_resume", case_failure("exclusions", pause_resume_failures), exclusion_evidence)
        results.record("exclusions_secure_schema_stale", case_failure("exclusions2", secure_schema_failures), exclusion_evidence)

        # --- faults ---
        # Restart the collector for the held fault; the absent phase does not need it.
        start_collector(backend_path, collector_root, socket)
        commands.append({"argv": ["collector", "restart"], "exit": 0})
        code, out = policy(backend_path, socket, "enable", expect_revision=1)
        commands.append({"argv": ["policy", "enable"], "exit": code})
        if code != 0:
            policy(backend_path, socket, "enable")

        absent_failures = []
        report = os.path.join(root, "timing-faults-absent.json")
        code, out, err, leaked = harness(binary, shared, user, log, socket, "timing-faults", report, ("--phase", "absent"))
        commands.append({"argv": ["harness", "timing-faults", "absent"], "exit": code})
        absent = read_report(report)
        absent_failures.extend(harness_failures(absent))
        if code != 0:
            absent_failures.append("harness_exit")
        if leaked:
            absent_failures.append("content_leak")
        absent_report = absent.get("timing_faults") or {}
        elapsed = absent_report.get("elapsed_ns")
        if not isinstance(elapsed, int) or elapsed >= WATCHDOG_MS * 1_000_000:
            absent_failures.append("watchdog")
        if not isinstance(absent_report.get("client_updates"), int) or absent_report.get("client_updates", 0) <= 0:
            absent_failures.append("client_updates")
        absent_source = absent_report.get("source_instance_id")
        code, rows, err = query_timeline(backend_path, socket)
        if not absent_source:
            absent_failures.append("source_identity")
        elif code == 0 and any(
            row.get("source_instance_id") == absent_source for row in timing_rows(rows)
        ):
            absent_failures.append("unexpected_rows")
        results.record("fault_absent_collector", case_failure("absent", absent_failures), {"elapsed_ns": elapsed})

        held_failures = []
        pressure = 0
        ready = os.path.join(root, "held-ready.json")
        go = os.path.join(root, "held-go")
        report = os.path.join(root, "timing-faults-held.json")
        process = harness_process(
            binary, shared, user, log, socket, "timing-faults", report,
            ("--phase", "held", "--ready", ready, "--go", go),
        )
        deadline = time.time() + 90
        while not os.path.lexists(ready) and process.poll() is None and time.time() < deadline:
            time.sleep(0.01)
        if not os.path.lexists(ready):
            process.kill()
            process.communicate()
            held_failures.append("not_ready")
        else:
            collector_pid = read_collector_pid(collector_root)
            if not collector_pid:
                held_failures.append("collector_pid")
            else:
                os.kill(collector_pid, signal.SIGSTOP)
                write_private(go, "go\n")
                out, err = process.communicate(timeout=120)
                held = read_report(report)
                held_failures.extend(harness_failures(held))
                if process.returncode != 0:
                    held_failures.append("harness_exit")
                held_report = held.get("timing_faults") or {}
                elapsed = held_report.get("elapsed_ns")
                if not isinstance(elapsed, int) or elapsed >= WATCHDOG_MS * 1_000_000:
                    held_failures.append("watchdog")
                if not isinstance(held_report.get("client_updates"), int) or held_report.get("client_updates", 0) <= 0:
                    held_failures.append("client_updates")
                pressure = sum(
                    held_report.get(key, 0) for key in ("queued", "known_dropped", "known_refused", "unreported_loss_notices")
                    if isinstance(held_report.get(key), int)
                )
                if pressure <= 0:
                    held_failures.append("no_pressure")
                os.kill(collector_pid, signal.SIGCONT)
                time.sleep(0.5)
                code, out = policy(backend_path, socket, "status")
                if code != 0:
                    held_failures.append("collector_status")
        results.record("fault_held_collector", case_failure("held", held_failures), {"pressure": pressure})

        # --- five existing behavior probes ---
        probe_results, probe_exits = run_probes(os.path.join(root, "behavior-probes"), iso_root)
        probe_failures = [name for name, result in probe_results.items() if result != "pass"]
        results.record("five_probes", case_failure("probes", probe_failures), {"results": probe_results, "exits": probe_exits})

        # --- privacy and docs ---
        privacy_failures = []
        docs = docs_check(iso_root)
        if not docs.get("present") or docs.get("missing_fields"):
            privacy_failures.append("docs")
        if any(canary in json.dumps(results.cases) for canary in CANARIES):
            privacy_failures.append("report_canary")
        code, rows, err = query_timeline(backend_path, socket)
        detail_cache = {}
        for row in timing_rows(rows):
            process_id = row.get("process_id")
            if process_id not in detail_cache:
                detail_code, detail_rows, detail_err = query_process_detail(backend_path, socket, process_id)
                detail_cache[process_id] = {
                    detail.get("source_local_sequence"): detail.get("payload")
                    for detail in detail_rows if detail.get("observation_kind") == "provenance"
                }
            payload = detail_cache[process_id].get(row.get("source_local_sequence"))
            violation = timing_object_violation(payload)
            if violation:
                privacy_failures.append("timing_payload:%s" % violation)
                break
        if not artifacts.get("harness_sha256"):
            privacy_failures.append("harness_identity")
        results.record("privacy_canary_and_schema_docs", case_failure("privacy", privacy_failures), {"docs": docs})
    finally:
        stop_collector(backend_path, collector_root, socket)

    report = {
        "contract": CONTRACT,
        "result": "pass" if not results.failures() else "fail",
        "content_included": False,
        "head": head,
        "frontend_base": FRONTEND_BASE,
        "backend": {"commit": BACKEND_COMMIT, **backend_identity, "path": backend_path},
        "library": {"path": librime_library, "sha256": library_hash},
        "source_digest_sha256": source_digest_value,
        "source_hashes": source_hashes,
        "header_hashes": include_hashes,
        "runtime": facts,
        "watchdog_ms": WATCHDOG_MS,
        "declared_cases": list(REQUIRED_CASES),
        "cases": results.cases,
        "commands": commands,
        "artifacts": artifacts,
    }
    if any(canary in json.dumps(report) for canary in CANARIES):
        report["result"] = "fail"
        report["canary_in_report"] = True
    write_private(report_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    failures = results.failures()
    if report.get("canary_in_report"):
        failures.append("canary_in_report")
    sys.stdout.write("result=%s cases=%d failures=%d content_included=false\n" % (
        report["result"], len(results.cases), len(failures)
    ))
    for failure in failures:
        sys.stdout.write("fail %s\n" % failure)
    return 0 if report["result"] == "pass" else 1


def fetch_payload(backend, socket, row):
    code, detail_rows, err = query_process_detail(backend, socket, row.get("process_id"))
    if code != 0:
        return None
    for detail in detail_rows:
        if detail.get("source_local_sequence") == row.get("source_local_sequence") \
                and detail.get("observation_kind") == row.get("observation_kind"):
            return detail.get("payload")
    return None


def retarget_row_segment(row, rows):
    for candidate in rows:
        if candidate.get("process_id") == row.get("process_id") \
                and candidate.get("update_id") == row.get("update_id") \
                and candidate.get("observation_kind") in ("input_change", "replacement", "temporary_selection", "start"):
            return candidate.get("continuity_segment_id")
    return None


def read_collector_pid(collector_root):
    path = os.path.join(collector_root, "collector.pid")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--suite", choices=("contract",))
    parser.add_argument("--root", default="")
    parser.add_argument("--backend", default="librime/plugins/llm-rerank")
    parser.add_argument("--library-dir", default="lib")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.suite:
        sys.stderr.write("code=invalid_request\n")
        return 2
    if not args.root or not args.report:
        sys.stderr.write("code=invalid_request\n")
        return 2
    if os.path.lexists(args.root):
        sys.stderr.write("code=output_collision path=%s\n" % args.root)
        return 2
    if os.path.lexists(args.report):
        sys.stderr.write("code=output_collision path=%s\n" % args.report)
        return 2
    try:
        validate_backend(args.backend)
        if not os.path.isdir(args.library_dir) or os.path.islink(args.library_dir):
            raise RuntimeError("own library directory is unavailable")
    except (OSError, RuntimeError) as error:
        sys.stderr.write("code=invalid_request %s\n" % error)
        return 2
    try:
        return contract(args)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        sys.stderr.write("code=invalid_request %s\n" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
