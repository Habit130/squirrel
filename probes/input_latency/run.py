#!/usr/bin/env python3
"""Per-key Pinyin candidate latency probes (Habit130/squirrel#172, AC-172-v1)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pwd
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.abspath(os.path.join(PROBE_DIR, "..", ".."))
LOCAL_ROOT = os.path.join(WORKTREE, ".local", "input-latency")
PLUGIN_DAEMON = os.path.join(WORKTREE, ".local", "plugin-src", "daemon")
INSTALLED_APP = "/Library/Input Methods/Squirrel.app"
INSTALLED_PLUGIN = os.path.join(
    INSTALLED_APP, "Contents/Frameworks/rime-plugins/librime-llm-rerank.dylib")
INSTALLED_LIBRIME = os.path.join(
    INSTALLED_APP, "Contents/Frameworks/librime.1.dylib")
SHARED_SUPPORT = os.path.join(INSTALLED_APP, "Contents/SharedSupport")
LIVE_PLUGIN = INSTALLED_PLUGIN
LIVE_CUSTOM = os.path.expanduser("~/Library/Rime/luna_pinyin.custom.yaml")
LIVE_COMPILED = os.path.expanduser("~/Library/Rime/build/luna_pinyin.schema.yaml")
LIVE_EVIDENCE = os.path.expanduser(
    "~/Library/Application Support/Squirrel/personal-bge-experiment/evidence.json")
LIVE_SOCKET = os.path.expanduser(
    "~/Library/Application Support/Squirrel/llm-rerank.sock")
AUTHORIZED_MODEL = (
    "/Users/habit/Developer/librime-llm-rerank/.local-work/models/BGE-M3")
PINNED_PLUGIN = "060254e544f73187f2b095928943320354d7cbca"
PINNED_PLUGIN_DYLIB = (
    "8b39a34163afa57829e4a61ae2bcb9566b364717fa7e1b367fca6d5fa281d0f0")
FROZEN_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
CONFIG_IDENTITY_LIVE = (
    "evidence-v1:repr=%s:tau=0.5:kev=8:H=128:sat=3:gamma=1"
)
REPRESENTATION_LIVE = (
    "dedicated-embedding-repr-v1:route=bge-m3-dense-1024:"
    "payload=candidate-conditioned-concat-v1:"
    "serialization=last64-preceding-plus-candidate:no-separator:no-special:"
    "model=b9d800590cbaf23471af0d0722870b0a6f8681dc09630ed12cd57db0a9c34b2d:"
    "tokenizer=ec113500465479de593e55e1972aee45f0932447604272792b5e98db0fb9a35a:"
    "adapter=bge-m3:instruction=none:pool=dense-mean:dim=1024:format=fp32-l2:"
    "metric=cosine:deps=torch@2.7.1,transformers@4.52.4,tokenizers@0.21.1,"
    "safetensors@0.5.3")
HOT_P95_MS = 50.0
HOT_P99_MS = 100.0
XK_BACKSPACE = 0xFF08
XK_ESCAPE = 0xFF1B
XK_RETURN = 0xFF0D
XK_SPACE = 0x0020


def real_home():
    return pwd.getpwuid(os.getuid()).pw_dir


def live_writable_roots():
    home = real_home()
    return [
        os.path.join(home, "Library", "Rime"),
        os.path.join(home, "Library", "Application Support", "Squirrel"),
    ]


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nearest_rank(values, pct):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    rank = int(math.ceil(pct / 100.0 * n))
    return ordered[min(n, max(1, rank)) - 1]


def ns_to_ms(ns):
    return ns / 1e6


def load_fixture():
    path = os.path.join(PROBE_DIR, "fixtures", "invented.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def reject_live_writable(path, label, errors):
    if not path:
        errors.append("%s is empty" % label)
        return
    abs_path = os.path.abspath(path)
    real = os.path.realpath(abs_path)
    for live in live_writable_roots():
        live_real = os.path.realpath(live)
        if real == live_real or real.startswith(live_real + os.sep):
            errors.append("%s resolves to live path %s" % (label, live_real))
        if abs_path == live or abs_path.startswith(live + os.sep):
            errors.append("%s is under live path %s" % (label, live))
    if os.path.islink(abs_path):
        target = os.path.realpath(abs_path)
        for live in live_writable_roots():
            live_real = os.path.realpath(live)
            if target == live_real or target.startswith(live_real + os.sep):
                errors.append("%s symlink aliases live path %s" % (label, live_real))


def isolation_check(paths):
    errors = []
    for label, path in paths.items():
        reject_live_writable(path, label, errors)
        parent = os.path.dirname(os.path.abspath(path)) if path else ""
        if parent:
            reject_live_writable(parent, label + ".parent", errors)
        if path and os.path.lexists(path) and stat.S_ISLNK(os.lstat(path).st_mode):
            reject_live_writable(path, label + ".symlink", errors)
    if errors:
        raise SystemExit("isolation self-check failed:\n- " + "\n- ".join(errors))
    return {"ok": True, "checked": paths, "live_writable_roots": live_writable_roots()}


def default_paths():
    root = LOCAL_ROOT
    return {
        "root": root,
        "staging": os.path.join(root, "staging"),
        "binary": os.path.join(root, "rime_session"),
        "venv": os.path.join(root, "venv"),
        "home": os.path.join(root, "home"),
        "facts": os.path.join(
            root, "home", "Library", "Application Support", "Squirrel",
            "SemanticMemory"),
        "derived": os.path.join(root, "derived"),
        "run_dir": "/tmp/s172",
        "socket": "/tmp/s172/llm-rerank.sock",
        "control_socket": "/tmp/s172/control.sock",
        "evidence_config": os.path.join(root, "evidence.json"),
        "log_dir": os.path.join(root, "rime-logs"),
        "results": os.path.join(root, "results"),
        "config": os.path.join(root, "config.json"),
        "rime_a": os.path.join(root, "rime-a"),
        "rime_b": os.path.join(root, "rime-b"),
        "rime_c": os.path.join(root, "rime-c"),
        "model": AUTHORIZED_MODEL,
        "shared_data_dir": SHARED_SUPPORT,
        "plugin_daemon": PLUGIN_DAEMON,
    }


def arm_custom_yaml(arm, socket_path, representation_id):
    processors_on = """  engine/processors:
    - llm_rerank_recorder
    - ascii_composer
    - recognizer
    - key_binder
    - speller
    - punctuator
    - selector
    - navigator
    - express_editor
  "engine/filters/+":
    - llm_rerank
"""
    processors_off = """  engine/processors:
    - ascii_composer
    - recognizer
    - key_binder
    - speller
    - punctuator
    - selector
    - navigator
    - express_editor
"""
    if arm == "C":
        return "patch:\n  switches/@2/reset: 1\n" + processors_off
    evidence = "true" if arm == "A" else "false"
    return """patch:
  switches/@2/reset: 1
%s  llm_rerank/recording_enabled: true
  llm_rerank/reranking_enabled: true
  llm_rerank/evidence_enabled: %s
  llm_rerank/alpha: 0.0
  llm_rerank/sys_coeff: 1.0
  llm_rerank/usr_coeff: 1.0
  llm_rerank/gamma: 1.0
  llm_rerank/saturate_k: 3.0
  llm_rerank/tau: 0.5
  llm_rerank/k_evidence: 8
  llm_rerank/half_life: 128
  llm_rerank/window: 32
  llm_rerank/deadline_ms: 200
  llm_rerank/baseline_policy_id: "mean-token-lm-v1"
  llm_rerank/socket_path: %s
  llm_rerank/representation_id: %s
""" % (processors_on, evidence, json.dumps(socket_path),
       json.dumps(representation_id))


def write_rime_user_dir(user_dir, arm, socket_path, representation_id):
    os.makedirs(user_dir, exist_ok=True)
    with open(os.path.join(user_dir, "default.custom.yaml"), "w",
              encoding="utf-8") as handle:
        handle.write("""patch:
  schema_list:
    - {schema: luna_pinyin}
  switcher/fix_schema_list_order: true
  menu/page_size: 5
""")
    with open(os.path.join(user_dir, "luna_pinyin.custom.yaml"), "w",
              encoding="utf-8") as handle:
        handle.write(arm_custom_yaml(arm, socket_path, representation_id))


def compile_harness(paths):
    src = os.path.join(PROBE_DIR, "rime_session.c")
    out = paths["binary"]
    librime = os.path.join(paths["staging"], "librime.1.dylib")
    if not os.path.isfile(librime):
        raise SystemExit("missing staged librime at %s" % librime)
    cmd = [
        "clang", "-O2", "-o", out, src, librime,
        "-Wl,-rpath,%s" % paths["staging"],
    ]
    subprocess.check_call(cmd, cwd=PROBE_DIR)
    return out


def live_hashes():
    items = {
        "installed_plugin": LIVE_PLUGIN,
        "installed_librime": INSTALLED_LIBRIME,
        "live_custom": LIVE_CUSTOM,
        "live_compiled": LIVE_COMPILED,
        "live_evidence_config": LIVE_EVIDENCE,
    }
    out = {}
    for key, path in items.items():
        if os.path.isfile(path):
            out[key] = {"path": path, "sha256": sha256_file(path)}
        else:
            out[key] = {"path": path, "sha256": None, "missing": True}
    return out


def unix_request(sock_path, payload, timeout=3.0):
    started = time.monotonic()
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    conn.connect(sock_path)
    conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    conn.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    conn.close()
    raw = b"".join(chunks).decode("utf-8")
    body = json.loads(raw.split("\n", 1)[0]) if raw.strip() else None
    return {
        "ok": True,
        "ms": (time.monotonic() - started) * 1000.0,
        "body": body,
    }


def health_request(sock_path, request_id, timeout=3.0):
    payload = {
        "version": 2,
        "request_id": request_id,
        "kind": "health",
    }
    try:
        result = unix_request(sock_path, payload, timeout)
        body = result.get("body") or {}
        result["ok"] = body.get("kind") == "health"
        return result
    except Exception as error:  # noqa: BLE001 - status-only observation
        return {
            "ok": False,
            "ms": 0.0,
            "error": type(error).__name__,
        }


class RimeProc:
    def __init__(self, paths, user_dir, include_text=False):
        env = os.environ.copy()
        env["HOME"] = paths["home"]
        env["DYLD_LIBRARY_PATH"] = paths["staging"]
        env["RIME_LOG_DIR"] = paths["log_dir"]
        err_path = os.path.join(paths["log_dir"], "rime_session.err")
        os.makedirs(paths["log_dir"], exist_ok=True)
        self._err = open(err_path, "ab")
        self.proc = subprocess.Popen(
            [paths["binary"]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._err,
            env=env,
            text=True,
            cwd=WORKTREE,
        )
        self.include_text = include_text
        self.user_dir = user_dir
        self.paths = paths

    def send(self, obj, timeout=60.0):
        line = json.dumps(obj, ensure_ascii=False)
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("rime_session response timeout")
            ready, _, _ = select.select(
                [self.proc.stdout.fileno()], [], [], remaining)
            if not ready:
                raise TimeoutError("rime_session response timeout")
            raw = self.proc.stdout.readline()
            if not raw:
                raise RuntimeError("rime_session exited")
            row = json.loads(raw)
            if not row.get("ok", True):
                raise RuntimeError(row.get("error", "rime_session error"))
            return row

    def init(self):
        return self.send({
            "op": "init",
            "home": self.paths["home"],
            "shared_data_dir": self.paths["shared_data_dir"],
            "user_data_dir": self.user_dir,
            "log_dir": self.paths["log_dir"],
            "schema": "luna_pinyin",
            "include_text": self.include_text,
        }, timeout=180.0)

    def key(self, code, mask=0, seq=0):
        return self.send({
            "op": "key",
            "code": code,
            "mask": mask,
            "seq": seq,
            "scheduled_ns": 0,
        })

    def type_text(self, text, seq0=0, scenario=""):
        rows = []
        seq = seq0
        for char in text:
            seq += 1
            row = self.key(ord(char), seq=seq)
            row["scenario"] = scenario
            row["char"] = char
            rows.append(row)
        return rows, seq

    def close(self):
        try:
            self.send({"op": "shutdown"}, timeout=10.0)
        except Exception:
            pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if getattr(self, "_err", None):
            self._err.close()
            self._err = None


def compiled_schema_identity(user_dir):
    path = os.path.join(user_dir, "build", "luna_pinyin.schema.yaml")
    if not os.path.isfile(path):
        return {"path": path, "missing": True}
    processors = []
    filters = []
    switches = {}
    section = None
    in_llm = False
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith("engine:"):
                section = "engine"
                in_llm = False
                continue
            if line.startswith("llm_rerank:"):
                in_llm = True
                section = None
                continue
            if line and not line.startswith(" ") and not line.startswith("\t"):
                in_llm = False
                section = None
            stripped = line.strip()
            if section == "engine":
                if stripped.startswith("processors:"):
                    section = "processors"
                    continue
                if stripped.startswith("filters:"):
                    section = "filters"
                    continue
            if section == "processors" and stripped.startswith("- "):
                processors.append(stripped[2:].strip().strip('"'))
            elif section == "filters" and stripped.startswith("- "):
                filters.append(stripped[2:].strip().strip('"'))
            elif section in ("processors", "filters") and stripped and not stripped.startswith("-") and ":" in stripped:
                section = "engine"
            if in_llm and ":" in stripped and not stripped.startswith("-"):
                key, value = stripped.split(":", 1)
                switches[key.strip()] = value.strip()
    return {
        "path": path,
        "sha256": sha256_file(path),
        "processors": processors,
        "filters": filters,
        "llm_rerank": switches,
    }


def start_daemon(paths, representation_id):
    os.makedirs(paths["facts"], exist_ok=True)
    os.chmod(paths["facts"], 0o700)
    os.makedirs(paths["derived"], exist_ok=True)
    os.makedirs(paths["run_dir"], exist_ok=True)
    os.chmod(paths["run_dir"], 0o700)
    evidence = {
        "provider_kind": "bge_m3",
        "bge_model_path": paths["model"],
        "representation_id": representation_id,
        "tau": 0.5,
        "k_evidence": 8,
        "half_life": 128,
        "saturation_k": 3.0,
        "gamma": 1.0,
        "retrieval_backend": "exact",
    }
    with open(paths["evidence_config"], "w", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2)
        handle.write("\n")
    for sock in (paths["socket"], paths["control_socket"]):
        if os.path.exists(sock):
            os.remove(sock)
    python = os.path.join(paths["venv"], "bin", "python")
    env = os.environ.copy()
    env["HOME"] = paths["home"]
    env["PYTHONPATH"] = PLUGIN_DAEMON
    cmd = [
        python, os.path.join(PLUGIN_DAEMON, "server.py"),
        "--serve", "--health-only",
        "--facts-root", paths["facts"],
        "--evidence-config", paths["evidence_config"],
        "--socket", paths["socket"],
        "--control-socket", paths["control_socket"],
    ]
    log_path = os.path.join(paths["root"], "daemon.log")
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd, cwd=PLUGIN_DAEMON, env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 300
    while time.time() < deadline:
        if proc.poll() is not None:
            log.close()
            raise SystemExit("isolated daemon exited early; see %s" % log_path)
        if os.path.exists(paths["socket"]):
            health = health_request(paths["socket"], "lat172-daemon-ready", 5.0)
            if health.get("ok") and (health.get("body") or {}).get("kind") == "health":
                log.close()
                return proc, health
        time.sleep(0.5)
    proc.terminate()
    log.close()
    raise SystemExit("isolated daemon did not become healthy in 300s")


def stop_proc(proc):
    if proc is None:
        return
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def machine_snapshot():
    load = os.getloadavg()
    ps = subprocess.check_output(
        ["ps", "-ax", "-o", "pid=,pcpu=,rss=,command="], text=True)
    competing = []
    for line in ps.splitlines():
        lower = line.lower()
        if any(token in lower for token in (
                "squirrel", "llm-rerank", "make ", "xcode", "ctest",
                "swiftlint", "periphery")):
            competing.append(line.strip()[:300])
    return {
        "loadavg": list(load),
        "ncpu": os.cpu_count(),
        "competing": competing[:30],
        "at": utc_now(),
    }


def summarize(rows, endpoint="event_to_candidate_ns"):
    values = [row[endpoint] for row in rows if endpoint in row]
    ms = [ns_to_ms(v) for v in values]
    return {
        "n": len(ms),
        "p50_ms": None if not ms else ns_to_ms(nearest_rank(values, 50)),
        "p95_ms": None if not ms else ns_to_ms(nearest_rank(values, 95)),
        "p99_ms": None if not ms else ns_to_ms(nearest_rank(values, 99)),
        "max_ms": None if not ms else max(ms),
        "endpoint": endpoint,
    }


def apply_counts(facts_root):
    path = os.path.join(facts_root, "traces", "client_apply.jsonl")
    counts = {"applied": 0, "fallback": 0, "unknown": 0, "other": 0, "path": path}
    if not os.path.isfile(path):
        counts["unavailable"] = True
        return counts
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                counts["other"] += 1
                continue
            state = row.get("apply_state") or row.get("state")
            if state in counts:
                counts[state] += 1
            else:
                counts["other"] += 1
    return counts


def tag_rows(rows, arm, run, scenario, history):
    for row in rows:
        row["arm"] = arm
        row["run"] = run
        row["scenario"] = scenario
        row["history"] = history
        row["class"] = "cold" if scenario == "a_cold" else (
            "background" if scenario.startswith("f_") else "warm")
    return rows


def seed_via_recording(paths):
    """Commit one invented competitive selection into the isolated store."""
    fixture = load_fixture()
    proc = RimeProc(paths, paths["rime_a"], include_text=True)
    try:
        proc.init()
        _rows, seq = proc.type_text(fixture["seed_segment"], 0, "seed")
        space = proc.key(XK_SPACE, seq=seq + 1)
    finally:
        proc.close()
    db_path = os.path.join(paths["facts"], "facts.sqlite3")
    return {
        "facts_db": os.path.isfile(db_path),
        "commit_bytes": space.get("commit_bytes"),
        "commit": space.get("commit"),
    }


def evidence_payload(candidates, request_id):
    fixture = load_fixture()
    return {
        "version": 2,
        "kind": "evidence",
        "request_id": request_id,
        "plan_identity": "lat172-" + request_id,
        "schema_id": "luna_pinyin",
        "category": "word",
        "canonical_segment_input": fixture["seed_segment"],
        "preceding_text": "",
        "candidates": candidates,
        "config_identity": CONFIG_IDENTITY_LIVE % REPRESENTATION_LIVE,
        "fact_high_water": None,
    }


def start_busy_encoder(paths):
    stop = threading.Event()
    candidates = [
        "城", "市", "成", "事", "程", "试", "乘", "势",
        "橙", "氏", "盛", "世", "诚", "实", "承", "释",
        "秤", "匙", "骋", "叱", "炽", "翅", "斥", "赤",
        "敕", "啻", "傺", "瘛", "铚", "豉", "彳", "叱",
    ]

    def loop():
        n = 0
        while not stop.is_set():
            n += 1
            try:
                unix_request(
                    paths["socket"],
                    evidence_payload(candidates, "busy-%s" % n),
                    timeout=120.0,
                )
            except Exception:
                if stop.wait(0.2):
                    break

    thread = threading.Thread(target=loop, name="lat172-busy", daemon=True)
    thread.start()
    return stop, thread


def warmup_evidence(paths):
    fixture = load_fixture()
    payload = {
        "version": 2,
        "kind": "evidence",
        "request_id": "lat172-bge-warmup",
        "plan_identity": "lat172-warmup",
        "schema_id": "luna_pinyin",
        "category": "word",
        "canonical_segment_input": fixture["seed_segment"],
        "preceding_text": "",
        "candidates": [fixture["seed_selected"], fixture["seed_competitor"]],
        "config_identity": CONFIG_IDENTITY_LIVE % REPRESENTATION_LIVE,
        "fact_high_water": None,
    }
    return unix_request(paths["socket"], payload, timeout=180.0)


def warmup_arm_a(paths):
    proc = RimeProc(paths, paths["rime_a"], include_text=False)
    try:
        proc.init()
        rows, seq = proc.type_text("ni", 0, "warmup")
        proc.key(XK_ESCAPE, seq=seq + 1)
        return rows
    finally:
        proc.close()


def run_arm_session(paths, arm, run, include_text=False):
    fixture = load_fixture()
    user_dir = paths["rime_%s" % arm.lower()]
    proc = RimeProc(paths, user_dir, include_text=include_text)
    rows = []
    assertions = {}
    try:
        init = proc.init()
        init["arm"] = arm
        init["run"] = run
        init["scenario"] = "init"
        rows.append(init)
        cold, seq = proc.type_text(fixture["short_pinyin"], 0, "a_cold")
        tag_rows(cold, arm, run, "a_cold", "none")
        rows.extend(cold)
        proc.key(XK_ESCAPE, seq=seq + 1)
        seq = 0
        cycles = 70
        warm = []
        for _ in range(cycles):
            chunk, seq = proc.type_text(fixture["short_pinyin"], seq, "b_warm_short")
            warm.extend(chunk)
            seq += 1
            proc.key(XK_ESCAPE, seq=seq)
        tag_rows(warm, arm, run, "b_warm_short", "none")
        rows.extend(warm)
        long_rows, seq = proc.type_text(fixture["long_pinyin"], 0, "c_long")
        tag_rows(long_rows, arm, run, "c_long", "none")
        rows.extend(long_rows)
        proc.key(XK_ESCAPE, seq=seq + 1)
        back, seq = proc.type_text(fixture["short_pinyin"], 0, "d_backspace")
        for _ in range(2):
            seq += 1
            row = proc.key(XK_BACKSPACE, seq=seq)
            row["scenario"] = "d_backspace"
            back.append(row)
        more, seq = proc.type_text("ao", seq, "d_backspace")
        back.extend(more)
        tag_rows(back, arm, run, "d_backspace", "none")
        rows.extend(back)
        proc.key(XK_ESCAPE, seq=seq + 1)
        sel, seq = proc.type_text(fixture["seed_segment"], 0, "e_select")
        seq += 1
        selected = proc.send({
            "op": "select",
            "index": 0,
            "seq": seq,
            "scheduled_ns": 0,
        })
        selected["scenario"] = "e_select"
        sel.append(selected)
        cont, seq = proc.type_text("you", seq, "e_select")
        sel.extend(cont)
        tag_rows(sel, arm, run, "e_select", "none")
        rows.extend(sel)
        if include_text:
            committed = "".join(
                row.get("commit") or "" for row in sel if row.get("commit"))
            assertions["e_select_commit_once"] = {
                "text": committed,
                "ok": committed.count(committed) == 1 if committed else False,
            }
        proc.key(XK_ESCAPE, seq=seq + 1)
        derived, seq = proc.type_text(fixture["short_pinyin"], 0, "f_derived")
        tag_rows(derived, arm, run, "f_derived", "recording")
        rows.extend(derived)
        proc.key(XK_ESCAPE, seq=seq + 1)
    finally:
        proc.close()
    return rows, assertions, compiled_schema_identity(user_dir)


def behavior_replay(paths):
    fixture = load_fixture()
    user_dir = paths["rime_c"]
    proc = RimeProc(paths, user_dir, include_text=True)
    result = {"ok": True, "checks": []}
    try:
        proc.init()
        rows, seq = proc.type_text(fixture["short_pinyin"], 0, "commit")
        space = proc.key(XK_SPACE, seq=seq + 1)
        committed = (space.get("commit") or "") + "".join(
            row.get("commit") or "" for row in rows)
        # Space often commits the highlighted candidate.
        if not committed:
            committed = space.get("commit") or ""
        check = {
            "name": "commit_once",
            "expected": fixture["short_expected_commit"],
            "got": committed,
            "ok": committed == fixture["short_expected_commit"] or (
                space.get("commit_bytes") == 6 and not space.get("composing")),
        }
        result["checks"].append(check)
        rows2, seq = proc.type_text(fixture["short_pinyin"], 0, "cancel")
        esc = proc.key(XK_ESCAPE, seq=seq + 1)
        cancelled = not esc.get("composing") and not (esc.get("preedit") or "")
        result["checks"].append({
            "name": "escape_cancels_composition",
            "ok": bool(cancelled),
        })
        typed, seq = proc.type_text("nihao", 0, "backspace")
        proc.key(XK_BACKSPACE, seq=seq + 1)
        proc.key(XK_BACKSPACE, seq=seq + 2)
        ctx = proc.send({"op": "context", "seq": seq + 3, "scheduled_ns": 0})
        result["checks"].append({
            "name": "backspace_shortens_preedit",
            "preedit": ctx.get("preedit"),
            "ok": (ctx.get("preedit_bytes") or 0) < 5,
        })
        del typed, rows2
        result["ok"] = all(item["ok"] for item in result["checks"])
    finally:
        proc.close()
    return result


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def prepare_config(config_path):
    paths = default_paths()
    os.makedirs(paths["root"], exist_ok=True)
    os.makedirs(paths["home"], exist_ok=True)
    os.makedirs(paths["log_dir"], exist_ok=True)
    os.makedirs(os.path.join(paths["home"], "Library", "Application Support",
                             "Squirrel"), exist_ok=True)
    os.makedirs(paths["run_dir"], exist_ok=True)
    os.chmod(paths["run_dir"], 0o700)
    isolation = isolation_check({
        "home": paths["home"],
        "facts": paths["facts"],
        "derived": paths["derived"],
        "run_dir": paths["run_dir"],
        "socket": paths["socket"],
        "log_dir": paths["log_dir"],
        "rime_a": paths["rime_a"],
        "rime_b": paths["rime_b"],
        "rime_c": paths["rime_c"],
        "results": paths["results"],
    })
    config = {
        "paths": paths,
        "representation_id": REPRESENTATION_LIVE,
        "plugin_pin": PINNED_PLUGIN,
        "expected_plugin_sha256": PINNED_PLUGIN_DYLIB,
        "model": AUTHORIZED_MODEL,
        "isolation": isolation,
        "endpoint": {
            "name": "event_to_candidate_update",
            "definition": (
                "monotonic time from rime_session handler entry through "
                "process_key/select plus get_commit plus get_context "
                "(librime candidate list available). Not IMK host dispatch "
                "and not vsync/presentation."),
            "queue_delay": (
                "pipe delay from Python scheduled_ns to C arrival_ns"),
            "presentation": "not exercised; environment/permission gap",
        },
        "targets_ms": {"p95": HOT_P95_MS, "p99": HOT_P99_MS},
    }
    dest = config_path or paths["config"]
    write_json(dest, config)
    return config


def cmd_self_test(args):
    paths = default_paths()
    os.makedirs(paths["root"], exist_ok=True)
    os.makedirs(paths["home"], exist_ok=True)
    os.makedirs(paths["log_dir"], exist_ok=True)
    os.makedirs(paths["run_dir"], exist_ok=True)
    os.chmod(paths["run_dir"], 0o700)
    isolation = isolation_check({
        "home": paths["home"],
        "facts": paths["facts"],
        "derived": paths["derived"],
        "run_dir": paths["run_dir"],
        "socket": paths["socket"],
        "log_dir": paths["log_dir"],
        "rime_c": paths["rime_c"],
    })
    compile_harness(paths)
    write_rime_user_dir(paths["rime_c"], "C", paths["socket"], REPRESENTATION_LIVE)
    proc = RimeProc(paths, paths["rime_c"], include_text=True)
    try:
        init = proc.init()
        overhead = proc.send({"op": "overhead", "n": 2000})
        rows, seq = proc.type_text("ni", 0, "self-test")
        assert rows and rows[-1]["num_candidates"] >= 1, "expected candidates"
        proc.key(XK_ESCAPE, seq=seq + 1)
    finally:
        proc.close()
    behavior = behavior_replay(paths)
    if not behavior["ok"]:
        raise SystemExit("behavior assertions failed: %s" % behavior)
    print(json.dumps({
        "ok": True,
        "isolation": isolation["ok"],
        "init_version": init.get("version"),
        "overhead_ns": overhead.get("total_ns"),
        "behavior": behavior,
        "plugin_module_required": True,
    }, indent=2))
    return 0


def cmd_collect(args):
    config = prepare_config(args.config)
    paths = config["paths"]
    out_dir = args.output or paths["results"]
    os.makedirs(out_dir, exist_ok=True)
    print("QUIET-MACHINE START #172 measured interval", utc_now(), flush=True)
    pre_live = live_hashes()
    pre_machine = machine_snapshot()
    live_health = health_request(LIVE_SOCKET, "lat172-live-health-1", 3.0)
    compile_harness(paths)
    staged_plugin = os.path.join(
        paths["staging"], "rime-plugins", "librime-llm-rerank.dylib")
    identities = {
        "squirrel_base": "20969777183d7d9998ef88780a71e4b2dbe20410",
        "plugin_source_pin": PINNED_PLUGIN,
        "installed_plugin_sha256": pre_live["installed_plugin"]["sha256"],
        "staged_plugin_sha256": sha256_file(staged_plugin),
        "installed_librime_sha256": pre_live["installed_librime"]["sha256"],
        "expected_plugin_sha256": PINNED_PLUGIN_DYLIB,
        "plugin_match": pre_live["installed_plugin"]["sha256"] == PINNED_PLUGIN_DYLIB,
        "installed_vs_source": (
            "Installed dylib copied read-only; plugin product not rebuilt. "
            "Source pin %s is reference only." % PINNED_PLUGIN),
        "model_path": AUTHORIZED_MODEL,
        "representation_id": REPRESENTATION_LIVE,
        "live_health": live_health,
        "live_hashes_pre": pre_live,
    }
    for arm in ("A", "B", "C"):
        write_rime_user_dir(
            paths["rime_%s" % arm.lower()], arm, paths["socket"],
            REPRESENTATION_LIVE)
    daemon = None
    all_rows = []
    schema_ids = {}
    apply_stats = {}
    daemon_health = []
    try:
        daemon, ready = start_daemon(paths, REPRESENTATION_LIVE)
        daemon_health.append({"when": "ready", **ready})
        if daemon.poll() is not None:
            raise SystemExit("isolated daemon died after ready")
        seed_info = seed_via_recording(paths)
        write_json(os.path.join(out_dir, "seed.json"), seed_info)
        warmup = warmup_evidence(paths)
        write_json(os.path.join(out_dir, "warmup.json"), {
            "ok": warmup.get("ok"),
            "ms": warmup.get("ms"),
            "status": (warmup.get("body") or {}).get("status"),
            "kind": (warmup.get("body") or {}).get("kind"),
            "error_code": ((warmup.get("body") or {}).get("error") or {}).get("code"),
        })
        if daemon.poll() is not None:
            raise SystemExit("isolated daemon died during BGE warmup")
        busy_rows = []
        busy = start_busy_encoder(paths)
        try:
            time.sleep(1.0)
            rime = RimeProc(paths, paths["rime_a"], include_text=False)
            try:
                rime.init()
                busy_rows, _seq = rime.type_text("nihao" * 5, 0, "busy_bge")
            finally:
                rime.close()
        finally:
            busy[0].set()
            busy[1].join(timeout=2)
        tag_rows(busy_rows, "A", 0, "busy_bge", "seeded")
        all_rows.extend(busy_rows)
        daemon_health.append({
            "when": "post-warmup",
            **health_request(paths["socket"], "lat172-post-warmup", 5.0),
        })
        for run in range(1, 4):
            for arm in ("A", "B", "C"):
                print("collect arm=%s run=%s" % (arm, run), flush=True)
                rows, _asserts, schema = run_arm_session(paths, arm, run)
                schema_ids["%s-run%s" % (arm, run)] = schema
                all_rows.extend(rows)
                health = health_request(
                    paths["socket"], "lat172-arm-%s-run-%s" % (arm, run), 1.0)
                daemon_health.append({"arm": arm, "run": run, **health})
        apply_stats = apply_counts(paths["facts"])
    finally:
        stop_proc(daemon)
        print("QUIET-MACHINE END #172 measured interval", utc_now(), flush=True)
    post_live = live_hashes()
    letter_rows = [
        row for row in all_rows
        if row.get("op") == "key" and row.get("scenario") == "b_warm_short"
    ]
    by_arm = {}
    for arm in ("A", "B", "C"):
        arm_rows = [row for row in letter_rows if row.get("arm") == arm]
        by_arm[arm] = {
            "warm_short": summarize(arm_rows),
            "cold": summarize([
                row for row in all_rows
                if row.get("arm") == arm and row.get("scenario") == "a_cold"
                and row.get("op") == "key"]),
            "long": summarize([
                row for row in all_rows
                if row.get("arm") == arm and row.get("scenario") == "c_long"
                and row.get("op") == "key"]),
            "backspace": summarize([
                row for row in all_rows
                if row.get("arm") == arm and row.get("scenario") == "d_backspace"
                and row.get("op") == "key"]),
            "select": summarize([
                row for row in all_rows
                if row.get("arm") == arm and row.get("scenario") in (
                    "e_select",) and row.get("op") in ("key", "select")]),
            "derived": summarize([
                row for row in all_rows
                if row.get("arm") == arm and row.get("scenario") == "f_derived"
                and row.get("op") == "key"]),
            "process_key": summarize(arm_rows, "process_key_ns"),
            "get_context": summarize(arm_rows, "get_context_ns"),
            "queue_delay": summarize(arm_rows, "queue_delay_ns"),
            "n_warm_keys": len(arm_rows),
        }
    busy_stats = summarize([
        row for row in all_rows
        if row.get("scenario") == "busy_bge" and row.get("op") == "key"])
    by_arm["A"]["busy_bge"] = busy_stats
    raw_path = os.path.join(out_dir, "timing.jsonl")
    with open(raw_path, "w", encoding="utf-8") as handle:
        for row in all_rows:
            exported = {key: value for key, value in row.items()
                        if key not in ("preedit", "commit", "candidates", "char")}
            handle.write(json.dumps(exported, ensure_ascii=False) + "\n")
    summary = {
        "identities": identities,
        "schema": schema_ids,
        "arms": by_arm,
        "apply": apply_stats,
        "daemon_health": daemon_health,
        "live_hashes_post": post_live,
        "live_hash_unchanged": pre_live == post_live,
        "machine_pre": pre_machine,
        "machine_post": machine_snapshot(),
        "raw": raw_path,
        "endpoint": config["endpoint"],
        "n_rows": len(all_rows),
    }
    write_json(os.path.join(out_dir, "summary.json"), summary)
    write_json(os.path.join(out_dir, "manifest.json"), {
        "fixture": load_fixture(),
        "replay": {
            "runs": 3,
            "arms": ["A", "B", "C"],
            "warm_short_cycles_per_run": 70,
            "command": "python3 probes/input_latency/run.py --collect",
        },
        "identities": identities,
    })
    print(json.dumps({
        "ok": True,
        "output": out_dir,
        "warm_n": {arm: by_arm[arm]["n_warm_keys"] for arm in by_arm},
        "warm_p95_ms": {arm: by_arm[arm]["warm_short"]["p95_ms"] for arm in by_arm},
    }, indent=2))
    missing = [arm for arm, info in by_arm.items() if info["n_warm_keys"] < 1000]
    if missing:
        raise SystemExit("incomplete dataset: warm keys < 1000 for %s" % missing)
    return 0


def cmd_repro(args):
    config = prepare_config(args.config)
    paths = config["paths"]
    print("QUIET-MACHINE START #172 repro interval", utc_now(), flush=True)
    compile_harness(paths)
    os.makedirs(paths["facts"], exist_ok=True)
    os.chmod(paths["facts"], 0o700)
    write_rime_user_dir(paths["rime_a"], "A", paths["socket"], REPRESENTATION_LIVE)
    daemon = None
    busy = None
    rows = []
    try:
        daemon, _ready = start_daemon(paths, REPRESENTATION_LIVE)
        warmup_evidence(paths)
        rime = RimeProc(paths, paths["rime_a"], include_text=False)
        try:
            rime.init()
            busy = start_busy_encoder(paths)
            time.sleep(1.0)
            typed, _seq = rime.type_text("nihao" * 4, 0, "busy_bge")
            rows = typed
        finally:
            rime.close()
    finally:
        if busy is not None:
            busy[0].set()
            busy[1].join(timeout=2)
        stop_proc(daemon)
        print("QUIET-MACHINE END #172 repro interval", utc_now(), flush=True)
    stats = summarize([row for row in rows if row.get("op") == "key"])
    red = (stats["p95_ms"] or 0) > HOT_P95_MS or (stats["p99_ms"] or 0) > HOT_P99_MS
    print(json.dumps({
        "endpoint": "event_to_candidate_update",
        "n": stats["n"],
        "p95_ms": stats["p95_ms"],
        "p99_ms": stats["p99_ms"],
        "target_p95_ms": HOT_P95_MS,
        "target_p99_ms": HOT_P99_MS,
        "symptom": red,
    }, indent=2))
    return 2 if red else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--repro", action="store_true")
    parser.add_argument("--config")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.self_test:
        return cmd_self_test(args)
    if args.collect:
        return cmd_collect(args)
    if args.repro:
        return cmd_repro(args)
    parser.error("one of --self-test --collect --repro is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
