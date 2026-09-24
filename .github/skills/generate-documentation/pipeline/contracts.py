"""Strict schemas plus source and referential integrity, separate from semantics."""
from __future__ import annotations

import json
from pathlib import Path

from .common import Failure, SKILL, contained, digest, read_json, tokens
from .inventory import redact


def schema(result):
    if not isinstance(result, dict):
        raise Failure("Task result must be a JSON object")
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise Failure("Missing Python dependencies. Run setup.py and use its selected Python executable.", 3) from exc
    definition = read_json(SKILL / "schemas/result.schema.json")
    branch = next((s for s in definition["oneOf"] if s["properties"]["kind"]["const"] == result.get("kind")), None)
    if branch is None:
        raise Failure("Unknown result kind")
    validator = Draft202012Validator({**branch, "$defs": definition["$defs"]})
    errors = sorted(validator.iter_errors(result), key=lambda e: str(list(e.path)))
    if errors:
        raise Failure("Schema: " + "; ".join(f"{'.'.join(str(x) for x in e.path)}: {e.message[:250]}" for e in errors[:6]))


def registry(results):
    reg = {"evidence": {}, "facts": {}, "relations": {}, "blocks": {}, "diagrams": {}, "ownership": {}}
    for result in results:
        for field in ("evidence", "facts", "relations", "diagrams"):
            for item in result.get(field, []):
                if item["id"] in reg[field]:
                    raise Failure(f"Duplicate {field} ID: {item['id']}")
                reg[field][item["id"]] = item
        for section in result.get("sections", []):
            for block in section["blocks"]:
                if block["id"] in reg["blocks"]:
                    raise Failure(f"Duplicate block ID: {block['id']}")
                reg["blocks"][block["id"]] = block
        for owner in result.get("ownership", []):
            ident = result["task_id"] + ".owner-" + digest(owner["path"])[:12]
            if ident in reg["ownership"]:
                raise Failure("Duplicate ownership record ID: " + ident)
            reg["ownership"][ident] = {"id": ident, **owner}
    return reg


def refs(ids, collection, description):
    for ident in ids:
        if ident not in collection:
            raise Failure(f"Unknown {description}: {ident}")


def check_source(root, reference, allowed):
    p = reference["path"]
    path = contained(root, p)
    ranges = [a for a in allowed if a["path"] == p and a["hash"] == reference["hash"]]
    if not any(a["start"] <= reference["start"] <= reference["end"] <= a["end"] for a in ranges):
        raise Failure(f"Evidence range was not delivered/registered: {p}:{reference['start']}-{reference['end']}")
    try:
        raw = path.read_bytes()
        if digest(raw) != reference["hash"]:
            raise Failure(f"Stale evidence: {p}; rescan required", 5)
        lines, _ = redact(raw.decode("utf-8-sig", "strict"))
    except (OSError, UnicodeError) as exc:
        raise Failure(f"Cannot verify {p}: {exc}", 5) from exc
    start, end = reference["start"], reference["end"]
    if not (1 <= start <= end <= len(lines)) and not (start == end == len(lines) == 0):
        raise Failure(f"Invalid source lines: {p}:{start}-{end}")
    if "snippet" in reference and reference["snippet"] != "\n".join(lines[max(0, start - 1):end]):
        raise Failure(f"Snippet does not exactly match the redacted source range: {p}:{start}-{end}")


def validate_result(root, config, task, result, accepted, manifest, allowed, check_envelope=True):
    schema(result)
    def check_secrets(value):
        if isinstance(value, str):
            if redact(value)[1]:
                raise Failure("Result contains a likely secret literal. Retain variable names/usage and remove literal values before acceptance.")
        elif isinstance(value, dict):
            for item in value.values():
                check_secrets(item)
        elif isinstance(value, list):
            for item in value:
                check_secrets(item)
    check_secrets(result)
    if check_envelope:
        for field in ("task_id", "snapshot", "input_fingerprint", "kind"):
            expected = task["id"] if field == "task_id" else task[field]
            if result[field] != expected:
                raise Failure(f"Result {field} does not match assigned contract")
    if tokens(result) > config["result_tokens"]:
        raise Failure("Result exceeds result_tokens. Split content into smaller factual blocks; do not truncate evidence.")
    if tokens(result["summary"]) > config["summary_tokens"]:
        raise Failure("Summary exceeds summary_tokens; keep IDs with concise conclusions")
    own_ids = []
    for field in ("evidence", "facts", "relations", "diagrams", "findings"):
        own_ids.extend(x["id"] for x in result.get(field, []))
    for s in result.get("sections", []):
        own_ids.append(s["id"])
        own_ids.extend(b["id"] for b in s["blocks"])
    if len(own_ids) != len(set(own_ids)):
        raise Failure("Duplicate IDs within result")
    if any(not ident.startswith(task["id"] + ".") for ident in own_ids):
        raise Failure("Result IDs must use the assigned task ID plus '.' namespace")
    reg = registry([*accepted, result])
    entries = {e["path"]: e for e in manifest["entries"]}
    for e in result.get("evidence", []):
        check_source(root, e, allowed)
    for f in result.get("facts", []):
        refs(f["evidence"], reg["evidence"], "evidence")
        refs(f["conflicts"], reg["facts"], "conflicting fact")
        if f["status"] != "unknown" and not f["evidence"]:
            raise Failure("Observed/inferred facts need evidence")
        if f["status"] == "unknown" and f["basis"] != "not-established":
            raise Failure("Unknown facts must have not-established basis")
        if f["basis"] == "not-established" and f["status"] != "unknown":
            raise Failure("Not-established facts must remain unknown")
    for relation in result.get("relations", []):
        refs(relation["facts"], reg["facts"], "relation fact")
        for endpoint in (relation["source"], relation["target"]):
            if endpoint.startswith("external:"):
                continue
            contained(root, endpoint)
            if endpoint not in entries or not entries[endpoint]["eligible"]:
                raise Failure(f"Relation endpoint outside eligible scope must use external: prefix: {endpoint}")
        supporting = [reg["facts"][f] for f in relation["facts"]]
        if relation["status"] == "observed" and any(f["status"] != "observed" for f in supporting):
            raise Failure("Observed relations cannot upgrade inferred/unknown facts")
    if result["kind"] == "discover":
        paths = {a["path"] for a in allowed}
        for proposal in result["proposals"]:
            if not set(proposal["paths"]) <= paths:
                raise Failure("Discovery proposal contains an undelivered path")
    if result["kind"] == "analyze":
        if sorted(result["chunks"]) != sorted(a["id"] for a in task["chunks"]):
            raise Failure("Analysis must account for every assigned chunk exactly once")
        for chunk in task["chunks"]:
            if not any(e["path"] == chunk["path"] and chunk["start"] <= e["start"] <= e["end"] <= chunk["end"] for e in result["evidence"]):
                raise Failure(f"No evidence/fact account for chunk {chunk['id']}")
        if not all(any(e["id"] in f["evidence"] for f in result["facts"]) for e in result["evidence"]):
            raise Failure("Each source reference needs an associated fact")
    if result["kind"] == "reconcile":
        if sorted(o["path"] for o in result["ownership"]) != sorted(task["owner_paths"]):
            raise Failure("Ownership must account exactly once for assigned primary paths")
        for owner in result["ownership"]:
            refs(owner["facts"], reg["facts"], "ownership fact")
            if not owner["unresolved"] and not owner["facts"]:
                raise Failure("Resolved ownership needs facts")
        expected = {f["id"] for r in accepted if r["task_id"] in task["content_deps"] for f in r.get("facts", []) if f["type"] == "entry-point"}
        if set(e["fact"] for e in result["entry_points"]) != expected or len(result["entry_points"]) != len(expected):
            raise Failure("Every detected entry-point fact must have a mapping or unresolved row")
        for entry in result["entry_points"]:
            refs(entry["downstream"], reg["relations"], "entry-point downstream relation")
            if entry["component"] not in entries and not entry["unresolved"]:
                raise Failure("Unsupported entry-point component needs an unresolved explanation")
        for conflict in result["conflicts"]:
            refs(conflict["facts"], reg["facts"], "conflict fact")
            if len(set(conflict["facts"])) < 2:
                raise Failure("A conflict must reference at least two distinct facts")
    if result["kind"] in ("write", "synthesize"):
        for s in result["sections"]:
            for block in s["blocks"]:
                refs(block["facts"], reg["facts"], "block fact")
        for diagram in result["diagrams"]:
            refs(diagram["facts"], reg["facts"], "diagram fact")
            if len(diagram["nodes"]) > config["max_nodes"]:
                raise Failure("Diagram exceeds max_nodes; split the view")
            nodes = {n["id"]: n for n in diagram["nodes"]}
            if len(nodes) != len(diagram["nodes"]):
                raise Failure("Duplicate diagram node ID")
            for n in nodes.values():
                refs(n["facts"], reg["facts"], "diagram node fact")
                if n["component"] not in entries and not n["component"].startswith("external:"):
                    raise Failure("Unknown diagram component")
            for e in diagram["edges"]:
                refs([e["source"], e["target"]], nodes, "diagram node")
                refs([e["relation"]], reg["relations"], "diagram relation")
                relation = reg["relations"][e["relation"]]
                if (nodes[e["source"]]["component"], nodes[e["target"]]["component"]) != (relation["source"], relation["target"]):
                    raise Failure("Diagram edge endpoints do not match its relation")
            if diagram["purpose"] == "ordered-flow" and sorted(e["step"] for e in diagram["edges"]) != list(range(1, len(diagram["edges"]) + 1)):
                raise Failure("Ordered flows require consecutive unique steps beginning at 1")
    if result["kind"] == "review":
        targets = [r for r in accepted if r["task_id"] in task["content_deps"]]
        blocks = set(task["review_blocks"])
        facts = set(task["review_facts"])
        if set(result["checked_blocks"]) != blocks or set(result["checked_facts"]) != facts:
            raise Failure("Review must explicitly account for every assigned block/diagram and fact; no implicit sampling")
        for finding in result["findings"]:
            refs(finding["blocks"], blocks, "finding block")
            refs(finding["facts"], reg["facts"], "finding fact")
            refs(finding["evidence"], reg["evidence"], "finding evidence")
    return reg
