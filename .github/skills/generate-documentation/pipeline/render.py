"""Local-only Pandoc AST assembly, safe diagrams, DOCX finishing and preview."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import textwrap
import xml.etree.ElementTree as ET

from .common import Failure, SKILL, atomic, code_version, contained, digest, executable, lock, read_json, run
from .contracts import registry
from .inventory import range_coverage
from .style import build_reference, finish

FORMAT = "markdown+pipe_tables+fenced_code_blocks+fenced_divs+bracketed_spans-raw_html-raw_tex-yaml_metadata_block"


def parse(markdown, root, config):
    raw = run([executable("pandoc", config), "--from", FORMAT, "--to", "json"], root, config["timeout"], input=markdown)
    return json.loads(raw)


def nodes(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from nodes(v)
    elif isinstance(value, list):
        for v in value:
            yield from nodes(v)


def fact_links(value):
    return {n["c"][2][0][5:] for n in nodes(value) if n.get("t") == "Link" and n["c"][2][0].startswith("fact:")}


def check_markdown(block, root, config, reg):
    text = block["markdown"]
    if "{{" in text or "}}" in text or "<%" in text or re.search(r"\[@[^\]]+\]", text):
        raise Failure("Unresolved placeholder or unsupported citation marker")
    ast = parse(text, root, config)
    ids = fact_links(ast)
    if ids != set(block["facts"]):
        raise Failure(f"Block {block['id']}: [source](fact:ID) markers must match its fact IDs exactly")
    for n in nodes(ast):
        t, c = n.get("t"), n.get("c")
        if t in ("RawBlock", "RawInline", "Image", "Note"):
            raise Failure("Model Markdown cannot contain raw markup, images or hand-written footnotes; use diagram specifications and fact links")
        if t == "Link" and not c[2][0].startswith(("fact:", "#")):
            raise Failure("Only fact: and internal # links are allowed in model Markdown; no remote/local resources")
        if t == "CodeBlock" and c[0][1] and c[0][1][0].lower() in ("dot", "mermaid", "graphviz"):
            raise Failure("Raw diagram source is not document content")
    # Each paragraph/list item needs a direct source note, each table body row its own.
    def inspect_blocks(blocks):
        for b in blocks:
            t, c = b["t"], b.get("c")
            if t in ("Para", "Plain") and not fact_links(b):
                raise Failure(f"Uncited substantive paragraph in {block['id']}")
            if t == "Table":
                for body in c[4]:
                    for row in [*body[2], *body[3]]:
                        if not fact_links(row):
                            raise Failure(f"Uncited factual table row in {block['id']}")
            if t in ("BulletList", "OrderedList"):
                for item in (c if t == "BulletList" else c[1]):
                    inspect_blocks(item)
            if t == "BlockQuote":
                inspect_blocks(c)
            if t == "Div":
                inspect_blocks(c[1])
    inspect_blocks(ast["blocks"])
    return ast


def str_(text):
    return {"t": "Str", "c": text}


def para(text):
    return {"t": "Para", "c": [str_(text)]}


def heading(level, title, ident):
    return {"t": "Header", "c": [level, [ident, [], []], [str_(title)]]}


def link_(label, target):
    return {"t": "Link", "c": [["", [], []], [str_(label)], [target, ""]]}


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ").replace("`", "'")


def diagram_assets(spec, relations, out, config):
    dot = executable("dot", config)
    q = lambda value: json.dumps(str(value), ensure_ascii=False)
    wrap = lambda text: "\n".join(textwrap.wrap(text, width=22, break_long_words=True))
    shapes = {"component": "box", "store": "cylinder", "external": "ellipse", "state": "ellipse"}
    lines = ['digraph view {', 'graph [rankdir=TB, bgcolor="white", pad=0.15, nodesep=0.4, ranksep=0.55];',
             'node [fontname="Arial", fontsize=14, style="rounded,filled", fillcolor="#E8F3F3", color="#' + config["branding"]["teal"] + '", margin="0.14,0.10"];',
             'edge [fontname="Arial", fontsize=14, color="#' + config["branding"]["navy"] + '", arrowsize=0.8];']
    for node in spec["nodes"]:
        lines.append(f'{q(node["id"])} [label={q(wrap(node["label"]))}, shape={shapes[node["kind"]]}];')
    for edge in spec["edges"]:
        relation = relations[edge["relation"]]
        status = relation["status"]
        label = (str(edge["step"]) + ". " if edge["step"] else "") + edge["label"]
        label += " [" + relation["type"] + "]"
        if status != "observed":
            label += " (" + status + ")"
        lines.append(f'{q(edge["source"])} -> {q(edge["target"])} [label={q(wrap(label))}, style={"solid" if status == "observed" else "dashed"}];')
    lines.append("}")
    dest = out / "diagrams"
    dest.mkdir(exist_ok=True)
    stem = dest / spec["id"]
    atomic(dest / (spec["id"] + ".json"), spec)
    # IDs contain dots, so append extensions rather than replacing identifier suffixes.
    dotpath = dest / (spec["id"] + ".dot")
    atomic(dotpath, "\n".join(lines))
    svg, png = dest / (spec["id"] + ".svg"), dest / (spec["id"] + ".png")
    run([dot, "-Tsvg", str(dotpath), "-o", str(svg)], out, config["timeout"])
    run([dot, "-Tpng", "-Gdpi=200", str(dotpath), "-o", str(png)], out, config["timeout"])
    if not svg.exists() or not png.exists() or min(svg.stat().st_size, png.stat().st_size) < 100:
        raise Failure("Diagram renderer produced missing/empty assets", 3)
    root = ET.fromstring(svg.read_bytes())
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    # Remove Graphviz's external SVG DTD declaration; assets require no remote resources.
    atomic(svg, ET.tostring(root, encoding="utf-8", xml_declaration=True))
    width_pt = float(root.attrib["width"].removesuffix("pt"))
    height_pt = float(root.attrib["height"].removesuffix("pt"))
    scale = min(1.0, (170 / 25.4 * 72) / width_pt, (210 / 25.4 * 72) / height_pt)
    effective = 14 * scale
    if effective < 9:
        raise Failure(f"Diagram {spec['id']} would have {effective:.1f}pt labels on the Word page. Split/group the view; do not shrink it.", 6)
    raw = png.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise Failure("Invalid rendered PNG", 3)
    w, h = struct.unpack(">II", raw[16:24])
    if min(w, h) < 40:
        raise Failure("Rendered diagram dimensions are too small", 3)
    return {"id": spec["id"], "png": png.relative_to(out).as_posix(), "svg": svg.relative_to(out).as_posix(), "width_inches": width_pt / 72 * scale, "effective_font_pt": round(effective, 2), "pixels": [w, h], "visual_review": "pending"}


def assemble(engine, out, partial, report, progress=None):
    results = engine.results()
    if progress is not None:
        selected = set(progress["writers"] + progress["reviews"])
        results = [r for r in results if r["kind"] not in ("write", "synthesize", "review") or r["task_id"] in selected]
    reg = registry(results)
    config = engine.config
    diagram_map = {d["id"]: diagram_assets(d, reg["relations"], out, config) for d in reg["diagrams"].values()}
    ast = parse("", engine.root, config)
    title = config["title"] + (" — Incomplete draft" if progress is not None else " — DRAFT INCOMPLETE" if partial else "")
    blocks = [{"t": "Div", "c": [["", [], [["custom-style", "Title"]]], [para(title)]]},
              para("Technical maintenance documentation"), para("Source-based analysis · " + config["audience"])]
    if config["branding"]["logo"]:
        logo = contained(engine.root, config["branding"]["logo"])
        dest = out / ("brand-logo" + logo.suffix.lower())
        shutil.copyfile(logo, dest)
        blocks.append({"t": "Para", "c": [{"t": "Image", "c": [["", [], [["width", "1.5in"]]], [str_("Logo")], [dest.name, ""]]}]})
    blocks.extend([para("Snapshot: " + engine.state["manifest"]["snapshot"]), para("Scope: " + ", ".join(config["scope"]))])
    git = engine.state["manifest"]["git"]
    if git["kind"] == "git":
        blocks.append(para("Git baseline: " + (git["commit"] or "unborn repository") + "; working tree dirty: " + str(git["dirty"]) + ". File hashes identify the documented working tree; HEAD alone does not."))
    else:
        blocks.append(para("Snapshot kind: non-Git directory. File hashes identify the source material read for this document."))
    if progress is not None:
        blocks.append(para("Incomplete draft. Only completed, validated and reviewed subsystem chapters are included. Final synthesis and strict final-export checks remain separate. Visual QA: pending. Human approval: not assigned."))
    elif partial:
        blocks.extend([para("DRAFT — INCOMPLETE. Required work remains. This is not a completed export."), *[para(x) for x in report["issues"]]])
    contents_index = len(blocks)
    blocks.append(heading(1, "Contents", "contents"))
    body = [] if progress is not None else [heading(1, "System overview", "system-overview")]
    if progress is not None:
        body.append(heading(1, "Subsystem progress", "subsystem-progress"))
        body.append(para("Incomplete draft — progress at the recorded source snapshot. A completed chapter is not approval of the entire repository document."))
        rows = ["| Status | Subsystems |", "|---|---|"]
        for status in ("completed", "pending", "blocked"):
            names = [cell(s["subsystem"] + (" (" + s["reason"] + ")" if s["reason"] else "")) for s in progress["subsystems"] if s["status"] == status]
            rows.append(f"| {status.capitalize()} | {'; '.join(names) or 'None'} |")
        body.extend(parse("\n".join(rows), engine.root, config)["blocks"])
        body.append(para("Pending or blocked chapters are omitted. Coverage later in this draft describes the whole recorded scope, including work outside the included chapters."))
    overview = engine.state.get("overview")
    authors = [r for r in results if r["kind"] == "write"]
    roots = [r for r in results if r["task_id"] == overview]
    if not roots and progress is None:
        body.append(para("Overview synthesis is incomplete."))
    used_facts, seen_diagrams = set(), set()

    def add_result(result, base_level=2):
        for section in result["sections"]:
            body.append(heading(base_level, section["title"], section["id"]))
            for block in section["blocks"]:
                parsed = check_markdown(block, engine.root, config, reg)
                used_facts.update(block["facts"])
                headers = [node for node in nodes(parsed["blocks"]) if node.get("t") == "Header"]
                min_level = min((node["c"][0] for node in headers), default=1)
                local_links = {node["c"][1][0]: block["id"] + "-" + node["c"][1][0] for node in headers}
                for node in nodes(parsed["blocks"]):
                    if node.get("t") == "Header":
                        node["c"][0] = min(6, node["c"][0] - min_level + base_level + 1)
                        node["c"][1][0] = local_links[node["c"][1][0]]
                    if node.get("t") == "Link" and node["c"][2][0].startswith("#") and node["c"][2][0][1:] in local_links:
                        node["c"][2][0] = "#" + local_links[node["c"][2][0][1:]]
                    if node.get("t") == "Link" and node["c"][2][0].startswith("fact:"):
                        ident = node["c"][2][0][5:]
                        node["c"][2][0] = "#" + ident
                        node["c"][1] = [str_("[" + str(sorted(reg["facts"]).index(ident) + 1) + "]")]
                body.extend(parsed["blocks"])
        for spec in result["diagrams"]:
            if spec["id"] in seen_diagrams:
                continue
            seen_diagrams.add(spec["id"])
            used_facts.update(spec["facts"])
            asset = diagram_map[spec["id"]]
            body.append({"t": "Para", "c": [{"t": "Image", "c": [[spec["id"], [], [["width", f"{asset['width_inches']:.3f}in"]]], [str_(spec["title"])], [asset["png"], ""]]}]})
            body.append({"t": "Div", "c": [["", [], [["custom-style", "Caption"]]], [para(f"Figure {len(seen_diagrams)}. {spec['caption']} Solid edges: observed in source; dashed: inferred/unknown. Geometry checked; visual review is separate.")]]})
            if spec["purpose"] == "ordered-flow":
                rows = ["| Step | Interaction | Relation type |", "|---|---|---|"] + [f"| {e['step']} | {cell(e['label'])} | {reg['relations'][e['relation']]['type']} |" for e in sorted(spec["edges"], key=lambda e: e["step"])]
                body.extend(parse("\n".join(rows), engine.root, config)["blocks"])

    for r in roots:
        add_result(r)
    owners = [o for r in results for o in r.get("ownership", [])]
    if progress is not None:
        owners = [o for o in owners if o["subsystem"] in progress["completed"]]
    catalog = ["| Subsystem | Indexed components | Unresolved ownership |", "|---|---:|---:|"]
    subsystems = sorted({o["subsystem"] for o in owners})
    for subsystem in subsystems:
        catalog.append(f"| {cell(subsystem)} | {sum(o['subsystem'] == subsystem for o in owners)} | {sum(o['subsystem'] == subsystem and o['unresolved'] for o in owners)} |")
    if progress is None:
        body.extend(parse("\n".join(catalog), engine.root, config)["blocks"])
    entry_points = [e for r in results for e in r.get("entry_points", [])] if progress is None else []
    if entry_points:
        body.append(heading(2, "Entry points and integrations", "entry-points"))
        rows = ["| Entry / trigger | Declared component | Subsystem | Supported downstream | Evidence / gap |", "|---|---|---|---|---|"]
        for ep in entry_points:
            used_facts.add(ep["fact"])
            rows.append("| " + " | ".join([cell(reg["facts"][ep["fact"]]["statement"]), cell(ep["component"]), cell(ep["subsystem"]), cell(", ".join(reg["relations"][i]["label"] for i in ep["downstream"])), f"[Source](#{ep['fact']}) " + cell(ep["unresolved"])]) + " |")
        body.extend(parse("\n".join(rows), engine.root, config)["blocks"])
    by_subsystem = {}
    for r in authors:
        subsystem = engine.state["tasks"][r["task_id"]]["payload"]["subsystem"]
        by_subsystem.setdefault(subsystem, []).append(r)
    for sub, group in sorted(by_subsystem.items()):
        body.append(heading(1, sub.replace("-", " ").capitalize(), "subsystem-" + sub))
        for r in group:
            add_result(r)
        subset = [o for o in owners if o["subsystem"] == sub]
        if subset:
            body.append(heading(2, "Component index", "index-" + sub))
            rows = ["| Component | Responsibility / ownership |", "|---|---|"]
            for owner in subset:
                used_facts.update(owner["facts"])
                notes = " ".join(f"[Source](#{f})" for f in owner["facts"])
                rows.append(f"| `{cell(owner['path'])}` | {cell(owner['reason'])}{' (unresolved)' if owner['unresolved'] else ''} {notes} |")
            body.extend(parse("\n".join(rows), engine.root, config)["blocks"])
    body.append(heading(1, "Knowledge gaps and coverage", "coverage"))
    status = report["coverage"]
    for key, denominator in (("accepted_analysis_packets", "analysis_packet_denominator"), ("indexed_files", "owner_denominator"), ("semantically_reviewed", "review_denominator")):
        body.append(para(key.replace("_", " ").capitalize() + f": {status[key]} / {status[denominator]}."))
    body.append(para(f"Eligible lines with accepted analysis: {status['accepted_analysis_ranges']['covered_lines']} / {status['eligible_lines']}. Redacted lines: {status['redacted_lines']}. Unresolved ownership: {status['unresolved_owners']}."))
    for limitation in report["limits"]:
        body.append(para(limitation))
    review_limitations = sorted({limit for r in results if r["kind"] == "review" for limit in r["limitations"]})
    for limitation in review_limitations:
        body.append(para("Review limitation: " + limitation))
    body.append(para(f"Review context records: {status['fresh_context_reviews']} fresh; {status['same_context_reviews']} same-context. Context provenance is reported, not independently proven by scripts."))
    body.append(para("Visual QA is recorded after export in preview/preview.json when pages are rendered and inspected; if absent, it is pending. Human approval: not assigned. See coverage.json for full denominators and review context provenance."))
    for fact in (reg["facts"].values() if progress is None else []):
        if fact["status"] == "unknown" or fact["conflicts"]:
            used_facts.add(fact["id"])
            body.append(para(f"{fact['status'].capitalize()}: {fact['statement']} {fact['explanation']}"))
    for r in (results if progress is None else []):
        for conflict in r.get("conflicts", []):
            body.append(para(("Resolved conflict: " if conflict["resolved"] else "Unresolved conflict: ") + conflict["resolution"]))
    excluded = [e for e in engine.state["manifest"]["entries"] if not e["eligible"]]
    if excluded:
        rows = ["| Excluded / unavailable material | Reason |", "|---|---|"] + [f"| `{cell(e['path'])}` | {cell(e['reason'])}; {e['kind']} |" for e in excluded]
        body.extend(parse("\n".join(rows), engine.root, config)["blocks"])
    body.append(heading(1, "Evidence references", "evidence-references"))
    for index, ident in enumerate(sorted(reg["facts"]), 1):
        if ident not in used_facts:
            continue
        fact = reg["facts"][ident]
        sources = "; ".join(f"{reg['evidence'][e]['path']}:{reg['evidence'][e]['start']}-{reg['evidence'][e]['end']}" for e in fact["evidence"])
        body.append({"t": "Div", "c": [[ident, [], [["custom-style", "Source Note"]]], [para(f"[{index}] {ident} · {fact['status']} · {fact['basis']} · {sources or fact['explanation']}")]]})
    # Stable unique heading IDs and visible links; no TOC field/page-number guesses.
    counts = [0] * 6
    heading_map = []
    seen = {"contents"}
    previous_level = 0
    for node in nodes(body):
        if node.get("t") == "Header":
            level, attr, inline = node["c"]
            level = min(level, previous_level + 1)
            node["c"][0] = level
            previous_level = level
            ident = attr[0]
            if ident in seen:
                ident = ident + "-" + str(len(heading_map) + 1)
                attr[0] = ident
            seen.add(ident)
            counts[level - 1] += 1
            counts[level:] = [0] * (6 - level)
            number = ".".join(str(n) for n in counts[:level])
            label = number + " " + " ".join(n.get("c", "") for n in inline if n["t"] == "Str")
            node["c"][2] = [str_(label)]
            if level <= 2:
                heading_map.append((level, ident, label))
    toc = [{"t": "Para", "c": [link_(("    " if level == 2 else "") + label, "#" + ident)]} for level, ident, label in heading_map]
    blocks.extend(toc)
    blocks.extend(body)
    ast["blocks"] = blocks
    ast["meta"] = {"lang": {"t": "MetaString", "c": config["language"]}}
    targets = {n["c"][1][0] for n in nodes(blocks) if n.get("t") == "Header"} | {n["c"][0][0] for n in nodes(blocks) if n.get("t") in ("Div", "Span", "Image")}
    for node in nodes(blocks):
        if node.get("t") == "Link":
            url = node["c"][2][0]
            if url.startswith("#") and url[1:] not in targets:
                raise Failure("Broken internal link: " + url)
    atomic(out / "document.ast.json", ast)
    atomic(out / "evidence-index.json", reg)
    atomic(out / "heading-map.json", [{"level": level, "bookmark": ident, "text": label} for level, ident, label in heading_map])
    return ast, diagram_map


def output_directory(engine):
    output = contained(engine.root, engine.config["output_dir"] + "/" + engine.sid)
    marker = output / ".docgen-owned.json"
    if not marker.exists():
        if output.exists() and any(output.iterdir()):
            raise Failure("Output scope directory is nonempty and not toolkit-owned")
        atomic(marker, {"owner": "generate-documentation", "version": 1})
    elif read_json(marker).get("owner") != "generate-documentation":
        raise Failure("Output directory has another owner")
    return output


def render_document(engine, staging, basename, partial, report, progress=None):
    ast, diagrams = assemble(engine, staging, partial, report, progress)
    pandoc = executable("pandoc", engine.config)
    ref = staging / "reference.docx"
    build_reference(ref, engine.config["branding"])
    args = [pandoc, "--from", "json", str(staging / "document.ast.json")]
    run([*args, "--to", "markdown", "--wrap=none", "-o", str(staging / "documentation.md")], staging, engine.config["timeout"])
    run([*args, "--to", "docx", "--standalone", "--reference-doc", str(ref), "--resource-path", str(staging), "-o", str(staging / (basename + ".docx"))], staging, engine.config["timeout"])
    checks = finish(staging / (basename + ".docx"))
    expected_images = sum(node.get("t") == "Image" for node in nodes(ast))
    if checks["drawings"] != expected_images:
        raise Failure("DOCX is missing one or more expected embedded images", 6)
    return diagrams, pandoc, checks


def chapter_progress(engine):
    """Derive readiness from the active DAG, never from a worker's completion label."""
    tasks = [engine.state["tasks"][i] for i in engine.state["active"]]
    results = {t["id"]: engine.result(t) for t in tasks if t["status"] == "accepted"}
    findings = [f for r in results.values() for f in r.get("findings", []) if f["severity"] == "blocker"]
    owners = [o for r in results.values() for o in r.get("ownership", [])]
    authors = [t for t in tasks if t["kind"] == "write"]
    subsystems = sorted({o["subsystem"] for o in owners} | {t["payload"]["subsystem"] for t in authors})
    missing = set(range_coverage(engine.state["manifest"], [{"chunks": t["chunks"]} for t in tasks if t["kind"] == "analyze" and t["status"] == "accepted"])["missing_files"])
    progress = {"subsystems": [], "completed": [], "writers": [], "reviews": []}
    for subsystem in subsystems:
        writers = [t for t in authors if t["payload"]["subsystem"] == subsystem]
        ids = {t["id"] for t in writers}
        reviews = [t for t in tasks if t["kind"] == "review" and ids.intersection(t["deps"])]
        blockers = [f for t in reviews for f in results.get(t["id"], {}).get("findings", []) if f["severity"] == "blocker"]
        chapter_facts = {u["fact"]["id"] for t in writers for u in t["payload"]["units"]} | {f for t in reviews for f in t["review_facts"]}
        # A later review can challenge shared facts used by an already reviewed chapter.
        blockers.extend(f for f in findings if chapter_facts.intersection(f["facts"]))
        selected_owners = [o for o in owners if o["subsystem"] == subsystem]
        status, reason = "pending", "Writing or required review remains"
        if any(o["unresolved"] or o["path"] in missing for o in selected_owners):
            status, reason = "blocked", "Ownership or accepted source-range coverage is unresolved"
        elif blockers or any(t.get("repair_findings") and t["status"] != "accepted" for t in writers):
            status, reason = "blocked", "Review findings or requested repairs remain"
        elif writers and all(t["status"] == "accepted" for t in writers):
            parts = {t["payload"]["part"] for t in writers}
            all_parts = all(parts == set(range(1, t["payload"]["parts"] + 1)) for t in writers)
            blocks = {b["id"] for t in writers for s in results[t["id"]]["sections"] for b in s["blocks"]}
            blocks |= {d["id"] for t in writers for d in results[t["id"]]["diagrams"]}
            checked = {b for t in reviews for b in results.get(t["id"], {}).get("checked_blocks", [])}
            if all_parts and reviews and all(t["status"] == "accepted" for t in reviews) and blocks <= checked:
                status, reason = "completed", ""
                progress["completed"].append(subsystem)
                progress["writers"].extend(t["id"] for t in writers)
                progress["reviews"].extend(t["id"] for t in reviews)
        progress["subsystems"].append({"subsystem": subsystem, "status": status, "reason": reason})
    return progress


def export_progress(engine):
    """Automatic deterministic export. Caller holds the coordinator lock; final build is untouched."""
    progress = chapter_progress(engine)
    previous = engine.state.get("progress_preview")
    if not progress["completed"]:
        if previous:
            previous["current"] = False
        return
    fingerprint = digest({"progress": progress, "snapshot": engine.state["manifest"]["snapshot"],
                          "artifacts": {i: engine.state["tasks"][i]["accepted_hash"] for i in progress["writers"] + progress["reviews"]},
                          "presentation": code_version(True), "config": engine.config})
    if previous:
        previous["current"] = False
    output = output_directory(engine)
    destination = contained(output, "documentation-progress.docx")
    if previous and previous["fingerprint"] == fingerprint and destination.is_file() and digest(destination.read_bytes()) == previous["docx_hash"]:
        previous["current"] = True
        engine.state["progress_error"] = None
        return
    report = engine.validate()
    if not report["integrity_valid"]:
        raise Failure("Progress export blocked by saved-content validation: " + "; ".join(report["issues"]), 6)
    staging = Path(tempfile.mkdtemp(prefix=".building-progress-", dir=output))
    try:
        diagrams, pandoc, checks = render_document(engine, staging, "documentation-progress", True, report, progress)
        # Recheck after rendering as external tools can take time; never publish a stale draft.
        engine.validate_saved()
        atomic(staging / "progress.json", progress)
        atomic(staging / "coverage.json", report)
        atomic(staging / "QUALITY.md", "# Progress preview quality\n\nIncomplete draft. Only completed, validated and reviewed subsystem chapters are included. Final-export gates remain separate.\n\nVisual QA: pending. Human approval: not assigned.\n\nSee progress.json for completed/pending/blocked subsystems and coverage.json for whole-scope denominators.\n")
        metadata = {"version": 1, "kind": "incremental", "snapshot": engine.state["manifest"]["snapshot"],
                    "fingerprint": fingerprint, "partial": True, "validation": "included chapters only",
                    "docx_checks": checks, "diagrams": diagrams, "visual_qa": "pending", "human_approval": "not-assigned",
                    "pandoc": run([pandoc, "--version"], staging).splitlines()[0]}
        metadata["files"] = {p.relative_to(staging).as_posix(): digest(p.read_bytes()) for p in staging.rglob("*") if p.is_file()}
        atomic(staging / "build.json", metadata)
        # A unique completed directory preserves diagram originals and previous successful builds.
        target = output / ("progress-build-" + staging.name.removeprefix(".building-progress-"))
        staging.rename(target)
        content = (target / "documentation-progress.docx").read_bytes()
        # Same-directory atomic replacement: renderer, finishing or file-lock failures retain the old preview.
        atomic(destination, content)
        engine.state["progress_preview"] = {"docx": str(destination), "directory": str(target), "docx_hash": digest(content),
                                            "fingerprint": fingerprint, "snapshot": engine.state["manifest"]["snapshot"], "current": True,
                                            "subsystems": {status: sum(s["status"] == status for s in progress["subsystems"]) for status in ("completed", "pending", "blocked")},
                                            "visual_qa": "pending", "human_approval": "not-assigned"}
        engine.state["progress_error"] = None
    except Exception:
        if staging.exists():
            atomic(staging / "FAILED.txt", "Progress export failed; the previous successful preview was not replaced.\n")
        raise


def export(engine, partial=False):
    with lock(engine.home):
        engine.reload()
        report = engine.validate()
        if not report["valid"] and not partial:
            raise Failure("Strict export blocked: " + "; ".join(report["issues"]), 6)
        # Partial permits missing work, never stale/corrupt evidence.
        engine.verify_sources()
        if any("Stale" in x or "snapshot changed" in x or "changed" in x or "Schema:" in x for x in report["issues"]):
            raise Failure("Partial export cannot bypass stale/corrupt artifacts. Rescan and repair first.", 5)
        output = output_directory(engine)
        staging = Path(tempfile.mkdtemp(prefix=".building-", dir=output))
        try:
            basename = "DRAFT-INCOMPLETE" if partial else "documentation"
            diagrams, pandoc, checks = render_document(engine, staging, basename, partial, report)
            atomic(staging / "coverage.json", report)
            atomic(staging / "QUALITY.md", "# Quality report\n\n" + ("DRAFT INCOMPLETE\n\n" if partial else "Strict mechanical validation passed.\n\n") + "\n".join("- " + x for x in report["limits"]) + "\n\nVisual QA: pending. Human approval: not assigned.\n\nSee coverage.json for explicit inventory, source range, packet, index and review denominators.\n")
            metadata = {"version": 1, "snapshot": engine.state["manifest"]["snapshot"], "partial": partial, "validation": report["valid"], "docx_checks": checks, "diagrams": diagrams, "visual_qa": "pending", "human_approval": "not-assigned", "pandoc": run([pandoc, "--version"], staging).splitlines()[0]}
            metadata["files"] = {p.relative_to(staging).as_posix(): digest(p.read_bytes()) for p in staging.rglob("*") if p.is_file()}
            atomic(staging / "build.json", metadata)
            name = "build-" + digest({"files": metadata["files"], "snapshot": metadata["snapshot"]})[:12]
            target = output / name
            index = 1
            while target.exists():
                index += 1
                target = output / (name + "-" + str(index))
            staging.rename(target)
            build = {"directory": str(target), "docx": str(target / (basename + ".docx")), "markdown": str(target / "documentation.md"), "visual_qa": "pending", "partial": partial, "validation": report["valid"], "docx_checks": checks}
            engine.state["build"] = build
            engine.save()
            return build
        except Exception:
            # Keep failure evidence local; no successful build pointer is assigned.
            atomic(staging / "FAILED.txt", "Export failed. This directory is not a completed document build.\n")
            raise


def preview(engine):
    build = engine.state.get("build")
    if not build:
        raise Failure("Export a document first")
    soffice = executable("soffice", engine.config)
    try:
        renderer = executable("pdftoppm", engine.config)
    except Failure:
        if engine.config["executables"]["pdftoppm"]:
            raise
        renderer = None
        try:
            import pymupdf
        except ImportError as exc:
            raise Failure("Preview needs pdftoppm or the optional PyMuPDF renderer. Run setup.py --preview explicitly.", 3) from exc
    path = Path(build["docx"])
    output = path.parent / "preview"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docgen-preview-") as tmp:
        temp = Path(tmp)
        run([soffice, "-env:UserInstallation=" + (temp / "profile").as_uri(), "--headless", "--convert-to", "pdf", "--outdir", str(temp), str(path)], temp, engine.config["timeout"], binary=True)
        pdf = temp / (path.stem + ".pdf")
        if not pdf.exists() or pdf.stat().st_size < 100:
            raise Failure("LibreOffice did not produce a PDF", 3)
        shutil.copyfile(pdf, output / pdf.name)
        if renderer:
            run([renderer, "-png", "-r", "110", str(pdf), str(output / "page")], temp, engine.config["timeout"])
        else:
            with pymupdf.open(pdf) as document:
                for index, page in enumerate(document, 1):
                    page.get_pixmap(dpi=110).save(output / f"page-{index:03d}.png")
    pages = sorted(output.glob("page-*.png"))
    if not pages:
        raise Failure("PDF renderer produced no page images", 3)
    atomic(output / "preview.json", {"docx_hash": digest(path.read_bytes()), "pages": [p.name for p in pages], "rendered": True, "image_review": "pending", "human_approval": "not-assigned"})
    build["visual_qa"] = "rendered-images-await-inspection"
    engine.save()
    return {"preview": str(output), "pages": len(pages), "visual_qa": build["visual_qa"], "instruction": "Inspect every page. Record clipping, tables, diagram labels, Unicode, contents and links separately; rendering alone is not visual QA."}


def record_layout(engine, pages, reviewer, notes):
    build = engine.state.get("build")
    if not build:
        raise Failure("Export and preview before recording image inspection")
    path = Path(build["docx"])
    output = path.parent / "preview"
    record = read_json(output / "preview.json")
    if record["docx_hash"] != digest(path.read_bytes()):
        raise Failure("DOCX changed after preview; render it again", 5)
    expected = set(range(1, len(record["pages"]) + 1))
    if not pages or not set(pages) <= expected or len(pages) != len(set(pages)):
        raise Failure("Supply unique inspected page numbers from the current preview")
    record.update(inspected_pages=sorted(pages), reviewer=reviewer, notes=notes,
                  image_review="all-pages-inspected" if set(pages) == expected else "partially-inspected", human_approval="not-assigned")
    atomic(output / "preview.json", record)
    build["visual_qa"] = record["image_review"]
    metadata = read_json(path.parent / "build.json")
    metadata.update(visual_qa=record["image_review"], layout_review=record)
    quality = path.parent / "QUALITY.md"
    text = quality.read_text("utf-8").replace("Visual QA: pending.", "Visual QA: " + record["image_review"] + ".")
    atomic(quality, text)
    metadata["files"]["QUALITY.md"] = digest(quality.read_bytes())
    atomic(path.parent / "build.json", metadata)
    engine.save()
    return record
