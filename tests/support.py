"""Hand-authored fixture artifacts. This is NOT a Copilot integration emulator/certification."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".github/skills/generate-documentation"
sys.path.insert(0, str(SKILL))
from pipeline.common import atomic, read_json
from pipeline.engine import Engine

CATEGORIES = ("responsibilities", "interfaces", "configuration", "data", "dependencies", "entry_points", "lifecycle", "side_effects", "errors_retries", "concurrency", "rationale")
EXPECTED = {
    "ledger.py": ("interface", "implementation", "Account.debit(amount: int) returns the remaining integer balance; it raises ValueError before mutation for non-positive amounts or insufficient balance."),
    "tests/test_ledger.py": ("failure", "test-expectation", "The test expects an insufficient withdrawal to raise ValueError and preserve balance 10. This test was read, not run."),
    "pyproject.toml": ("configuration", "declaration", "The fixture declares Python >=3.11 and pytest discovery under tests."),
    "README.md": ("responsibility", "documentation", "The README identifies hand-authored synthetic fixture material and describes documentation intent; it is not proof of executed behavior."),
    "service/routes.ts": ("entry-point", "implementation", "The declared POST /orders route uses postOrder, which calls createOrder with the request id and quantity."),
    "domain/orders.ts": ("interface", "implementation", "createOrder rejects non-positive quantities and returns the storage save result."),
    "storage/store.ts": ("retry", "implementation", "save tries runtimeAdapter.put at most three times and rethrows the third failure; adapter selection remains outside this fixture."),
    "infra/resources.yaml": ("entry-point", "declaration", "The fixture declares OrderStore and two route triggers; /replay refers to missing.dynamicHandler and no deployed name is established."),
    ".github/workflows/check.yml": ("maintenance", "declaration", "The CI fixture declares an echo step on push; no source execution result is available."),
    "main.f90": ("responsibility", "implementation", "The Fortran fixture assigns 3 + 4 to an integer total and declares a print statement."),
    "query.sql": ("data", "declaration", "The SQL fixture declares an item table with an integer primary key and required text label."),
    "notes.md": ("responsibility", "documentation", "The fixture contains Unicode text and describes generic non-Git analysis."),
    ".docgenignore": ("configuration", "declaration", "The fixture ignore file excludes the scratch directory."),
}


@lru_cache(maxsize=None)
def tool_path(name):
    override = os.environ.get("DOCGEN_TEST_" + name.upper())
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    suffix = ".exe" if os.name == "nt" else ""
    directories = [ROOT / ".tools" / name, ROOT / ".tools" / (name + "-linux")]
    if name == "soffice":
        directories.append(ROOT / ".tools/libreoffice")
    if name == "dot":
        directories.extend([ROOT / ".tools/graphviz", ROOT / ".tools/graphviz-linux"])
    if name == "pdftoppm":
        directories.append(ROOT / ".tools/poppler")
    matches = [p for directory in directories if directory.exists() for p in directory.rglob(name + suffix) if p.is_file()]
    return str(matches[0]) if matches else ""


def config(root, **values):
    rows = [f"{k} = {json.dumps(v)}" for k, v in values.items()]
    rows.append("[executables]")
    for tool in ("pandoc", "dot", "soffice", "pdftoppm"):
        if tool_path(tool):
            rows.append(f"{tool} = {json.dumps(tool_path(tool))}")
    (Path(root) / "docgen.toml").write_text("\n".join(rows) + "\n", encoding="utf-8")


def fixture(name="python-library", root=None):
    path = Path(root) if root else Path(tempfile.mkdtemp(prefix="docgen fixture ü "))
    shutil.copytree(ROOT / "tests/fixtures" / name, path, dirs_exist_ok=True)
    config(path, title="Hand-authored fixture — maintenance style sample")
    return path


def artifact(engine, task, layout=False):
    """Explicit test data supplied through the same public accept contract as a worker."""
    prefix = task["id"]
    base = {"version": 1, "task_id": prefix, "kind": task["kind"], "snapshot": task["snapshot"], "input_fingerprint": task["input_fingerprint"], "summary": "Hand-authored deterministic fixture artifact; no Copilot session was used."}
    if task["kind"] == "discover":
        return {**base, "proposals": [{"subsystem": "ledger", "paths": sorted({c["path"] for c in task["chunks"]}), "reason": "Provisional fixture ownership, to be reconciled."}], "uncertainties": ["Fixture declarations are not live runtime evidence."]}
    if task["kind"] == "analyze":
        evidence, facts = [], []
        for i, c in enumerate(task["chunks"], 1):
            eid, fid = prefix + f".e{i}", prefix + f".f{i}"
            evidence.append({k: c[k] for k in ("path", "hash", "start", "end")} | {"id": eid, "snippet": c["text"]})
            typ, basis, statement = EXPECTED.get(c["path"], ("responsibility", "implementation", "This synthetic test range contains the hand-authored fixture text."))
            if c["path"] == "README.md" and "Legacy claim" in c["text"]:
                statement = "The legacy README claims storage failures never retry; this is documented intent and contradicts the implementation loop."
            if c["start"] == c["end"] == 0:
                statement = "The fixture file is empty; no declarations can be inspected in this range."
            facts.append({"id": fid, "type": typ, "statement": statement, "status": "observed", "basis": basis, "evidence": [eid], "explanation": "Hand-authored expected fixture fact, verified mechanically against exact source range; no execution claim.", "conflicts": []})
        relations = []
        paths = {e["path"]: facts[i]["id"] for i, e in enumerate(evidence)}
        if "storage/store.ts" in paths:
            if "README.md" in paths:
                for f in facts:
                    if f["id"] == paths["README.md"]:
                        f["conflicts"] = [paths["storage/store.ts"]]
            eid = next(e["id"] for e in evidence if e["path"] == "storage/store.ts")
            facts.append({"id": prefix + ".unknown-adapter", "type": "configuration", "statement": "Runtime adapter selection and the deployed storage name are not established by this fixture.", "status": "unknown", "basis": "not-established", "evidence": [eid], "explanation": "Which external adapter and live resource supply runtimeAdapter?", "conflicts": []})
        if "infra/resources.yaml" in paths:
            fid = paths["infra/resources.yaml"]
            next(f for f in facts if f["id"] == fid)["type"] = "configuration"
            eid = next(e["id"] for e in evidence if e["path"] == "infra/resources.yaml")
            for n, (route, handler) in enumerate((("/orders", "service/routes.postOrder"), ("/replay", "missing.dynamicHandler")), 1):
                facts.append({"id": prefix + f".trigger{n}", "type": "entry-point", "statement": f"The declaration maps POST {route} to {handler}; it is not verified deployed behavior.", "status": "observed", "basis": "declaration", "evidence": [eid], "explanation": "Distinct fixture trigger declaration; dynamic handler resolution is unresolved.", "conflicts": []})
        for src, dst, typ in (("tests/test_ledger.py", "ledger.py", "import"), ("service/routes.ts", "domain/orders.ts", "call"), ("domain/orders.ts", "storage/store.ts", "call")):
            if src in paths and dst in paths:
                relations.append({"id": prefix + f".r{len(relations) + 1}", "source": src, "target": dst, "type": typ, "status": "observed", "label": "Declared " + typ, "facts": [paths[src]]})
        return {**base, "summary": base["summary"] + " " + " ".join(f["id"] for f in facts[:3]), "chunks": [c["id"] for c in task["chunks"]], "evidence": evidence, "facts": facts, "relations": relations, "categories": {k: "See explicit fixture facts; no additional runtime guarantees are established." for k in CATEGORIES}}
    if task["kind"] == "reconcile":
        data = task["payload"]["analysis"]
        evidence = {e["id"]: e for e in data["evidence"]}
        def owner(path):
            return "api" if path.startswith("service/") else "storage" if path.startswith("storage/") else "ledger"
        ownership = [{"path": p, "subsystem": owner(p), "reason": "Primary placement supported by the fixture's explicit source responsibilities.", "facts": [f["id"] for f in data["facts"] if any(evidence[e]["path"] == p for e in f["evidence"])], "unresolved": False} for p in task["owner_paths"]]
        entries = [{"fact": f["id"], "component": evidence[f["evidence"][0]]["path"], "subsystem": owner(evidence[f["evidence"][0]]["path"]), "downstream": [], "unresolved": "No runtime execution or dynamic handler resolution was performed."} for f in data["facts"] if f["type"] == "entry-point"]
        conflicts = [{"facts": [f["id"], other], "resolution": "The legacy no-retry statement conflicts with the source loop; preserve the discrepancy and use source-backed behavior for maintenance.", "resolved": False} for f in data["facts"] for other in f["conflicts"]]
        return {**base, "ownership": ownership, "relations": [], "conflicts": conflicts, "entry_points": entries}
    if task["kind"] in ("write", "synthesize"):
        if task["kind"] == "write":
            facts = [u["fact"] for u in task["payload"]["units"]]
            subsystem = task["payload"]["subsystem"]
        else:
            accepted = engine.results()
            facts = [f for r in accepted for f in r.get("facts", [])][:2]
            subsystem = "overview"
        fact_ids = [f["id"] for f in facts]
        blocks = [{"id": prefix + f".b{i}", "markdown": f["statement"] + f" [source](fact:{f['id']})", "facts": [f["id"]]} for i, f in enumerate(facts, 1)]
        if task["kind"] == "write" and any("Account.debit" in f["statement"] for f in facts):
            f = next(f for f in facts if "Account.debit" in f["statement"])
            marker = f"[source](fact:{f['id']})"
            blocks.insert(0, {"id": prefix + ".context", "markdown": "## Where it fits\n\nThe fixture library owns the balance mutation boundary. " + marker + "\n\n## Inputs\n\n| Input | Type / Shape | Source | When | Evidence |\n|---|---|---|---|---|\n| amount | positive integer | caller | debit invocation | " + marker + " |\n\n## Outputs\n\n| Output | Type / Shape | Destination | When | Evidence |\n|---|---|---|---|---|\n| remaining balance | integer | caller | accepted debit | " + marker + " |\n| ValueError | exception | caller | invalid or insufficient amount | " + marker + " |", "facts": [f["id"]]})
            if layout:
                lines = ["## Interface details", "", "The following layout fixture repeats a supported interface row to exercise multi-page tables; it is not additional application functionality. " + marker, "", "| Case | Interface / path | Expected source behavior |", "|---|---|---|"]
                lines += [f"| Layout row {i:02d} | `Account.debit` | Reject non-positive amount. {marker} |" for i in range(1, 56)]
                blocks.append({"id": prefix + ".layout", "markdown": "\n".join(lines), "facts": [f["id"]]})
                blocks.append({"id": prefix + ".unicode", "markdown": "## Interface details\n\nLayout sample typography: résumé, Київ, Δstate, → output. Long path example: `samples/very_long_repository_component_name/maintenance_contracts/repeated_interface_example.py`. This sentence is fixture presentation data alongside the supported debit signature. " + marker + "\n\n```python\ndef debit(self, amount: int) -> int:\n    # Source interface; do not execute during documentation.\n    ...\n```", "facts": [f["id"]]})
        diagrams = []
        relations = [r for result in engine.results() for r in result.get("relations", [])]
        if task["kind"] == "write" and relations and task["payload"]["part"] == 1 and subsystem == "ledger":
            relation = relations[0]
            is_test = relation["type"] == "import"
            diagrams = [{"id": prefix + ".d1", "subsystem": subsystem, "title": "Fixture dependency context", "purpose": "dependency", "caption": "The test source imports the account implementation; an import does not prove a runtime execution." if is_test else "The fixture declares this cross-component call in source; runtime execution is not verified.", "nodes": [{"id": "source", "component": relation["source"], "label": "Test expectations" if is_test else "Route component", "kind": "component", "facts": relation["facts"]}, {"id": "target", "component": relation["target"], "label": "Account interface" if is_test else "Order domain", "kind": "component", "facts": relation["facts"]}], "edges": [{"source": "source", "target": "target", "relation": relation["id"], "label": "imports" if is_test else "calls", "step": 0}], "facts": relation["facts"]}]
        return {**base, "summary": base["summary"] + " " + " ".join(fact_ids[:3]), "sections": [{"id": prefix + ".s1", "subsystem": subsystem, "title": "Maintenance context" if task["kind"] == "write" else "Fixture purpose and constraints", "blocks": blocks}], "diagrams": diagrams}
    if task["kind"] == "review":
        return {**base, "checked_blocks": task["review_blocks"], "checked_facts": task["review_facts"], "findings": [], "context": "same-context", "limitations": ["Hand-authored fixture review record for deterministic testing. No live Copilot semantic review occurred."]}
    raise ValueError(task["kind"])


def accept_next(engine, session, layout=False):
    receipt = engine.next(session)
    if not receipt.get("task_id"):
        return None
    task = engine.state["tasks"][receipt["task_id"]]
    result = artifact(engine, task, layout)
    atomic(Path(receipt["result"]), result)
    engine.accept(task["id"], session)
    return task["id"]


def finish_fixture(engine, session, layout=False):
    for _ in range(250):
        if not accept_next(engine, session, layout):
            return engine.status()
    raise AssertionError("Fixture DAG did not finish within 250 bounded tasks")
