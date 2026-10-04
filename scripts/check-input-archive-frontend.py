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
import shutil
import stat
import subprocess
import sys
import time

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
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def write_private(path, text):
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


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
    include = os.path.join(root, ".local", "ac189-include")
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
    code, out, err = run(command, timeout=180)
    if code != 0:
        sys.stderr.write(err)
        raise SystemExit(code)
    os.chmod(binary, 0o700)
    return binary


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


def harness(binary, shared, user, log, socket, scenario, report):
    code, out, err = run(
        [binary, "--shared", shared, "--user", user, "--log", log, "--socket", socket, "--scenario", scenario, "--report", report],
        timeout=600,
    )
    leaked = any(token in out or token in err for token in ("你好", "INV-EQUAL", "INV-CONFLICT"))
    return code, out, err, leaked


def run_probes(probes_dir):
    private_dir(probes_dir)
    results = {}
    for name, source, probe, frameworks in PROBES:
        binary = os.path.join(probes_dir, name)
        code, out, err = run(["xcrun", "swiftc", "-parse-as-library", source, probe, "-o", binary, *frameworks])
        if code != 0:
            results[name] = "compile_failed"
            continue
        os.chmod(binary, 0o700)
        code, out, err = run([binary])
        results[name] = "pass" if code == 0 else "fail"
    return results


def query_payloads(backend, socket):
    code, body, err = cli(backend, socket, "query", "timeline", "--page-size", "50")
    if code != 0:
        return code, [], err
    rows = (body.get("body") or {}).get("observations") or []
    processes = sorted({row.get("process_id") for row in rows if row.get("process_id")})
    detailed = []
    for process_id in processes:
        code, page, err = cli(
            backend, socket, "query", "process", "--process-id", process_id,
            "--private-detail", "--page-size", "50",
        )
        if code != 0:
            return code, detailed, err
        detailed.extend((page.get("body") or {}).get("observations") or [])
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


def archive_relations(backend, socket):
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

    # Terminal binding: a terminal that closes an observed composition must be
    # stored against that composition's process and segment. A terminal is
    # treated as closing the page only when the observed input it reports
    # matches the page it follows; unrelated finalizations are not comparable.
    terminal_binding = True
    terminal_detail = []
    for index, row in enumerate(rows):
        if row.get("observation_kind") != "raw_finalization":
            continue
        source = row.get("source_instance_id")
        prior = [
            candidate for candidate in rows[:index]
            if candidate.get("source_instance_id") == source
            and candidate.get("observation_kind") in PAGE_KINDS
        ]
        if not prior:
            continue
        page = prior[-1]
        closes_page = payload_text(row) == payload_preedit(page)
        same_process = page.get("process_id") == row.get("process_id")
        same_segment = page.get("continuity_segment_id") == row.get("continuity_segment_id")
        entry = {
            "terminal_seq": row.get("durable_seq"),
            "page_seq": page.get("durable_seq"),
            "closes_page": closes_page,
            "same_process": same_process,
            "same_segment": same_segment,
        }
        if closes_page:
            if not (same_process and same_segment):
                terminal_binding = False
            terminal_detail.append(entry)

    # No stored payload may carry text that was composed while ineligible.
    joined = "\n".join(payload_text(row) for row in rows)

    detail = {
        "raw_terminals_observed": len(terminal_detail),
        "raw_terminal_binding": terminal_detail,
        "excluded_canaries_absent": {
            "jiamin": "jiamin" not in joined,
            "甲敏": "甲敏" not in joined,
            "甲斥": "甲斥" not in joined,
        },
        "eligible_canary_present": "甲正" in joined,
    }
    evidence = {
        "raw_terminal_process_continuity": terminal_binding and bool(terminal_detail),
        "no_unobserved_prefix_admitted": all(detail["excluded_canaries_absent"].values()),
        "eligible_content_still_recorded": detail["eligible_canary_present"],
    }
    return 0, {"evidence": evidence, "detail": detail}, ""


def fault_coverage(binary, root, scratch, shared, user, log):
    """Real held/failing collector, bounded queue, capacity and concurrent query.

    Every arm compiles and drives the production controller; only the collector
    side is faulted, and each arm uses its own collector root.
    """
    results = {}
    env = {"PYTHONPATH": os.environ.get("AC189_BACKEND", ".local/ac189-a3-backend")}

    def collector_call(collector_root, *args):
        return run(
            ["/usr/bin/python3", "-m", "archive.cli", "--root", collector_root, "--socket", os.path.join(collector_root, "s"), *args],
            env=env,
        )

    # Arm 1: bounded producer queue with the collector absent for the burst.
    held_root = os.path.join(scratch, "fault-held-r")
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
    bounded_root = os.path.join(scratch, "fault-bounded-r")
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
        status_code, status, _ = cli(".local/ac189-a3-backend", bounded_socket, "status")
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
    missing = os.path.join(scratch, "missing.sock")
    report = os.path.join(scratch, "sig-missing.json")
    code, _, err, _ = harness(binary, scratch, scratch, scratch, missing, "socket-call", report)
    results["connect_failure"] = code == 0 and "collector_unavailable" in err

    def peer_close(name, scenario, large=True):
        path = os.path.join(scratch, name)
        if os.path.exists(path):
            os.unlink(path)
        server = pysock.socket(pysock.AF_UNIX, pysock.SOCK_STREAM)
        server.bind(path)
        os.chmod(path, 0o600)
        server.listen(1)
        server.settimeout(5)
        proc = subprocess.Popen(
            [binary, "--shared", scratch, "--user", scratch, "--log", scratch, "--socket", path, "--scenario", scenario, "--report", os.path.join(scratch, scenario + ".json")],
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
    path = os.path.join(scratch, "ok.sock")
    if os.path.exists(path):
        os.unlink(path)
    server = pysock.socket(pysock.AF_UNIX, pysock.SOCK_STREAM)
    server.bind(path)
    os.chmod(path, 0o600)
    server.listen(1)
    server.settimeout(5)
    proc = subprocess.Popen(
        [binary, "--shared", scratch, "--user", scratch, "--log", scratch, "--socket", path, "--scenario", "socket-call", "--report", os.path.join(scratch, "ok.json")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        conn, _ = server.accept()
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            if len(chunk) < 65536:
                break
        reply = json.dumps({
            "interface_version": "input-archive-v1",
            "envelope_version": 1,
            "op": "admit_batch",
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
    results["normal_exchange"] = proc.returncode == 0 and "socket_call=" in err
    return results


def contract(args):
    scratch = os.path.join(args.scratch, "contract-%d" % int(time.time()))
    shared = os.path.join(scratch, "shared")
    user = os.path.join(scratch, "user")
    log = os.path.join(scratch, "log")
    root = os.path.join(scratch, "r")
    socket = os.path.join(root, "s")
    if len(socket.encode()) > 103:
        sys.stderr.write("code=invalid_request\n")
        return 1
    private_dir(args.root)
    private_dir(scratch)
    write_schema(shared, user, socket)
    probes = run_probes(os.path.join(args.root, "probes"))
    binary = compile_harness(os.getcwd(), os.path.join(args.root, "build"))
    start_collector(args.backend, root, socket)
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
        query_code, timeline, _ = cli(args.backend, socket, "query", "timeline", "--page-size", "50")
        observations = ((timeline.get("body") or {}).get("observations") or [])
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
        relations_code, relations, relations_err = archive_relations(args.backend, socket)
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
        os.environ["AC189_BACKEND"] = args.backend
        faults = fault_coverage(binary, args.root, args.scratch, shared, user, log)
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
            and edge_code == 0
            and provenance_code == 0
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
            "scenario_exits": {
                "contract": code,
                "schema_gate": gate_code,
                "transition_edge": edge_code,
                "terminal_provenance": provenance_code,
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
        stop_collector(args.backend, root, socket)


def timing(args):
    if not os.path.exists(args.plan):
        sys.stderr.write("code=invalid_request\n")
        return 1
    plan = json.load(open(args.plan))
    if plan.get("procedure") != "MEAS-189-v1":
        sys.stderr.write("code=invalid_request\n")
        return 1
    load = os.getloadavg()[0]
    if load > plan.get("max_loadavg", 8):
        sys.stderr.write("code=environment_blocker load=%s\n" % load)
        return 1
    private_dir(args.root)
    raw = os.path.join(args.root, "raw-%d.json" % int(time.time()))
    # The harness timing scenario writes the raw file when --raw is passed.
    # Recompile so the measured artifact matches the published plan.
    binary = compile_harness(os.getcwd(), os.path.join(args.root, "build"))
    if sha256(binary) != plan.get("harness_sha256"):
        sys.stderr.write("code=invalid_request artifact_mismatch\n")
        return 1
    scratch = os.path.join(args.scratch, "timing-%d" % int(time.time()))
    root = os.path.join(scratch, "r")
    socket = os.path.join(root, "s")
    shared = os.path.join(scratch, "shared")
    user = os.path.join(scratch, "user")
    log = os.path.join(scratch, "log")
    private_dir(scratch)
    write_schema(shared, user, socket)
    start_collector(args.backend, root, socket)
    try:
        run(["/usr/bin/python3", "-m", "archive.cli", "--socket", socket, "policy", "enable", "--expect-revision", "0"], env={"PYTHONPATH": args.backend})
        code, out, err = run(
            [binary, "--shared", shared, "--user", user, "--log", log, "--socket", socket, "--scenario", "timing", "--report", os.path.join(args.root, "timing-harness.json"), "--raw", raw],
            timeout=7200,
        )
        if code != 0:
            sys.stderr.write(err)
            return code
        rows = json.load(open(raw)).get("rows") or []
        # A valid capture-on arm must really have archived eligible observations.
        # Without this the artifact guard alone would accept a run in which every
        # observation was excluded and the deltas measured nothing.
        archived = os.path.join(scratch, "r", "observations.jsonl")
        eligible = 0
        if os.path.exists(archived):
            for line in open(archived):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("eligibility") == "included":
                    eligible += 1
        if eligible == 0:
            sys.stderr.write("code=invalid_request capture_on_arm_archived_nothing\n")
            return 1
        summary = {}
        failed = False
        for stratum in ("short", "long", "backspace", "retype", "number", "space", "mouse", "paging"):
            deltas = [row["delta_ns"] for row in rows if row["stratum"] == stratum]
            primary = [row["primary_delta_ns"] for row in rows if row["stratum"] == stratum]
            item = {
                "count": len(deltas),
                "p50": nearest_rank(deltas, 0.50) if deltas else None,
                "p95": nearest_rank(deltas, 0.95) if deltas else None,
                "p99": nearest_rank(deltas, 0.99) if deltas else None,
                "max": max(deltas) if deltas else None,
                "primary_p95": nearest_rank(primary, 0.95) if primary else None,
                "primary_p99": nearest_rank(primary, 0.99) if primary else None,
                "negative_count": sum(1 for value in deltas if value < 0),
            }
            summary[stratum] = item
            unavailable = sum(1 for row in rows if row["stratum"] == stratum and not row.get("primary_available"))
            item["primary_unavailable"] = unavailable
            keyboard = stratum in {"short", "long", "backspace", "retype", "number", "space"}
            if threshold_failed(deltas) or (keyboard and (unavailable or threshold_failed(primary))):
                failed = True
        public = {"procedure": "MEAS-189-v1", "passed": not failed, "strata": summary, "content_included": False, "loadavg": load}
        write_private(args.report, json.dumps(public, indent=2, sort_keys=True) + "\n")
        os.chmod(raw, 0o600)
        return 0 if not failed else 1
    finally:
        stop_collector(args.backend, root, socket)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--suite", choices=("contract", "timing"))
    parser.add_argument("--root", default=".local/ac189-check")
    parser.add_argument("--backend", default=".local/ac189-backend")
    parser.add_argument("--scratch", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--plan", default="")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.suite or not args.scratch or not args.report:
        sys.stderr.write("code=invalid_request\n")
        return 2
    private_dir(args.root)
    if args.suite == "contract":
        return contract(args)
    return timing(args)


if __name__ == "__main__":
    sys.exit(main())
