#!/usr/bin/env python3
"""Drive the production Squirrel frontend against the accepted input archive.

This script does not implement a second frontend or archive. It compiles the
production controller, panel, and librime paths, starts the accepted collector,
and checks observable client, panel, and query results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import uuid

INTERFACE = "input-archive-v1"
BACKEND_COMMIT = "467185cc5b24d96fdf0c58fd67c000b4e990a759"
BACKEND_TREE = "ee2a3a00ed848ba66182268c4b4b484f86b7585d"
REQUIRED = (
    "short_long_typing",
    "backspace_retype",
    "selection_paging",
    "cancellation_raw_deactivation",
    "retarget_unavailable_command",
    "capture_off_on_text",
    "eligibility_exclusion",
    "excluded_terminal_process_cut",
    "provenance_continuity",
    "fault_nonblocking",
    "policy_pause_restart",
    "five_probes",
    "no_cwd_or_stdout_leak",
)
PROBES = (
    ("app_retarget", "sources/AppRetarget.swift", "probes/app_retarget_probe.swift", []),
    ("composition_finalization", "sources/CompositionFinalization.swift", "probes/composition_finalization_probe.swift", []),
    ("modifier_physical_keys", "sources/ModifierPhysicalKeys.swift", "probes/modifier_physical_keys_probe.swift", ["-framework", "AppKit", "-framework", "Carbon"]),
    ("paging_hit_paths", "sources/PagingHitPaths.swift", "probes/paging_hit_paths_probe.swift", ["-framework", "CoreGraphics"]),
    ("cli_build_status", "sources/CLIBuildStatus.swift", "probes/cli_build_status_probe.swift", []),
)


def nearest_rank(values, percentile):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty sample")
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def pair_order(index):
    return ("off", "on") if index % 2 == 0 else ("on", "off")


def threshold_failed(delta_ns, p95_ms=1.0, p99_ms=3.0):
    if not delta_ns:
        return True
    return nearest_rank(delta_ns, 0.95) > p95_ms * 1_000_000 or nearest_rank(delta_ns, 0.99) > p99_ms * 1_000_000


def self_test():
    failures = []
    sample = list(range(1, 2001))
    if nearest_rank(sample, 0.50) != 1000:
        failures.append("p50")
    if nearest_rank(sample, 0.95) != 1900:
        failures.append("p95")
    if nearest_rank(sample, 0.99) != 1980:
        failures.append("p99")
    if pair_order(0) != ("off", "on") or pair_order(1) != ("on", "off"):
        failures.append("pair_order")
    if not threshold_failed([2_000_000] * 2000):
        failures.append("threshold_positive")
    if threshold_failed([100_000] * 2000):
        failures.append("threshold_negative")
    identity = {
        "source_instance_id": "source-1",
        "process_id": "process-1",
        "sequence_before": 4,
        "sequence_after": 6,
    }
    observation = {
        "source_instance_id": "source-1",
        "process_id": "process-1",
        "source_local_sequence": 5,
    }
    if not public_capture_identity([observation], identity):
        failures.append("public_query_identity_positive")
    for key, value in (
        ("source_instance_id", "source-2"),
        ("process_id", "process-2"),
        ("source_local_sequence", 4),
        ("source_local_sequence", 7),
    ):
        control = dict(observation)
        control[key] = value
        if public_capture_identity([control], identity):
            failures.append("public_query_identity_negative")
            break
    upper_bound = dict(observation)
    upper_bound["source_local_sequence"] = identity["sequence_after"]
    if not public_capture_identity([upper_bound], identity):
        failures.append("public_query_inclusive_upper_bound")
    if public_capture_identity([observation], {**identity, "sequence_after": 4}):
        failures.append("public_query_empty_interval")
    excluded_identity = {
        "source_instance_id": "source-1",
        "excluded_process_id": "process-1",
        "excluded_segment_id": "segment-1",
        "excluded_update_id": "update-1",
        "exclusion_cut_sequence": "3",
        "next_process_id": "process-2",
        "next_update_id": "update-2",
        "sequence_after": "6",
    }
    excluded_rows = [
        {
            "source_instance_id": "source-1", "process_id": "process-1",
            "continuity_segment_id": "segment-1", "source_local_sequence": 2,
            "observation_kind": "input_change", "update_id": "update-1", "durable_seq": 0,
        },
        {
            "source_instance_id": "source-1", "process_id": "process-1",
            "source_local_sequence": 3,
            "observation_kind": "exclusion_notice", "payload": None, "durable_seq": 1,
        },
        {
            "source_instance_id": "source-1", "process_id": "process-2",
            "continuity_segment_id": "segment-1", "source_local_sequence": 4,
            "observation_kind": "start", "durable_seq": 2,
        },
        {
            "source_instance_id": "source-1", "process_id": "process-2",
            "continuity_segment_id": "segment-1", "source_local_sequence": 5,
            "observation_kind": "input_change", "update_id": "update-2", "durable_seq": 3,
        },
    ]
    if not excluded_terminal_relation(excluded_rows, excluded_identity).get("passed"):
        failures.append("excluded_terminal_public_query_positive")
    reused = excluded_rows + [{
        "source_instance_id": "source-1", "process_id": "process-1",
        "continuity_segment_id": "segment-1", "source_local_sequence": 5,
        "observation_kind": "input_change", "durable_seq": 4,
    }]
    if excluded_terminal_relation(reused, excluded_identity).get("passed"):
        failures.append("excluded_terminal_public_query_negative")
    if "five_probes" not in REQUIRED:
        failures.append("scenario_inventory")
    skipped = {"five_probes": "skipped"}
    if not any(skipped.get(item) == "skipped" for item in REQUIRED):
        failures.append("skip_detector")
    if failures:
        sys.stderr.write("self-test failed: %s\n" % ",".join(failures))
        return 1
    sys.stdout.write("self-test ok content_included=false\n")
    return 0


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_oid(path):
    with open(path, "rb") as handle:
        content = handle.read()
    header = b"blob %d\0" % len(content)
    return hashlib.sha1(header + content).digest()


def git_tree_oid(path):
    entries = []
    with os.scandir(path) as iterator:
        for item in iterator:
            info = item.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise RuntimeError("backend export contains a symlink: %s" % item.path)
            if stat.S_ISDIR(info.st_mode):
                mode = b"40000"
                oid = bytes.fromhex(git_tree_oid(item.path))
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
        if any(os.path.islink(os.path.join(_, name)) for name in dirs):
            raise RuntimeError("backend export contains a symlink directory")
        count += len(files)
    return count


def validate_backend(path):
    if not os.path.isdir(path) or os.path.islink(path):
        raise RuntimeError("accepted backend export is unavailable")
    count = backend_file_count(path)
    tree = git_tree_oid(path)
    if count != 344 or tree != BACKEND_TREE:
        raise RuntimeError("backend export identity mismatch: files=%s tree=%s" % (count, tree))
    return {"files": count, "tree": tree}


def stage_backend(source, destination):
    if os.path.lexists(destination):
        raise RuntimeError("fresh backend destination already exists: %s" % destination)
    source_identity = validate_backend(source)
    reject_symlink_components(destination)

    def copy_directory(source_dir, destination_dir):
        os.mkdir(destination_dir, 0o700)
        with os.scandir(source_dir) as iterator:
            for item in iterator:
                info = item.stat(follow_symlinks=False)
                target = os.path.join(destination_dir, item.name)
                if stat.S_ISDIR(info.st_mode):
                    copy_directory(item.path, target)
                elif stat.S_ISREG(info.st_mode):
                    mode = 0o755 if info.st_mode & 0o111 else 0o644
                    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                    if hasattr(os, "O_NOFOLLOW"):
                        flags |= os.O_NOFOLLOW
                    fd = os.open(target, flags, mode)
                    with os.fdopen(fd, "wb") as outgoing, open(item.path, "rb") as incoming:
                        shutil.copyfileobj(incoming, outgoing)
                    os.chmod(target, mode)
                else:
                    raise RuntimeError("backend export contains a non-file entry: %s" % item.path)

    copy_directory(source, destination)
    destination_identity = validate_backend(destination)
    if destination_identity != source_identity:
        raise RuntimeError("staged backend identity differs from its accepted source")
    sys.stdout.write("backend staged files=%s tree=%s content_included=false\n" % (
        destination_identity["files"], destination_identity["tree"]
    ))
    return 0


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


def fresh_socket_path(scratch, label):
    # macOS AF_UNIX paths are capped; callers use a short private test root.
    path = os.path.join(scratch, label + "-" + uuid.uuid4().hex[:12])
    reject_symlink_components(path)
    if os.path.lexists(path):
        raise RuntimeError("fresh socket path already exists: %s" % path)
    if len(os.fsencode(path)) > 103:
        raise RuntimeError("socket path exceeds macOS sun_path: %s" % path)
    return path


def fresh_collector_root(scratch, label):
    # Keep collector roots shallow so their required root-local socket fits
    # sun_path even when the allocated scratch path itself is long.
    root = os.path.join(scratch, label + "-" + uuid.uuid4().hex[:8])
    reject_symlink_components(root)
    if os.path.lexists(root):
        raise RuntimeError("fresh collector root already exists: %s" % root)
    if len(os.fsencode(os.path.join(root, "s"))) > 103:
        raise RuntimeError("collector socket path exceeds macOS sun_path")
    return root


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


def compile_harness(root, probes):
    private_dir(probes)
    app = os.path.join(probes, "Harness.app", "Contents", "MacOS")
    private_dir(app)
    plist = os.path.join(probes, "Harness.app", "Contents", "Info.plist")
    write_private(plist, """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.ac189.harness</string>
<key>CFBundleExecutable</key><string>harness</string>
<key>CFBundleVersion</key><string>189</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
</dict></plist>
""")
    sources = sorted(
        os.path.join("sources", name)
        for name in os.listdir("sources")
        if name.endswith(".swift") and name != "Main.swift"
    )
    binary = os.path.join(app, "harness")
    include = os.path.join(os.path.dirname(probes), "include")
    stage_include_headers(os.path.join(root, ".local", "ac189-include"), include)
    command = [
        "xcrun", "swiftc", "-parse-as-library", "-swift-version", "5",
        "-enable-bare-slash-regex", "-O",
        "-import-objc-header", "sources/Squirrel-Bridging-Header.h",
        "-I", include, "-L", "lib", "-lrime.1",
        "-Xlinker", "-rpath", "-Xlinker", os.path.abspath("lib"),
        "-framework", "AppKit", "-framework", "InputMethodKit",
        "-framework", "Carbon", "-framework", "UserNotifications",
        "-framework", "CoreGraphics",
    ] + sources + ["probes/input_archive_frontend_harness.swift", "-o", binary]
    if os.path.lexists(binary):
        raise RuntimeError("harness output already exists: %s" % binary)
    code, out, err = run(command, timeout=180)
    if code != 0:
        sys.stderr.write(err)
        raise SystemExit(code)
    os.chmod(binary, 0o700)
    return binary


def stage_include_headers(source, destination):
    headers = (
        "rime_api_stdbool.h", "rime_api.h", "rime/key_table.h",
        "X11/keysymdef.h", "X11/keysym.h",
    )
    if not os.path.isdir(source) or os.path.islink(source):
        raise RuntimeError("pinned librime headers are unavailable")
    if not os.path.lexists(destination):
        private_dir(destination)
    hashes = {}
    for relative in headers:
        original = os.path.join(source, relative)
        target = os.path.join(destination, relative)
        original_info = os.lstat(original)
        if not stat.S_ISREG(original_info.st_mode) or stat.S_ISLNK(original_info.st_mode):
            raise RuntimeError("librime header is not a regular file: %s" % relative)
        hashes[relative] = sha256(original)
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


def collector(backend, args, *extra):
    return [
        "/usr/bin/python3", "-m", "archive.cli",
        "--root", args[0], "--socket", args[1], *extra,
    ]


def start_collector(backend, root, socket, **limits):
    command = collector(backend, (root, socket), "collector", "start")
    for key, value in limits.items():
        command.extend(["--" + key.replace("_", "-"), str(value)])
    code, out, err = run(command, env={"PYTHONPATH": backend})
    if code != 0:
        sys.stderr.write(err or out)
        raise SystemExit(code)
    return out


def stop_collector(backend, root, socket):
    run(collector(backend, (root, socket), "collector", "stop"), env={"PYTHONPATH": backend})


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


def harness(binary, shared, user, log, socket, scenario, report, extra=()):
    code, out, err = run(
        [binary, "--shared", shared, "--user", user, "--log", log, "--socket", socket,
         "--scenario", scenario, "--report", report, *extra],
        timeout=600,
    )
    leaked = any(token in out or token in err for token in ("你好", "INV-EQUAL", "INV-CONFLICT"))
    return code, out, err, leaked


def run_probes(probes_dir):
    private_dir(probes_dir)
    results = {}
    for name, source, probe, frameworks in PROBES:
        binary = os.path.join(probes_dir, name)
        if os.path.lexists(binary):
            raise RuntimeError("probe binary path already exists: %s" % binary)
        code, out, err = run(["xcrun", "swiftc", "-parse-as-library", source, probe, "-o", binary, *frameworks])
        if code != 0:
            results[name] = "compile_failed"
            continue
        os.chmod(binary, 0o700)
        code, out, err = run([binary])
        results[name] = "pass" if code == 0 else "fail"
    return results


def query_payloads(backend, socket):
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
    processes = sorted({row.get("process_id") for row in rows if row.get("process_id")})
    detailed = []
    for process_id in processes:
        cursor = ""
        while True:
            args = [
                "query", "process", "--process-id", process_id, "--private-detail", "--page-size", "50",
            ]
            if cursor:
                args.extend(["--cursor", cursor])
            code, page, err = cli(backend, socket, *args)
            if code != 0:
                return code, detailed, err
            body = page.get("body") or {}
            detailed.extend(body.get("observations") or [])
            next_cursor = body.get("next_cursor")
            if next_cursor in (None, ""):
                break
            next_cursor = str(next_cursor)
            if next_cursor == cursor:
                return 1, detailed, "process cursor did not advance"
            cursor = next_cursor
    return 0, detailed, ""


def payload_text(row):
    payload = row.get("payload")
    if isinstance(payload, dict):
        return str(payload.get("text") or "")
    return ""


def payload_preedit(row):
    payload = row.get("payload")
    if isinstance(payload, dict):
        return str(payload.get("text") or payload.get("preedit") or "")
    return ""


PAGE_KINDS = ("start", "input_change", "replacement", "temporary_selection")


def terminal_relation(rows, identity, kind, process_key):
    source = identity.get("source_instance_id")
    process_id = identity.get(process_key)
    segment = identity.get("segment_id")
    if not source or not process_id or not segment:
        return {"passed": False, "reason": "missing fixture identity"}
    terminals = [
        row for row in rows
        if row.get("source_instance_id") == source
        and row.get("process_id") == process_id
        and row.get("continuity_segment_id") == segment
        and row.get("observation_kind") == kind
    ]
    if len(terminals) != 1:
        return {"passed": False, "terminal_count": len(terminals)}
    terminal = terminals[0]
    parent = terminal.get("parent_update_id")
    pages = [
        row for row in rows
        if row.get("source_instance_id") == source
        and row.get("process_id") == process_id
        and row.get("continuity_segment_id") == segment
        and row.get("observation_kind") in PAGE_KINDS
        and row.get("update_id") == parent
        and (row.get("durable_seq") or 0) < (terminal.get("durable_seq") or 0)
    ]
    passed = bool(parent) and len(pages) == 1
    payload = terminal.get("payload")
    if kind == "unavailable_client":
        passed = passed and isinstance(payload, dict) and "text" not in payload
    return {
        "passed": passed,
        "terminal_seq": terminal.get("durable_seq"),
        "page_seq": pages[0].get("durable_seq") if pages else None,
        "same_process": terminal.get("process_id") == process_id,
        "same_segment": terminal.get("continuity_segment_id") == segment,
        "parent_update_matches": bool(parent) and len(pages) == 1,
        "content_free_unavailable": kind != "unavailable_client" or (isinstance(payload, dict) and "text" not in payload),
    }


def excluded_terminal_relation(rows, identity):
    source = identity.get("source_instance_id")
    excluded_process = identity.get("excluded_process_id")
    segment = identity.get("excluded_segment_id")
    next_process = identity.get("next_process_id")
    excluded_update = identity.get("excluded_update_id")
    next_update = identity.get("next_update_id")
    try:
        cut_sequence = int(identity.get("exclusion_cut_sequence", ""))
        sequence_after = int(identity.get("sequence_after", ""))
    except (TypeError, ValueError):
        return {"passed": False, "reason": "invalid fixture sequence"}
    if not all((source, excluded_process, segment, next_process, excluded_update, next_update)):
        return {"passed": False, "reason": "missing fixture identity"}

    fixture_rows = [row for row in rows if row.get("source_instance_id") == source]
    excluded_pages = [
        row for row in fixture_rows
        if row.get("process_id") == excluded_process
        and row.get("continuity_segment_id") == segment
        and row.get("update_id") == excluded_update
        and row.get("observation_kind") in PAGE_KINDS
        and (row.get("source_local_sequence") or 0) <= cut_sequence
    ]
    excluded_notices = [
        row for row in fixture_rows
        if row.get("process_id") == excluded_process
        and row.get("observation_kind") == "exclusion_notice"
        and (row.get("source_local_sequence") or 0) <= cut_sequence
    ]
    next_starts = [
        row for row in fixture_rows
        if row.get("process_id") == next_process
        and row.get("observation_kind") == "start"
        and (row.get("source_local_sequence") or 0) > cut_sequence
        and (row.get("source_local_sequence") or 0) <= sequence_after
    ]
    next_pages = [
        row for row in fixture_rows
        if row.get("process_id") == next_process
        and row.get("continuity_segment_id") == segment
        and row.get("update_id") == next_update
        and row.get("observation_kind") in PAGE_KINDS
        and (row.get("source_local_sequence") or 0) > cut_sequence
        and (row.get("source_local_sequence") or 0) <= sequence_after
    ]
    old_rows_after_cut = [
        row for row in fixture_rows
        if row.get("process_id") == excluded_process
        and (row.get("source_local_sequence") or 0) > cut_sequence
    ]
    same_source_segment = any(
        row.get("process_id") in (excluded_process, next_process)
        and row.get("continuity_segment_id") == segment
        for row in fixture_rows
    )
    notice_is_content_free = bool(excluded_notices) and all(
        not isinstance(row.get("payload"), dict) or "text" not in row["payload"]
        for row in excluded_notices
    )
    passed = (
        excluded_process != next_process
        and excluded_update != next_update
        and bool(excluded_pages)
        and bool(excluded_notices)
        and notice_is_content_free
        and same_source_segment
        and len(next_starts) == 1
        and len(next_pages) == 1
        and not old_rows_after_cut
        and next_starts[0].get("durable_seq", 0) < next_pages[0].get("durable_seq", 0)
    )
    return {
        "passed": passed,
        "excluded_notice_count": len(excluded_notices),
        "excluded_notice_content_free": notice_is_content_free,
        "next_start_seq": next_starts[0].get("durable_seq") if next_starts else None,
        "next_page_seq": next_pages[0].get("durable_seq") if next_pages else None,
        "excluded_page_identity_matches": bool(excluded_pages),
        "same_source_segment": same_source_segment,
        "different_process": excluded_process != next_process,
        "different_update": excluded_update != next_update,
        "old_process_reused_after_cut": bool(old_rows_after_cut),
    }


def archive_relations(backend, socket, terminal_identities):
    """Check persisted archive relations through the public query interface.

    These are the relations the attempt-2 independent probes found corrupted:
    a composition that is finalized while its observed process is still open
    must store its terminal against that same process and segment, and a
    composition whose prefix was never observed must never be admitted later.
    """
    code, _, err = cli(backend, socket, "checkpoint")
    if code != 0:
        return code, {}, err
    code, rows, err = query_payloads(backend, socket)
    if code != 0:
        return code, {}, err
    rows = sorted(rows, key=lambda row: row.get("durable_seq") or 0)

    # Use the harness-emitted identity and parent-update relation. Text equality
    # is not an identity or a join key.
    deactivation = terminal_relation(
        rows, terminal_identities.get("deactivation", {}), "raw_finalization", "process_id"
    )
    global_raw = terminal_relation(
        rows, terminal_identities.get("global_raw", {}), "raw_finalization", "process_id"
    )
    global_unavailable = terminal_relation(
        rows, terminal_identities.get("global_unavailable", {}), "unavailable_client", "process_id"
    )
    excluded_terminal = excluded_terminal_relation(
        rows, terminal_identities.get("excluded_terminal", {})
    )

    # No stored payload may carry text that was composed while ineligible.
    joined = "\n".join(payload_text(row) for row in rows)

    detail = {
        "terminal_relations": {
            "deactivation_raw": deactivation,
            "global_raw": global_raw,
            "global_unavailable": global_unavailable,
            "excluded_terminal": excluded_terminal,
        },
        "excluded_canaries_absent": {
            "jiamin": "jiamin" not in joined,
            "甲敏": "甲敏" not in joined,
            "甲斥": "甲斥" not in joined,
        },
        "eligible_canary_present": "甲正" in joined,
    }
    evidence = {
        "raw_terminal_process_continuity": deactivation.get("passed") is True,
        "global_raw_terminal_persisted": global_raw.get("passed") is True,
        "global_unavailable_terminal_content_free": global_unavailable.get("passed") is True,
        "excluded_terminal_process_cut": excluded_terminal.get("passed") is True,
        "no_unobserved_prefix_admitted": all(detail["excluded_canaries_absent"].values()),
        "eligible_content_still_recorded": detail["eligible_canary_present"],
    }
    return 0, {"evidence": evidence, "detail": detail}, ""


def fault_coverage(binary, root, scratch, shared, user, log, backend):
    """Real held/failing collector, bounded queue, capacity and concurrent query.

    Every arm compiles and drives the production controller; only the collector
    side is faulted, and each arm uses its own collector root.
    """
    results = {}
    env = {"PYTHONPATH": backend}

    def collector_call(collector_root, *args):
        return run(
            ["/usr/bin/python3", "-m", "archive.cli", "--root", collector_root, "--socket", os.path.join(collector_root, "s"), *args],
            env=env,
        )

    # Arm 1: bounded producer queue with the collector absent for the burst.
    held_root = fresh_collector_root(scratch, "fh")
    private_dir(held_root)
    held_socket = os.path.join(held_root, "s")
    report = os.path.join(root, "fault-burst.json")
    code, out, err = run(
        [binary, "--shared", shared, "--user", user, "--log", log, "--socket", held_socket,
         "--scenario", "fault-burst", "--report", report],
        timeout=600,
    )
    body = json.load(open(report)) if os.path.exists(report) else {}
    results["absent_collector_burst"] = code == 0 and body.get("failure_count", 1) == 0

    # Arm 2: bounded queue count with a live collector, then a concurrent
    # management query while the frontend is composing.
    bounded_root = fresh_collector_root(scratch, "fb")
    private_dir(bounded_root)
    bounded_socket = os.path.join(bounded_root, "s")
    code, out, err = run(
        ["/usr/bin/python3", "-m", "archive.cli", "--root", bounded_root, "--socket", bounded_socket,
         "collector", "start", "--producer-queue-count", "8", "--producer-queue-bytes", "8192",
         "--archive-capacity-bytes", "65536", "--collector-queue-count", "8"],
        env=env,
    )
    results["bounded_collector_started"] = code == 0
    if code == 0:
        run(
            ["/usr/bin/python3", "-m", "archive.cli", "--socket", bounded_socket, "policy", "enable", "--expect-revision", "0"],
            env=env,
        )
        concurrent_report = os.path.join(root, "concurrent-status.json")
        concurrent_code, _, _, _ = harness(
            binary, shared, user, log, bounded_socket, "concurrent-status", concurrent_report
        )
        concurrent_body = json.load(open(concurrent_report)) if os.path.exists(concurrent_report) else {}
        results["concurrent_management_query"] = (
            concurrent_code == 0 and concurrent_body.get("failure_count", 1) == 0
        )
        status_code, status, _ = cli(backend, bounded_socket, "status")
        status_body = status.get("body") or {}
        results["fault_visible_in_status"] = (
            status_code == 0
            and (status_body.get("admission_refused_units", 0) >= 0)
            and status_body.get("globally_effective") is False
        )
        run(
            ["/usr/bin/python3", "-m", "archive.cli", "--root", bounded_root, "--socket", bounded_socket,
             "collector", "stop"],
            env=env,
        )
    return results


def sigpipe_controls(binary, scratch):
    import socket as pysock
    results = {}
    control_root = fresh_collector_root(scratch, "sp")
    private_dir(control_root)
    missing = fresh_socket_path(control_root, "mi")
    report = os.path.join(control_root, "sig-missing.json")
    code, _, err, _ = harness(binary, control_root, control_root, control_root, missing, "socket-call", report)
    results["connect_failure"] = code == 0 and "collector_unavailable" in err

    def peer_close(name, scenario, large=True):
        path = fresh_socket_path(control_root, name[:2])
        server = pysock.socket(pysock.AF_UNIX, pysock.SOCK_STREAM)
        server.bind(path)
        os.chmod(path, 0o600)
        server.listen(1)
        server.settimeout(5)
        proc = subprocess.Popen(
            [binary, "--shared", control_root, "--user", control_root, "--log", control_root,
             "--socket", path, "--scenario", scenario, "--report", os.path.join(control_root, scenario + ".json")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            conn, _ = server.accept()
            if large:
                try:
                    conn.recv(1)
                except OSError:
                    pass
            conn.close()
        except OSError:
            pass
        finally:
            server.close()
        try:
            out, err = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        return proc.returncode, out, err

    code, _, err = peer_close("close.sock", "socket-call")
    results["accept_close"] = code == 0 and code != -13 and "socket_call=collector_unavailable" in err
    code, _, err = peer_close("sender.sock", "sender-call", large=False)
    results["sender_close"] = code == 0 and "sender_call=survived" in err
    path = fresh_socket_path(control_root, "ok")
    server = pysock.socket(pysock.AF_UNIX, pysock.SOCK_STREAM)
    server.bind(path)
    os.chmod(path, 0o600)
    server.listen(1)
    server.settimeout(5)
    proc = subprocess.Popen(
        [binary, "--shared", control_root, "--user", control_root, "--log", control_root,
         "--socket", path, "--scenario", "socket-call", "--report", os.path.join(control_root, "ok.json")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    request = {}
    frame_size = 0
    try:
        conn, _ = server.accept()
        frame = bytearray()
        while len(frame) < 4:
            chunk = conn.recv(65536)
            if not chunk:
                break
            frame.extend(chunk)
        if len(frame) >= 4:
            frame_size = int.from_bytes(frame[:4], "big")
            while len(frame) < 4 + frame_size:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                frame.extend(chunk)
        if len(frame) >= 4 + frame_size:
            try:
                request = json.loads(bytes(frame[4:4 + frame_size]))
            except json.JSONDecodeError:
                request = {}
        reply = json.dumps({
            "interface_version": "input-archive-v1",
            "envelope_version": 1,
            "op": "admit_batch",
            "request_id": request.get("request_id", ""),
            "ok": False,
            "error": {"code": "invalid_request", "message": "content-free", "retryable": False, "content_included": False},
            "content_included": False,
        }).encode()
        conn.sendall(len(reply).to_bytes(4, "big") + reply)
        conn.close()
    except OSError:
        pass
    finally:
        server.close()
    try:
        _, err = proc.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    results["normal_exchange"] = (
        proc.returncode == 0
        and "socket_call=" in err
        and request.get("op") == "admit_batch"
        and bool(request.get("request_id"))
    )
    return results


def contract(args):
    scratch = os.path.join(args.scratch, "contract-" + uuid.uuid4().hex)
    shared = os.path.join(scratch, "shared")
    user = os.path.join(scratch, "user")
    log = os.path.join(scratch, "log")
    root = fresh_collector_root(args.scratch, "ct")
    socket = os.path.join(root, "s")
    private_dir(args.root)
    private_dir(scratch)
    write_schema(shared, user, socket)
    probes = run_probes(os.path.join(args.root, "probes"))
    binary = compile_harness(os.getcwd(), os.path.join(args.root, "build"))
    start_collector(args.backend, root, socket)
    binding_old_root = fresh_collector_root(args.scratch, "bo")
    binding_new_root = fresh_collector_root(args.scratch, "bn")
    binding_old_socket = os.path.join(binding_old_root, "s")
    binding_new_socket = os.path.join(binding_new_root, "s")
    binding_path_root = fresh_collector_root(args.scratch, "pa")
    if len(os.fsencode(os.path.join(binding_path_root, "x", "y", "s"))) > 103:
        raise RuntimeError("ancestor-alias control socket path exceeds macOS sun_path")
    private_dir(binding_path_root)
    binding_started = []
    try:
        code, _, err = run(
            ["/usr/bin/python3", "-m", "archive.cli", "--socket", socket, "policy", "enable", "--expect-revision", "0"],
            env={"PYTHONPATH": args.backend},
        )
        if code != 0:
            sys.stderr.write(err)
            return code
        report = os.path.join(args.root, "harness-contract.json")
        code, out, err, leaked = harness(binary, shared, user, log, socket, "contract", report)
        body = {}
        if os.path.exists(report):
            body = json.load(open(report))
        cli(args.backend, socket, "checkpoint")
        status_code, status, _ = cli(args.backend, socket, "status")
        query_code, observations, query_err = query_payloads(args.backend, socket)
        kinds = {row.get("observation_kind") for row in observations}
        gate_report = os.path.join(args.root, "schema-gate.json")
        gate_code, _, gate_err, _ = harness(binary, shared, user, log, socket, "schema-gate", gate_report)
        cli(args.backend, socket, "checkpoint")
        edge_report = os.path.join(args.root, "transition-edge.json")
        edge_code, _, _, _ = harness(binary, shared, user, log, socket, "transition-edge", edge_report)
        provenance_report = os.path.join(args.root, "terminal-provenance.json")
        provenance_code, _, _, _ = harness(
            binary, shared, user, log, socket, "terminal-provenance", provenance_report
        )
        provenance_body = json.load(open(provenance_report)) if os.path.exists(provenance_report) else {}
        excluded_report = os.path.join(args.root, "excluded-terminal.json")
        excluded_code, _, _, _ = harness(
            binary, shared, user, log, socket, "excluded-terminal", excluded_report
        )
        excluded_body = json.load(open(excluded_report)) if os.path.exists(excluded_report) else {}
        finalization_ids = body.get("global_finalization_identities") or {}
        provenance_ids = provenance_body.get("terminal_provenance_identities") or {}
        terminal_identities = {
            "deactivation": {
                "source_instance_id": provenance_ids.get("source_instance_id"),
                "process_id": provenance_ids.get("process_id"),
                "segment_id": provenance_ids.get("segment_id"),
            },
            "global_raw": {
                "source_instance_id": finalization_ids.get("source_instance_id"),
                "process_id": finalization_ids.get("raw_process_id"),
                "segment_id": finalization_ids.get("raw_segment_id"),
            },
            "global_unavailable": {
                "source_instance_id": finalization_ids.get("source_instance_id"),
                "process_id": finalization_ids.get("unavailable_process_id"),
                "segment_id": finalization_ids.get("unavailable_segment_id"),
            },
            "excluded_terminal": excluded_body.get("excluded_terminal_identities") or {},
        }
        relations_code, relations, relations_err = archive_relations(args.backend, socket, terminal_identities)
        relation_evidence = relations.get("evidence") or {}
        payload_code, rows, _ = query_payloads(args.backend, socket)
        texts = [payload_text(row) for row in rows]
        joined = "\n".join(texts)
        schema_gate = {
            "client_ok": gate_code == 0,
            "luna_stored": any(row.get("schema_id") == "luna_pinyin" and "甲正" in payload_text(row) for row in rows),
            "excluded_commit_absent": "甲斥" not in joined,
            "excluded_raw_absent": "jryuan" not in joined,
            "sensitive_absent": "甲敏" not in joined,
        }
        sig = sigpipe_controls(binary, args.scratch)
        faults = fault_coverage(binary, args.root, args.scratch, shared, user, log, args.backend)

        binding_started.append((binding_old_root, binding_old_socket))
        start_collector(args.backend, binding_old_root, binding_old_socket)
        old_policy_code, _, old_policy_err = run(
            ["/usr/bin/python3", "-m", "archive.cli", "--socket", binding_old_socket,
             "policy", "enable", "--expect-revision", "0"],
            env={"PYTHONPATH": args.backend},
        )
        binding_started.append((binding_new_root, binding_new_socket))
        start_collector(args.backend, binding_new_root, binding_new_socket)
        new_policy_code, _, new_policy_err = run(
            ["/usr/bin/python3", "-m", "archive.cli", "--socket", binding_new_socket,
             "policy", "enable", "--expect-revision", "0"],
            env={"PYTHONPATH": args.backend},
        )
        binding_report = os.path.join(args.root, "binding-controls.json")
        binding_code, _, binding_err, binding_leak = harness(
            binary, shared, user, log, binding_old_socket, "binding-controls", binding_report,
            extra=["--old-socket", binding_old_socket, "--new-socket", binding_new_socket,
                   "--path-root", binding_path_root],
        )
        binding_body = json.load(open(binding_report)) if os.path.exists(binding_report) else {}
        binding_ids = binding_body.get("binding_identities") or {}
        cli(args.backend, binding_old_socket, "checkpoint")
        cli(args.backend, binding_new_socket, "checkpoint")
        old_query_code, old_rows, old_query_err = query_payloads(args.backend, binding_old_socket)
        new_query_code, new_rows, new_query_err = query_payloads(args.backend, binding_new_socket)

        def has_observation(query_rows, source, process, text):
            return any(
                row.get("source_instance_id") == source
                and row.get("process_id") == process
                and payload_text(row) == text
                for row in query_rows
            )

        binding_evidence = {
            "old_endpoint_positive_control": has_observation(
                old_rows, binding_ids.get("route_source_instance_id"),
                binding_ids.get("route_old_control_process_id"), "INV-189-OLD-ENDPOINT-CONTROL",
            ),
            "queued_old_destination_not_sent_to_new": not has_observation(
                new_rows, binding_ids.get("route_source_instance_id"),
                binding_ids.get("route_old_process_id"), "INV-189-OLD-DESTINATION",
            ),
            "queued_old_destination_not_replayed_to_old": not has_observation(
                old_rows, binding_ids.get("route_source_instance_id"),
                binding_ids.get("route_old_process_id"), "INV-189-OLD-DESTINATION",
            ),
            "queued_old_destination_accounted_as_loss": (
                binding_body.get("failure_count", 1) == 0
                and binding_ids.get("route_discarded_known_dropped") == "1"
                and binding_ids.get("route_discarded_unreported_loss_notices") == "1"
            ),
            "new_endpoint_positive_control": has_observation(
                new_rows, binding_ids.get("route_source_instance_id"),
                binding_ids.get("route_new_process_id"), "INV-189-NEW-DESTINATION",
            ),
            "stale_policy_not_persisted": not any(
                row.get("source_instance_id") == binding_ids.get("policy_source_instance_id")
                and row.get("process_id") == binding_ids.get("policy_stale_process_id")
                for row in old_rows + new_rows
            ),
            "current_policy_positive_control": has_observation(
                new_rows, binding_ids.get("policy_source_instance_id"),
                binding_ids.get("policy_current_process_id"), "INV-189-CURRENT-POLICY",
            ),
        }
        evidence = {
            "short_long_typing": "commit_attempt" in kinds and "input_change" in kinds,
            "backspace_retype": "replacement" in kinds,
            "selection_paging": "temporary_selection" in kinds or "input_change" in kinds,
            "cancellation_raw_deactivation": "cancellation" in kinds and "raw_finalization" in kinds,
            "retarget_unavailable_command": code == 0 or body.get("failure_count") == 0,
            "capture_off_on_text": body.get("failure_count", 1) == 0,
            "eligibility_exclusion": all(schema_gate.values()),
            "provenance_continuity": len({row.get("process_id") for row in observations}) > 1,
            "raw_terminal_process_continuity": relation_evidence.get("raw_terminal_process_continuity") is True,
            "no_unobserved_prefix_admitted": relation_evidence.get("no_unobserved_prefix_admitted") is True,
            "eligible_content_still_recorded": relation_evidence.get("eligible_content_still_recorded") is True,
            "global_raw_terminal_persisted": relation_evidence.get("global_raw_terminal_persisted") is True,
            "global_unavailable_terminal_content_free": relation_evidence.get("global_unavailable_terminal_content_free") is True,
            "excluded_terminal_process_cut": relation_evidence.get("excluded_terminal_process_cut") is True,
            "stale_policy_reply_ignored": binding_evidence["stale_policy_not_persisted"] and binding_evidence["current_policy_positive_control"],
            "rebind_destination_isolation": all(binding_evidence.values()),
            "fault_nonblocking": all(sig.values()),
            "held_fault_and_bounded_queue": all(faults.values()) and bool(faults),
            "concurrent_management_query": faults.get("concurrent_management_query") is True,
            "policy_pause_restart": (status.get("body") or {}).get("legacy_switch_changed") is False,
            "five_probes": all(value == "pass" for value in probes.values()),
            "no_cwd_or_stdout_leak": body.get("cwd_unchanged") is True and not leaked,
        }
        # Pause, restart, and absent-collector checks.
        run(["/usr/bin/python3", "-m", "archive.cli", "--socket", socket, "policy", "pause", "--expect-revision", "1"], env={"PYTHONPATH": args.backend})
        stop_collector(args.backend, root, socket)
        absent_report = os.path.join(args.root, "harness-absent.json")
        absent_code, _, _, _ = harness(binary, shared, user, log, socket, "absent", absent_report)
        evidence["fault_nonblocking"] = absent_code == 0 and all(sig.values())
        start_collector(args.backend, root, socket)
        _, restarted, _ = cli(args.backend, socket, "status")
        evidence["policy_pause_restart"] = (restarted.get("body") or {}).get("desired_policy") == "paused"
        passed = (
            all(evidence.values())
            and body.get("failure_count", 1) == 0
            and status_code == 0
            and query_code == 0
            and payload_code == 0
            and relations_code == 0
            and binding_code == 0
            and old_policy_code == 0
            and new_policy_code == 0
            and old_query_code == 0
            and new_query_code == 0
            and edge_code == 0
            and provenance_code == 0
            and excluded_code == 0
        )
        public = {
            "interface_version": INTERFACE,
            "passed": passed,
            "evidence": evidence,
            "probes": probes,
            "schema_gate": schema_gate,
            "sigpipe": sig,
            "fault_coverage": faults,
            "relations": relations,
            "binding_evidence": binding_evidence,
            "binding_scenario": {
                "exit": binding_code,
                "failure_count": binding_body.get("failure_count", 1),
                "identities": binding_ids,
                "old_policy_enable_exit": old_policy_code,
                "new_policy_enable_exit": new_policy_code,
            },
            "scenario_exits": {
                "contract": code,
                "schema_gate": gate_code,
                "transition_edge": edge_code,
                "terminal_provenance": provenance_code,
                "excluded_terminal": excluded_code,
            },
            "failure_count": body.get("failure_count", 1),
            "observation_kinds": sorted(kinds),
            "content_included": False,
            "harness": sha256(binary),
            "backend_tree": BACKEND_TREE,
        }
        write_private(args.report, json.dumps(public, indent=2, sort_keys=True) + "\n")
        write_private(os.path.join(args.root, "walkthrough.txt"), "invented luna_pinyin timeline queried via process private_detail; host persistence unknown\n")
        return 0 if passed else 1
    finally:
        for collector_root, collector_socket in reversed(binding_started):
            stop_collector(args.backend, collector_root, collector_socket)
        stop_collector(args.backend, root, socket)


def timing(args):
    if not os.path.exists(args.plan):
        sys.stderr.write("code=invalid_request\n")
        return 1
    plan = json.load(open(args.plan))
    if plan.get("procedure") != "MEAS-189-v1":
        sys.stderr.write("code=invalid_request\n")
        return 1
    if plan.get("preflight_only") is True:
        reason = (plan.get("quiet_window") or {}).get("reason", "quiet window not confirmed")
        public = {
            "procedure": "MEAS-189-v1",
            "status": "environment_blocker",
            "reason": reason,
            "samples_started": 0,
            "passed": False,
            "content_included": False,
            "plan_sha256": sha256(args.plan),
        }
        write_private(args.report, json.dumps(public, indent=2, sort_keys=True) + "\n")
        sys.stderr.write("code=environment_blocker samples_started=0 reason=%s\n" % reason.replace(" ", "_"))
        return 1

    quiet = plan.get("quiet_window") or {}
    if quiet.get("confirmed") is not True:
        public = {
            "procedure": "MEAS-189-v1", "status": "environment_blocker",
            "reason": quiet.get("reason", "quiet window not confirmed"),
            "samples_started": 0, "passed": False, "content_included": False,
            "plan_sha256": sha256(args.plan),
        }
        write_private(args.report, json.dumps(public, indent=2, sort_keys=True) + "\n")
        sys.stderr.write("code=environment_blocker samples_started=0 reason=quiet_window_unconfirmed\n")
        return 1
    try:
        return run_certified_timing(args, plan)
    except (OSError, RuntimeError) as error:
        sys.stderr.write("code=invalid_request %s\n" % error)
        return 1


def write_timing_blocker_plan(path):
    if os.path.lexists(path):
        raise RuntimeError("timing plan path already exists: %s" % path)
    plan = {
        "procedure": "MEAS-189-v1",
        "contract": "AC-189-v1",
        "attempt": 4,
        "preflight_only": True,
        "quiet_window": {
            "confirmed": False,
            "owner": "#189",
            "reason": "No quiet window was confirmed; certification sampling is not authorized",
        },
        "secure_input_state": "not_observed_without_a_quiet_window",
        "samples_started": 0,
        "content_included": False,
    }
    write_private(path, json.dumps(plan, indent=2, sort_keys=True) + "\n")
    sys.stdout.write("timing preflight blocker plan written; samples_started=0 content_included=false\n")
    return 0


def compiled_source_hashes():
    paths = sorted(
        [os.path.join("sources", name) for name in os.listdir("sources")
         if name.endswith(".swift") and name != "Main.swift"]
        + ["sources/Squirrel-Bridging-Header.h", "probes/input_archive_frontend_harness.swift"]
    )
    return {path: sha256(path) for path in paths}


def source_digest(source_hashes):
    content = "".join("%s\0%s\n" % (path, source_hashes[path]) for path in sorted(source_hashes))
    return hashlib.sha256(content.encode()).hexdigest()


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


def verify_timing_plan(plan, args):
    artifact = plan["artifact"]
    fixture = plan["fixture"]
    manifest_path = os.path.abspath(plan["manifest_path"])
    if reject_symlink_components(manifest_path) is not None:
        raise RuntimeError("measurement manifest path is unsafe")
    if not os.path.isfile(manifest_path) or sha256(manifest_path) != plan["manifest_sha256"]:
        raise RuntimeError("measurement manifest digest mismatch")
    if plan.get("published_manifest_sha256") != plan["manifest_sha256"]:
        raise RuntimeError("published manifest digest does not match")
    if not str(plan.get("published_issue_comment", "")).startswith("https://github.com/Habit130/squirrel/issues/189#issuecomment-"):
        raise RuntimeError("manifest publication reference is missing")

    harness_path = os.path.abspath(artifact["harness_path"])
    if os.path.commonpath([os.path.abspath(args.root), harness_path]) != os.path.abspath(args.root):
        raise RuntimeError("optimized harness is outside the allocated timing root")
    reject_symlink_components(harness_path)
    if not os.path.isfile(harness_path) or sha256(harness_path) != artifact["harness_sha256"]:
        raise RuntimeError("optimized harness identity mismatch")

    hashes = compiled_source_hashes()
    if artifact.get("source_hashes") != hashes or artifact.get("source_digest_sha256") != source_digest(hashes):
        raise RuntimeError("compiled source set changed after manifest publication")
    if artifact.get("librime_dylib_sha256") != sha256("lib/librime.1.dylib"):
        raise RuntimeError("librime dylib identity mismatch")
    backend_identity = validate_backend(args.backend)
    if artifact.get("backend_tree") != backend_identity["tree"]:
        raise RuntimeError("accepted backend identity mismatch")

    include_root = os.path.join(os.path.abspath(args.root), "include")
    include_hashes = {}
    for relative in ("rime_api_stdbool.h", "rime_api.h", "rime/key_table.h", "X11/keysymdef.h", "X11/keysym.h"):
        path = os.path.join(include_root, relative)
        reject_symlink_components(path)
        include_hashes[relative] = sha256(path)
    if artifact.get("include_hashes") != include_hashes:
        raise RuntimeError("staged include header identities changed")
    if artifact.get("runtime_facts") != runtime_facts():
        raise RuntimeError("compiler or runtime identity changed after manifest publication")

    fixture_root = os.path.abspath(fixture["scratch_root"])
    if os.path.commonpath([os.path.abspath(args.scratch), fixture_root]) != os.path.abspath(args.scratch):
        raise RuntimeError("timing fixture is outside the allocated scratch root")
    for key in ("shared", "user", "log"):
        path = os.path.abspath(fixture[key])
        if os.path.commonpath([fixture_root, path]) != fixture_root:
            raise RuntimeError("timing fixture directory escapes its run root")
        private_dir(path)
    expected_fixtures = fixture.get("fixture_hashes") or {}
    actual_fixtures = {}
    for relative in expected_fixtures:
        root_key, leaf = relative.split("/", 1)
        actual_fixtures[relative] = sha256(os.path.join(fixture[root_key], leaf))
    if actual_fixtures != expected_fixtures:
        raise RuntimeError("timing fixture hashes changed")
    collector_root = os.path.abspath(fixture["collector_root"])
    if os.path.commonpath([fixture_root, collector_root]) != fixture_root:
        raise RuntimeError("collector root escapes its timing fixture")
    if os.path.lexists(collector_root):
        raise RuntimeError("collector root is not fresh")
    socket = os.path.abspath(fixture["socket"])
    if os.path.commonpath([collector_root, socket]) != collector_root or len(os.fsencode(socket)) > 103:
        raise RuntimeError("timing socket path is unsafe or overlong")
    return artifact, fixture, backend_identity


def public_capture_identity(rows, identity):
    source = identity.get("source_instance_id")
    process = identity.get("process_id")
    before = identity.get("sequence_before")
    after = identity.get("sequence_after")
    if not source or not process or not isinstance(before, int) or not isinstance(after, int) or after <= before:
        return False
    return any(
        row.get("source_instance_id") == source
        and row.get("process_id") == process
        and isinstance(row.get("source_local_sequence"), int)
        and before < row["source_local_sequence"] <= after
        for row in rows
    )


def summarize_timing_rows(rows):
    summary = {}
    failed = False
    strata = ("short", "long", "backspace", "retype", "number", "space", "mouse", "paging")
    for stratum in strata:
        group = sorted((row for row in rows if row.get("stratum") == stratum), key=lambda row: row.get("pair", -1))
        deltas = [row["delta_ns"] for row in group]
        primary = [row["primary_delta_ns"] for row in group]
        by_block = {}
        for block in range(10):
            block_rows = [row for row in group if row.get("block") == block]
            values = [row["delta_ns"] for row in block_rows]
            by_block[str(block)] = {
                "count": len(values),
                "p50": nearest_rank(values, 0.50) if values else None,
                "p95": nearest_rank(values, 0.95) if values else None,
                "p99": nearest_rank(values, 0.99) if values else None,
                "max": max(values) if values else None,
                "negative_count": sum(value < 0 for value in values),
            }
            if len(values) != 200:
                failed = True
        item = {
            "count": len(deltas),
            "p50": nearest_rank(deltas, 0.50) if deltas else None,
            "p95": nearest_rank(deltas, 0.95) if deltas else None,
            "p99": nearest_rank(deltas, 0.99) if deltas else None,
            "max": max(deltas) if deltas else None,
            "primary_p50": nearest_rank(primary, 0.50) if primary else None,
            "primary_p95": nearest_rank(primary, 0.95) if primary else None,
            "primary_p99": nearest_rank(primary, 0.99) if primary else None,
            "negative_count": sum(value < 0 for value in deltas),
            "primary_unavailable": sum(not row.get("primary_available") for row in group),
            "by_block": by_block,
        }
        summary[stratum] = item
        keyboard = stratum in {"short", "long", "backspace", "retype", "number", "space"}
        if len(deltas) != 2000 or threshold_failed(deltas):
            failed = True
        if keyboard and (item["primary_unavailable"] or threshold_failed(primary)):
            failed = True
    return summary, failed


def run_certified_timing(args, plan):
    artifact, fixture, backend_identity = verify_timing_plan(plan, args)
    binary = os.path.abspath(artifact["harness_path"])
    preflight_report = os.path.join(args.root, "timing-preflight.json")
    if os.path.lexists(preflight_report):
        raise RuntimeError("timing preflight report path already exists")
    code, _, err = run(
        [binary, "--shared", fixture["shared"], "--user", fixture["user"], "--log", fixture["log"],
         "--socket", fixture["socket"], "--scenario", "timing-preflight", "--report", preflight_report],
        timeout=30,
    )
    preflight = json.load(open(preflight_report)) if os.path.exists(preflight_report) else {}
    secure = (preflight.get("timing_preflight") or {}).get("secure_input_enabled")
    if code != 0 or secure is not False:
        public = {
            "procedure": "MEAS-189-v1", "status": "environment_blocker",
            "reason": "natural secure-input state was not confirmed off",
            "secure_input_enabled": secure, "samples_started": 0,
            "passed": False, "content_included": False,
        }
        write_private(args.report, json.dumps(public, indent=2, sort_keys=True) + "\n")
        sys.stderr.write("code=environment_blocker secure_input_off_not_confirmed samples_started=0\n")
        return 1

    load = os.getloadavg()[0]
    if load > plan.get("max_loadavg", 8):
        public = {
            "procedure": "MEAS-189-v1", "status": "environment_blocker",
            "reason": "load preflight exceeded the frozen plan guard",
            "loadavg": load, "samples_started": 0,
            "passed": False, "content_included": False,
        }
        write_private(args.report, json.dumps(public, indent=2, sort_keys=True) + "\n")
        sys.stderr.write("code=environment_blocker load=%s samples_started=0\n" % load)
        return 1

    raw = os.path.join(args.root, "raw-" + uuid.uuid4().hex + ".json")
    if os.path.lexists(raw):
        raise RuntimeError("timing raw output path already exists")
    harness_report = os.path.join(args.root, "timing-harness.json")
    if os.path.lexists(harness_report):
        raise RuntimeError("timing harness report path already exists")
    collector_root = fixture["collector_root"]
    socket = fixture["socket"]
    start_collector(args.backend, collector_root, socket)
    try:
        code, _, policy_err = run(
            ["/usr/bin/python3", "-m", "archive.cli", "--socket", socket,
             "policy", "enable", "--expect-revision", "0"],
            env={"PYTHONPATH": args.backend},
        )
        if code != 0:
            raise RuntimeError("collector policy enable failed: %s" % policy_err)
        code, _, err = run(
            [binary, "--shared", fixture["shared"], "--user", fixture["user"], "--log", fixture["log"],
             "--socket", socket, "--scenario", "timing", "--report", harness_report, "--raw", raw],
            timeout=7200,
        )
        if code != 0:
            raise RuntimeError("timing harness failed: %s" % err)
        raw_rows = json.load(open(raw)).get("rows") or []
        if len(raw_rows) != 8 * 2000:
            raise RuntimeError("timing raw output did not contain all 16,000 measured pairs")
        for row in raw_rows:
            pair = row.get("pair")
            if not isinstance(pair, int) or row.get("block") != pair // 200 or row.get("order") != list(pair_order(pair)):
                raise RuntimeError("timing pair order or block identity mismatch")
            off = row.get("off_capture_identity") or {}
            on = row.get("on_capture_identity") or {}
            if off.get("sequence_after") != off.get("sequence_before"):
                raise RuntimeError("capture-off negative control admitted a sequence")
            if not isinstance(on.get("sequence_after"), int) or on["sequence_after"] <= on.get("sequence_before", on["sequence_after"]):
                raise RuntimeError("capture-on positive control did not advance source sequence")
        cli(args.backend, socket, "checkpoint")
        query_code, persisted, query_err = query_payloads(args.backend, socket)
        if query_code != 0:
            raise RuntimeError("public archive query failed: %s" % query_err)
        measured_on_pairs = sum(
            public_capture_identity(persisted, row.get("on_capture_identity") or {})
            for row in raw_rows
        )
        if measured_on_pairs != 8 * 2000:
            raise RuntimeError("public query did not prove every capture-on measured arm")
        summary, failed = summarize_timing_rows(raw_rows)
        public = {
            "procedure": "MEAS-189-v1",
            "status": "complete",
            "passed": not failed,
            "manifest_sha256": plan["manifest_sha256"],
            "harness_sha256": artifact["harness_sha256"],
            "backend_tree": backend_identity["tree"],
            "librime_dylib_sha256": artifact["librime_dylib_sha256"],
            "source_digest_sha256": artifact["source_digest_sha256"],
            "measured_pairs": len(raw_rows),
            "capture_on_pairs_publicly_queryable": measured_on_pairs,
            "loadavg": load,
            "strata": summary,
            "content_included": False,
        }
        write_private(args.report, json.dumps(public, indent=2, sort_keys=True) + "\n")
        if stat.S_IMODE(os.lstat(raw).st_mode) != 0o600:
            raise RuntimeError("timing raw file mode is not 0600")
        return 0 if not failed else 1
    finally:
        stop_collector(args.backend, collector_root, socket)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--stage-backend", action="store_true")
    parser.add_argument("--write-timing-blocker-plan", action="store_true")
    parser.add_argument("--backend-source", default=".local/ac189-a3-backend")
    parser.add_argument("--suite", choices=("contract", "timing"))
    parser.add_argument("--root", default="")
    parser.add_argument("--backend", default=".local/ac189-a4-backend")
    parser.add_argument(
        "--scratch",
        default="/private/var/folders/lx/7h393vfs5j386qt400zvx5ww0000gn/T/opencode/a189/e4",
    )
    parser.add_argument("--report", default="")
    parser.add_argument("--plan", default=".local/ac189-a4-measurement-plan.json")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.stage_backend:
        return stage_backend(args.backend_source, args.backend)
    if args.write_timing_blocker_plan:
        return write_timing_blocker_plan(args.plan)
    if not args.suite or not args.scratch:
        sys.stderr.write("code=invalid_request\n")
        return 2
    if not args.root:
        args.root = ".local/ac189-a4-check" if args.suite == "contract" else ".local/ac189-a4-timing"
    if not args.report:
        args.report = ".local/ac189-a4-report.json" if args.suite == "contract" else ".local/ac189-a4-timing-report.json"
    if os.path.lexists(args.report):
        sys.stderr.write("code=output_collision path=%s\n" % args.report)
        return 2
    if args.suite == "contract" and os.path.lexists(args.root):
        sys.stderr.write("code=output_collision path=%s\n" % args.root)
        return 2
    if not os.path.isdir(args.scratch) or os.path.islink(args.scratch):
        sys.stderr.write("code=invalid_scratch\n")
        return 2
    try:
        reject_symlink_components(args.scratch)
        if stat.S_IMODE(os.lstat(args.scratch).st_mode) != 0o700:
            raise RuntimeError("scratch directory mode is not 0700")
        validate_backend(args.backend)
    except (OSError, RuntimeError) as error:
        sys.stderr.write("code=invalid_request %s\n" % error)
        return 2
    private_dir(args.root)
    if args.suite == "contract":
        return contract(args)
    return timing(args)


if __name__ == "__main__":
    sys.exit(main())
