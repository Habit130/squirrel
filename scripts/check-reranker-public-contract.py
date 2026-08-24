#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_JSON = ROOT / "docs" / "reranker-public-contract.json"
README = ROOT / "README.md"
CONTRACT_MD = ROOT / "docs" / "reranker-public-contract.md"
ACTION_INSTALL = ROOT / "action-install.sh"
FENCE = re.compile(r"```yaml\n(.*?)```", re.S)


def normalize(block: str) -> str:
    lines = []
    for raw in block.splitlines():
        without_comment = raw.split("#", 1)[0].rstrip()
        if without_comment.strip():
            lines.append(without_comment)
    return "\n".join(lines) + "\n"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    contract = json.loads(CONTRACT_JSON.read_text())
    expected = normalize(contract["example_yaml"])
    readme = README.read_text()
    contract_md = CONTRACT_MD.read_text()
    readme_blocks = [normalize(block) for block in FENCE.findall(readme)]
    md_blocks = [normalize(block) for block in FENCE.findall(contract_md)]
    if expected not in readme_blocks:
        fail("README.yaml example does not match contract example_yaml")
    if expected not in md_blocks:
        fail("docs/reranker-public-contract.md example does not match contract example_yaml")
    for phrase in contract["readme_forbidden_phrases"]:
        if phrase in readme:
            fail(f"README contains forbidden phrase: {phrase!r}")
    pin = f'llm_rerank_version="{contract["pinned_plugin"]["tag"]}"'
    if pin not in ACTION_INSTALL.read_text():
        fail(f"action-install.sh does not pin {pin}")
    if contract["pinned_plugin"]["commit"] not in contract_md:
        fail("contract markdown is missing the pinned plugin commit")
    for key, spec in contract["schema_keys"].items():
        if f"`{key}`" not in contract_md:
            fail(f"contract markdown missing key {key}")
        if spec["default_rendered"] not in contract_md:
            fail(f"contract markdown missing default {spec['default_rendered']!r} for {key}")
    for key, spec in contract["daemon_keys"].items():
        if spec["default_rendered"] not in contract_md:
            fail(f"contract markdown missing daemon default {spec['default_rendered']!r} for {key}")
    protocol = contract["protocol"]
    if f"version {protocol['version']}" not in contract_md.lower():
        fail(f"contract markdown missing protocol version {protocol['version']}")
    for field in (
        protocol["request_fields"]
        + protocol["success_response_fields"]
        + protocol["error_response_fields"]
        + protocol["error_object_fields"]
    ):
        if f"`{field}`" not in contract_md:
            fail(f"contract markdown missing protocol field {field}")
    print("reranker public contract check: ok")


if __name__ == "__main__":
    main()
