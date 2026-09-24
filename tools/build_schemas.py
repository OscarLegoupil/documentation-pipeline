"""Reproducible JSON Schema builder; generated schemas ship with the skill."""
import json
from pathlib import Path

DEST = Path(__file__).resolve().parents[1] / ".github/skills/generate-documentation/schemas"


def obj(properties, optional=()):
    return {"type": "object", "properties": properties, "required": [p for p in properties if p not in optional], "additionalProperties": False}


def arr(item, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum}


def enum(*values):
    return {"enum": list(values)}


def ref(name):
    return {"$ref": "#/$defs/" + name}


text = {"type": "string", "minLength": 1, "maxLength": 8000}
ident = {"type": "string", "pattern": "^[a-z][a-z0-9._-]{1,95}$"}
ids = arr(ident)
hash_ = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
integer = {"type": "integer", "minimum": 0}
source = obj({"id": ident, "path": text, "hash": hash_, "start": integer, "end": integer, "snippet": {"type": "string"}, "symbol": text}, ("snippet", "symbol"))
fact = obj({"id": ident, "type": enum("responsibility", "interface", "configuration", "data", "dependency", "entry-point", "lifecycle", "side-effect", "failure", "retry", "concurrency", "rationale", "maintenance"), "statement": text, "status": enum("observed", "inferred", "unknown"), "basis": enum("implementation", "test-expectation", "declaration", "documentation", "not-established"), "evidence": ids, "explanation": text, "conflicts": ids})
relation = obj({"id": ident, "source": text, "target": text, "type": enum("import", "call", "route", "event", "queue", "read", "write", "schema", "configuration", "deployment", "transition"), "status": enum("observed", "inferred", "unknown"), "label": text, "facts": arr(ident, 1)})
owner = obj({"path": text, "subsystem": ident, "reason": text, "facts": ids, "unresolved": {"type": "boolean"}})
block = obj({"id": ident, "markdown": text, "facts": arr(ident, 1)})
section = obj({"id": ident, "subsystem": ident, "title": text, "blocks": arr(ref("block"), 1)})
diagram = obj({"id": ident, "subsystem": ident, "title": text, "purpose": enum("context", "dependency", "dataflow", "state", "ordered-flow"), "caption": text, "nodes": arr(obj({"id": ident, "component": text, "label": {"type": "string", "minLength": 1, "maxLength": 70}, "kind": enum("component", "store", "external", "state"), "facts": arr(ident, 1)}), 1), "edges": arr(obj({"source": ident, "target": ident, "relation": ident, "label": {"type": "string", "minLength": 1, "maxLength": 70}, "step": integer})), "facts": arr(ident, 1)})
finding = obj({"id": ident, "severity": enum("blocker", "note"), "blocks": arr(ident, 1), "facts": ids, "evidence": ids, "message": text})
defs = {"source": source, "fact": fact, "relation": relation, "owner": owner, "block": block, "section": section, "diagram": diagram, "finding": finding}
base = {"version": {"const": 1}, "task_id": ident, "snapshot": hash_, "input_fingerprint": hash_, "summary": text}
variants = {
    "discover": {"proposals": arr(obj({"subsystem": ident, "paths": arr(text, 1), "reason": text}), 1), "uncertainties": arr(text)},
    "analyze": {"chunks": arr(ident, 1), "evidence": arr(ref("source")), "facts": arr(ref("fact"), 1), "relations": arr(ref("relation")), "categories": obj({key: text for key in ("responsibilities", "interfaces", "configuration", "data", "dependencies", "entry_points", "lifecycle", "side_effects", "errors_retries", "concurrency", "rationale")})},
    "reconcile": {"ownership": arr(ref("owner")), "relations": arr(ref("relation")), "conflicts": arr(obj({"facts": arr(ident, 2), "resolution": text, "resolved": {"type": "boolean"}})), "entry_points": arr(obj({"fact": ident, "component": text, "subsystem": ident, "downstream": ids, "unresolved": {"type": "string", "maxLength": 8000}}))},
    "write": {"sections": arr(ref("section"), 1), "diagrams": arr(ref("diagram"))},
    "synthesize": {"sections": arr(ref("section"), 1), "diagrams": arr(ref("diagram"))},
    "review": {"checked_blocks": arr(ident, 1), "checked_facts": arr(ident, 1), "findings": arr(ref("finding")), "context": enum("fresh-subagent", "fresh-chat", "same-context"), "limitations": arr(text)}
}


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:docgen:result:1", "$defs": defs, "oneOf": [obj({**base, "kind": {"const": kind}, **fields}) for kind, fields in variants.items()]}
    (DEST / "result.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8", newline="\n")
    for kind, fields in variants.items():
        branch = obj({**base, "kind": {"const": kind}, **fields})
        needed = set()
        def collect(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    name = value["$ref"].split("/")[-1]
                    if name not in needed:
                        needed.add(name)
                        collect(defs[name])
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
        collect(branch)
        specific = {"$schema": schema["$schema"], **branch, "$defs": {name: defs[name] for name in sorted(needed)}}
        (DEST / f"{kind}.schema.json").write_text(json.dumps(specific, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
