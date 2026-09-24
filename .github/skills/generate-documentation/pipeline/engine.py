"""Single-writer checkpointed DAG. Model text is data, never executable code."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import secrets
import time

from .common import Failure, SKILL, atomic, code_version, contained, digest, load_config, lock, read_json, scope_id, tokens
from .contracts import check_source, registry, schema, validate_result
from .inventory import exclusion, packets, range_coverage, redact, scan, source


class Engine:
    def __init__(self, root, scope=None):
        self.root = Path(root).resolve()
        self.config = load_config(self.root, scope)
        self.sid = scope_id(self.config)
        self.base = contained(self.root, self.config["state_dir"])
        self.home = contained(self.root, self.config["state_dir"] + "/runs/" + self.sid)
        self.state_path = self.home / "state.json"
        self.state = read_json(self.state_path) if self.state_path.exists() else None
        if self.state and (self.state.get("version") != 1 or self.state.get("root") != str(self.root)):
            raise Failure("Run state version/root does not match. Copy only the skill, not .docgen state.")

    def save(self):
        atomic(self.state_path, self.state)

    def reload(self):
        if self.state_path.exists():
            self.state = read_json(self.state_path)

    def task_dir(self, task_id):
        return contained(self.home, "tasks/" + task_id)

    def owned(self):
        marker = self.base / ".docgen-owned.json"
        if not marker.exists():
            if self.base.exists() and any(self.base.iterdir()):
                raise Failure(f"Refusing to adopt nonempty state directory {self.base}")
            atomic(marker, {"owner": "generate-documentation", "version": 1})
        elif read_json(marker).get("owner") != "generate-documentation":
            raise Failure("State directory has another owner")

    def session(self, value, recover=False):
        current = self.state.get("coordinator")
        if current and current["token"] != value and not recover:
            raise Failure("Another coordinator owns this run. Resume with its --session token, or after stopping it use prepare --recover. Never run two chats on one scope.", 4)
        if recover or not current:
            current = {"token": secrets.token_hex(16), "started": time.time()}
            self.state["coordinator"] = current
            for t in self.state["tasks"].values():
                if t.get("status") == "leased":
                    t["status"] = "pending"
        current["heartbeat"] = time.time()
        return current["token"]

    def prepare(self, session=None, recover=False):
        for scope in self.config["scope"]:
            if not contained(self.root, scope).exists():
                raise Failure(f"Scope path does not exist: {scope}")
        self.owned()
        with lock(self.home):
            self.reload()
            old = self.state
            if old is None:
                self.state = {"version": 1, "root": str(self.root), "scope_id": self.sid, "tasks": {}, "active": [], "build": None}
            token = self.session(session, recover)
            manifest = scan(self.root, self.config)
            package, errors = packets(self.root, manifest, self.config)
            previous = self.state.get("manifest", {})
            before = {e["path"]: e.get("hash") for e in previous.get("entries", [])}
            after = {e["path"]: e.get("hash") for e in manifest["entries"]}
            changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k) or (k in before) != (k in after))
            self.state.update(manifest=manifest, packets=package, packet_errors=errors, config=self.config,
                              analysis_version=code_version(), presentation_version=code_version(True))
            self.state["last_rescan"] = {"changed_paths": changed, "impact": "Source packet discovery/extraction reused by fingerprint; all reconciliation and downstream content invalidated on any analysis change because dynamic/shared contract impact cannot be proven precisely."}
            if changed or previous.get("snapshot") != manifest["snapshot"]:
                self.state["build"] = None
            # Validate cached payload integrity and source references before reuse.
            for task in self.state["tasks"].values():
                if task.get("status") == "accepted":
                    try:
                        self.result(task)
                        for ref in self.allowed(task):
                            check_source(self.root, ref, [ref])
                    except Failure:
                        task["status"] = "invalid"
                        task["extra"] = []
                        task["payload"].pop("lookups", None)
            self.refresh()
            self.save()
            atomic(self.home / "manifest.json", manifest)
            self.update_progress()
            return {**self.status(), "session": token, "changed_paths": len(changed), "resume": f"/generate-documentation scope={','.join(self.config['scope'])}"}

    def result(self, task):
        p = self.task_dir(task["id"]) / "accepted.json"
        raw = p.read_bytes() if p.exists() else b""
        if digest(raw) != task.get("accepted_hash"):
            raise Failure(f"Accepted artifact changed or missing: {task['id']}; run prepare --recover")
        data = read_json(p)
        schema(data)
        return data

    def results(self):
        return [self.result(self.state["tasks"][i]) for i in self.state["active"] if self.state["tasks"][i]["status"] == "accepted"]

    def complete(self, ids):
        return all(self.state["tasks"][i]["status"] == "accepted" for i in ids)

    def add(self, kind, data, deps=(), content_deps=None, **extra):
        semantic_config = {k: self.config[k] for k in ("scope", "exclude", "prune_dirs", "exclude_generated_headers", "language", "audience", "source_tokens", "packet_tokens", "result_tokens", "summary_tokens", "max_nodes", "repair_cycles")}
        dep_hashes = {i: self.state["tasks"][i].get("accepted_hash") for i in deps}
        fingerprint = digest({"kind": kind, "data": data, "deps": dep_hashes, "version": self.state["analysis_version"], "config": semantic_config})
        ident = kind[:2] + "-" + fingerprint[:20]
        old = self.state["tasks"].get(ident)
        task = old or {"id": ident, "kind": kind, "input_fingerprint": fingerprint, "snapshot": self.state["manifest"]["snapshot"], "status": "pending", "cycles": 0, "extra": [], "payload": data, "deps": list(deps), "dependency_hashes": dep_hashes, "content_deps": list(content_deps if content_deps is not None else deps), **extra}
        if old and any(self.state["tasks"].get(i, {}).get("accepted_hash") != h or self.state["tasks"].get(i, {}).get("status") != "accepted" for i, h in task.get("lookup_deps", {}).items()):
            task.update(status="invalid", lookup_deps={}, deps=list(deps), dependency_hashes=dep_hashes, payload=data)
            task.pop("accepted_hash", None)
            task["invalidated_reason"] = "A bounded lookup dependency changed; its result must be reconsidered"
        if task["status"] == "invalid":
            task["status"] = "pending"
            task["input_fingerprint"] = fingerprint
        if task["status"] != "accepted":
            task["snapshot"] = self.state["manifest"]["snapshot"]
        self.state["tasks"][ident] = task
        self.state["active"].append(ident)
        return ident

    def chunks_for(self, facts, reg):
        evidence = {e for f in facts for e in reg["facts"][f]["evidence"]}
        out = []
        for ident in sorted(evidence):
            e = reg["evidence"][ident]
            check_source(self.root, e, [e])
            lines = source(self.root, e)
            out.append({**{k: v for k, v in e.items() if k != "snippet"}, "text": "\n".join(lines[max(0, e["start"] - 1):e["end"]])})
        return out

    def groups(self, items, reserve=2400, kind="write"):
        groups, group = [], []
        budget = self.config["packet_tokens"] - max(reserve, self.overhead(kind) + 1800)
        for item in items:
            if tokens([item]) > budget:
                origin = (item.get("fact") or item.get("block") or item.get("diagram") or item).get("id", item.get("task", "unknown"))
                raise Failure(f"Dependency unit {origin} exceeds packet_tokens. Use repair on its originating task with --reason describing this budget failure; narrow evidence or split the block. Raising an explicit budget is also possible within limits.", 6)
            if group and tokens(group + [item]) > budget:
                groups.append(group)
                group = []
            group.append(item)
        if group:
            groups.append(group)
        return groups

    def reviews(self, writer_ids):
        out = []
        reg = registry(self.results())
        for wid in writer_ids:
            if not self.complete([wid]):
                continue
            result = self.result(self.state["tasks"][wid])
            units = []
            for sec in result["sections"]:
                for block in sec["blocks"]:
                    facts = block["facts"]
                    units.append({"block": block, "section": sec["title"], "facts": [reg["facts"][i] for i in facts], "sources": self.chunks_for(facts, reg)})
            for diagram in result["diagrams"]:
                facts = sorted(set(diagram["facts"]) | {f for n in diagram["nodes"] for f in n["facts"]} | {f for e in diagram["edges"] for f in reg["relations"][e["relation"]]["facts"]})
                units.append({"diagram": diagram, "facts": [reg["facts"][i] for i in facts], "sources": self.chunks_for(facts, reg), "relations": [reg["relations"][e["relation"]] for e in diagram["edges"]]})
            for group in self.groups(units, kind="review"):
                block_ids = [(u.get("block") or u.get("diagram"))["id"] for u in group]
                fact_ids = sorted({f["id"] for u in group for f in u["facts"]})
                out.append(self.add("review", {"units": group}, [wid], review_blocks=block_ids, review_facts=fact_ids))
        return out

    def refresh(self):
        self.state["active"] = []
        analyses = []
        for packet in self.state["packets"]:
            d = self.add("discover", {"chunks": packet["chunks"]}, chunks=packet["chunks"])
            if self.complete([d]):
                a = self.add("analyze", {"chunks": packet["chunks"], "proposals": self.result(self.state["tasks"][d])["proposals"]}, [d], chunks=packet["chunks"])
                analyses.append(a)
        if len(analyses) != len(self.state["packets"]) or not self.complete(analyses) or not analyses:
            return
        # Each path gets exactly one reconciliation owner, even when a large file spans packets.
        claimed, recon = set(), []
        for a in analyses:
            task = self.state["tasks"][a]
            paths = sorted({c["path"] for c in task["chunks"]} - claimed)
            claimed.update(paths)
            result = self.result(task)
            recon.append(self.add("reconcile", {"analysis": result, "owner_paths": paths, "lookup": "Use lookup for bounded accepted facts; request evidence for targeted source checks. Reconcile subsystem naming using prior accepted ownership shards."}, analyses, [a], owner_paths=paths))
        if not self.complete(recon):
            return
        reg = registry(self.results())
        ownership = {o["path"]: o for i in recon for o in self.result(self.state["tasks"][i])["ownership"]}
        by_owner = defaultdict(list)
        for fact in reg["facts"].values():
            paths = [reg["evidence"][e]["path"] for e in fact["evidence"]]
            owner = next((ownership[p]["subsystem"] for p in paths if p in ownership), "unresolved")
            relations = [r for r in reg["relations"].values() if fact["id"] in r["facts"]]
            by_owner[owner].append({"fact": fact, "sources": self.chunks_for([fact["id"]], reg), "relations": relations})
        writers = []
        for owner, units in sorted(by_owner.items()):
            groups = self.groups(units)
            for part, group in enumerate(groups, 1):
                writers.append(self.add("write", {"subsystem": owner, "part": part, "parts": len(groups), "units": group}, recon))
        reviews = self.reviews(writers)
        if not self.complete(writers) or not self.complete(reviews) or self.blockers(reviews):
            return
        current = writers
        level = 0
        while current:
            summaries = [{"task": i, "summary": self.result(self.state["tasks"][i])["summary"], "artifact": str(self.task_dir(i) / "accepted.json")} for i in current]
            groups = self.groups(summaries, reserve=5000, kind="synthesize")
            parents = [self.add("synthesize", {"level": level, "summaries": group, "root": len(groups) == 1}, [x["task"] for x in group] + reviews, [x["task"] for x in group]) for group in groups]
            r = self.reviews(parents)
            if not self.complete(parents) or not self.complete(r) or self.blockers(r):
                return
            if len(parents) == 1:
                self.state["overview"] = parents[0]
                return
            if len(parents) >= len(current):
                raise Failure("Summary hierarchy did not shrink; shorten summaries/fact ID selection before continuing", 6)
            current, reviews, level = parents, r, level + 1

    def blockers(self, task_ids=None):
        return [f for i in (task_ids if task_ids is not None else self.state["active"]) if self.state["tasks"][i]["status"] == "accepted" for f in self.result(self.state["tasks"][i]).get("findings", []) if f["severity"] == "blocker"]

    def allowed(self, task):
        chunks = list(task.get("chunks", [])) + task.get("extra", [])

        def visit(value):
            if isinstance(value, dict):
                if all(k in value for k in ("path", "hash", "start", "end")):
                    chunks.append(value)
                for v in value.values():
                    visit(v)
            elif isinstance(value, list):
                for v in value:
                    visit(v)
        visit(task["payload"])
        return chunks

    def verify_sources(self, task=None):
        entries = self.allowed(task) if task else [e for e in self.state["manifest"]["entries"] if e["eligible"]]
        for e in entries:
            try:
                raw = contained(self.root, e["path"]).read_bytes()
            except OSError as exc:
                raise Failure(f"Source unavailable: {e['path']}; rescan required", 5) from exc
            if digest(raw) != e["hash"]:
                raise Failure(f"Source changed: {e['path']}; result rejected. Run prepare to requeue affected work.", 5)

    def overhead(self, kind):
        return sum(tokens((SKILL / path).read_text("utf-8")) for path in ("tasks/" + kind + ".md", "tasks/common.md", "schemas/" + kind + ".schema.json"))

    def packet(self, task):
        instruction = SKILL / "tasks" / (task["kind"] + ".md")
        packet = {"contract_version": 1, "task_id": task["id"], "kind": task["kind"], "snapshot": task["snapshot"], "input_fingerprint": task["input_fingerprint"],
                  "output": str(self.task_dir(task["id"]) / "result.json"), "schema": str(SKILL / ("schemas/" + task["kind"] + ".schema.json")), "instructions": str(instruction),
                  "common_instructions": str(SKILL / "tasks/common.md"), "language": self.config["language"], "audience": self.config["audience"],
                  "result_token_ceiling": self.config["result_tokens"], "summary_token_ceiling": self.config["summary_tokens"],
                  "diagram_node_ceiling": self.config["max_nodes"],
                  "review_blocks": task.get("review_blocks", []), "review_facts": task.get("review_facts", []),
                  "data": task["payload"], "registered_extra_sources": task.get("extra", []), "repair_findings": task.get("repair_findings", [])}
        overhead = self.overhead(task["kind"])
        if tokens(packet) + overhead > self.config["packet_tokens"]:
            raise Failure(f"{task['id']} exceeds total packet budget including task instructions/schema reserve. Reduce facts/source_tokens or explicitly adjust packet_tokens.", 6)
        return packet

    def next(self, session):
        with lock(self.home):
            self.reload()
            self.session(session)
            if self.state["analysis_version"] != code_version():
                raise Failure("Toolkit instructions/schema changed; run prepare before continuing", 5)
            self.verify_sources()
            self.refresh()
            self.update_progress()
            for ident in self.state["active"]:
                task = self.state["tasks"][ident]
                if task["status"] in ("pending", "leased") and self.complete(task["deps"]):
                    packet = self.packet(task)
                    path = self.task_dir(ident) / "packet.json"
                    atomic(path, packet)
                    task["status"] = "leased"
                    task["delivered"] = True
                    self.save()
                    return {"task_id": ident, "kind": task["kind"], "packet": str(path), "result": packet["output"], "estimated_input_tokens": tokens(packet) + self.overhead(task["kind"]), "receipt_only": True, "existing_result": Path(packet["output"]).exists(), "progress_preview": self.state.get("progress_preview"), "progress_error": self.state.get("progress_error")}
            self.save()
            return {"task": None, **self.status()}

    def accept(self, task_id, session):
        with lock(self.home):
            self.reload()
            self.session(session)
            if task_id not in self.state["active"]:
                raise Failure("Task is not in the active DAG")
            task = self.state["tasks"][task_id]
            if task["status"] == "accepted":
                self.update_progress(refresh=True)
                return {"accepted": task_id, "reused": True, "progress_preview": self.state.get("progress_preview"), "progress_error": self.state.get("progress_error")}
            if task["status"] != "leased" or not self.complete(task["deps"]):
                raise Failure("Task was not issued or has incomplete dependencies")
            if any(self.state["tasks"][i].get("accepted_hash") != h for i, h in task.get("dependency_hashes", {}).items()):
                raise Failure("Task dependency acceptance changed; reissue the task", 5)
            try:
                self.verify_sources(task)
                self.verify_sources()  # conservative shared-contract freshness barrier
            except Failure:
                task["status"] = "pending"
                self.save()
                raise
            output = contained(self.task_dir(task_id), "result.json")
            if output.stat().st_size > self.config["result_tokens"] * 12:
                raise Failure("Result file is larger than the bounded artifact limit; split content, do not dump inventories")
            result = read_json(output)
            reg = validate_result(self.root, self.config, task, result, self.results(), self.state["manifest"], self.allowed(task))
            if task["kind"] in ("write", "synthesize"):
                from .render import check_markdown
                for s in result["sections"]:
                    for block in s["blocks"]:
                        check_markdown(block, self.root, self.config, reg)
                if task["kind"] == "write":
                    assigned = {u["fact"]["id"] for u in task["payload"]["units"]}
                    represented = {f for s in result["sections"] for b in s["blocks"] for f in b["facts"]}
                    if not assigned <= represented:
                        raise Failure("Writing omitted assigned fact IDs; represent them concisely or record their uncertainty")
                    if any(s["subsystem"] != task["payload"]["subsystem"] for s in result["sections"]):
                        raise Failure("Sections must retain the assigned subsystem")
            # Worker output is copied into an immutable accepted artifact before state commits.
            dest = self.task_dir(task_id) / "accepted.json"
            atomic(dest, result)
            task.update(status="accepted", accepted_hash=digest(dest.read_bytes()))
            self.state["build"] = None
            self.save()
            if task["kind"] == "review":
                self.update_progress(refresh=True)
            return {"accepted": task_id, "kind": task["kind"], "semantic_claim": "schema/evidence integrity only; semantic review is a separate task", "progress_preview": self.state.get("progress_preview"), "progress_error": self.state.get("progress_error")}

    def update_progress(self, refresh=False):
        """Called with the coordinator lock held; never roll back accepted work on export failure."""
        try:
            if refresh:
                self.refresh()
            from .render import export_progress
            export_progress(self)
        except Exception as exc:
            self.state["progress_error"] = type(exc).__name__ + ": " + str(exc) + "; last successful progress preview preserved. Retry with next after correcting the cause."
        self.save()

    def repair(self, task_id, session, reason=None):
        with lock(self.home):
            self.reload()
            self.session(session)
            task = self.state["tasks"].get(task_id)
            if not task or task_id not in self.state["active"] or task["kind"] not in ("analyze", "reconcile", "write", "synthesize"):
                raise Failure("Repair requires an active analysis, reconciliation or authoring task")
            if task["cycles"] >= self.config["repair_cycles"]:
                raise Failure("Repair cycle limit reached. Remaining issue is blocked; report it or explicitly request partial export.", 6)
            findings = [f for i in self.state["active"] if self.state["tasks"][i]["kind"] == "review" and task_id in self.state["tasks"][i]["deps"] and self.state["tasks"][i]["status"] == "accepted" for f in self.result(self.state["tasks"][i])["findings"]]
            if task["kind"] in ("analyze", "reconcile"):
                affected = {f["id"] for f in (self.result(task).get("facts", []) if task["kind"] == "analyze" else task["payload"]["analysis"]["facts"])}
                findings = [f for f in self.blockers() if affected & set(f["facts"])]
            if not findings:
                if not reason or not reason.strip():
                    raise Failure("No accepted review findings to repair. For a mechanical/budget correction, supply a concrete --reason.")
                findings = [{"id": "mechanical-correction", "severity": "blocker", "message": reason.strip(), "blocks": [], "facts": [], "evidence": []}]
            task["cycles"] += 1
            task["repair_findings"] = findings
            if task["status"] == "accepted":
                atomic(self.task_dir(task_id) / f"revision-{task['cycles']}.json", self.result(task))
            task["status"] = "pending"
            task.pop("accepted_hash", None)
            # Removing this acceptance changes downstream input fingerprints on refresh.
            self.refresh()
            self.save()
            self.update_progress()
            return {"repair": task_id, "cycle": task["cycles"]}

    def evidence(self, task_id, path, start, end, session):
        with lock(self.home):
            self.reload()
            self.session(session)
            task = self.state["tasks"].get(task_id)
            if not task or task_id not in self.state["active"] or task["status"] != "leased":
                raise Failure("Extra evidence requires a currently leased task")
            if exclusion(path, self.config):
                raise Failure("Excluded/credential/toolkit files cannot enter model packets")
            raw = contained(self.root, path).read_bytes()
            if b"\0" in raw:
                raise Failure("Cannot register binary source")
            lines, redactions = redact(raw.decode("utf-8-sig", "strict"))
            ref = {"path": path, "hash": digest(raw), "start": start, "end": end}
            check_source(self.root, ref, [ref])
            ref.update(text="\n".join(lines[max(0, start - 1):end]), external_to_scope=not any(e["path"] == path and e["eligible"] for e in self.state["manifest"]["entries"]), redacted_lines=redactions)
            task["extra"].append(ref)
            task["input_fingerprint"] = digest([task["input_fingerprint"], ref])
            packet = self.packet(task)
            atomic(self.task_dir(task_id) / "packet.json", packet)
            self.save()
            return {"registered": path, "external_to_scope": ref["external_to_scope"], "packet": str(self.task_dir(task_id) / "packet.json"), "input_fingerprint": task["input_fingerprint"]}

    def lookup(self, query, limit=10, task_id=None, session=None):
        reg = registry(self.results())
        matches = [{"kind": kind, "id": ident, "artifact": str(self.task_dir(ident.split('.')[0]) / "accepted.json")} for kind, values in reg.items() for ident, value in values.items() if query in ident or query.casefold() in json.dumps(value, ensure_ascii=False).casefold()]
        if task_id:
            with lock(self.home):
                self.reload()
                self.session(session)
                task = self.state["tasks"].get(task_id)
                if not task or task_id not in self.state["active"] or task["status"] != "leased":
                    raise Failure("Lookup attachment requires a leased active task")
                picked = matches[:limit]
                records = [reg[m["kind"]][m["id"]] for m in picked]
                fact_ids = {m["id"] for m in picked if m["kind"] == "facts"}
                fact_ids |= {f for m in picked if m["kind"] in ("relations", "blocks", "diagrams", "ownership") for f in reg[m["kind"]][m["id"]].get("facts", [])}
                sources = self.chunks_for(sorted(fact_ids), reg)
                task["payload"].setdefault("lookups", []).append({"query": query, "records": records, "facts": [reg["facts"][i] for i in sorted(fact_ids)], "sources": sources})
                task["input_fingerprint"] = digest([task["input_fingerprint"], records, sources])
                for match in picked:
                    publisher = match["id"].split(".")[0]
                    if publisher != task_id:
                        accepted_hash = self.state["tasks"][publisher]["accepted_hash"]
                        task.setdefault("lookup_deps", {})[publisher] = accepted_hash
                        task.setdefault("dependency_hashes", {})[publisher] = accepted_hash
                        if publisher not in task["deps"]:
                            task["deps"].append(publisher)
                packet = self.packet(task)
                atomic(self.task_dir(task_id) / "packet.json", packet)
                self.save()
        return {"matches": matches[:limit], "total": len(matches), "remaining": max(0, len(matches) - limit), "attached_to": task_id, "instruction": "To read facts/source, use lookup --task with the coordinator session; it attaches bounded records and updates the packet fingerprint. Search receipts alone are not source analysis."}

    def status(self):
        if not self.state:
            return {"scope_id": self.sid, "initialized": False}
        tasks = [self.state["tasks"][i] for i in self.state["active"]]
        accepted = [t for t in tasks if t["status"] == "accepted"]
        results = [self.result(t) for t in accepted]
        accepted_packets = [{"chunks": t["chunks"]} for t in accepted if t["kind"] == "analyze"]
        delivered = [{"chunks": t["chunks"]} for t in tasks if t["kind"] == "analyze" and t.get("delivered")]
        owners = [o for r in results for o in r.get("ownership", [])]
        blocks = [b["id"] for r in results for s in r.get("sections", []) for b in s["blocks"]] + [d["id"] for r in results for d in r.get("diagrams", [])]
        reviewed = {b for r in results for b in r.get("checked_blocks", [])}
        eligible = [e for e in self.state["manifest"]["entries"] if e["eligible"]]
        complete = bool(self.state.get("overview") in self.state["active"] and tasks and all(t["status"] == "accepted" for t in tasks) and not self.blockers())
        facts = {f["id"] for r in results for f in r.get("facts", [])}
        represented = {f for r in results for s in r.get("sections", []) for b in s["blocks"] for f in b["facts"]}
        def compact_ranges(packet_list):
            coverage = range_coverage(self.state["manifest"], packet_list)
            coverage["missing_file_count"] = len(coverage["missing_files"])
            coverage["missing_files"] = coverage["missing_files"][:10]
            coverage["missing_files_are_sample"] = coverage["missing_file_count"] > 10
            return coverage
        return {"scope_id": self.sid, "snapshot": self.state["manifest"]["snapshot"], "state": str(self.home), "task_counts": dict(Counter(t["status"] for t in tasks)),
                "pipeline_complete": complete, "inventory_entries": len(self.state["manifest"]["entries"]), "eligible_files": len(eligible),
                "inventory_file_records": sum(e["kind"] not in ("excluded-directory", "unreadable-directory") for e in self.state["manifest"]["entries"]),
                "directory_exclusion_records": sum(e["kind"] == "excluded-directory" for e in self.state["manifest"]["entries"]),
                "freshness_notice": "Task completion describes the recorded snapshot; run validate to recheck current sources, additions and dependencies.",
                "eligible_lines": sum(e["lines"] for e in eligible), "excluded_or_unavailable_entries": dict(Counter(e["kind"] for e in self.state["manifest"]["entries"] if not e["eligible"])),
                "planned_ranges": compact_ranges(self.state["packets"]), "delivered_ranges": compact_ranges(delivered), "accepted_analysis_ranges": compact_ranges(accepted_packets),
                "accepted_analysis_packets": sum(t["kind"] == "analyze" for t in accepted), "analysis_packet_denominator": len(self.state["packets"]),
                "indexed_files": len({o["path"] for o in owners}), "unresolved_owners": sum(o["unresolved"] for o in owners), "owner_denominator": len(eligible),
                "accepted_blocks_and_diagrams": len(blocks), "semantically_reviewed": len(set(blocks) & reviewed), "review_denominator": len(blocks),
                "represented_facts": len(facts & represented), "fact_denominator": len(facts), "unknown_facts": sum(f["status"] == "unknown" for r in results for f in r.get("facts", [])),
                "fresh_context_reviews": sum(r.get("context") in ("fresh-subagent", "fresh-chat") for r in results), "same_context_reviews": sum(r.get("context") == "same-context" for r in results),
                "blocking_findings": len(self.blockers()), "redacted_lines": sum(len(e.get("redacted_lines", [])) for e in eligible),
                "visual_qa": (self.state.get("build") or {}).get("visual_qa", "pending"), "human_approval": "not-assigned", "build": self.state.get("build"),
                "progress_preview": self.state.get("progress_preview"), "progress_error": self.state.get("progress_error"),
                "resume": "/generate-documentation" + (" scope=" + ",".join(self.config["scope"]) if self.config["scope"] != ["."] else "")}

    def validate_saved(self):
        """Integrity gate shared by final and incremental exports; does not require all tasks."""
        self.verify_sources()
        if code_version() != self.state["analysis_version"]:
            raise Failure("Toolkit extraction contracts changed; prepare required")
        if any(self.config[k] != self.state["config"][k] for k in ("language", "audience", "source_tokens", "packet_tokens", "result_tokens", "summary_tokens", "max_nodes", "repair_cycles")):
            raise Failure("Analysis configuration changed; prepare required")
        current = scan(self.root, self.config)
        if current["snapshot"] != self.state["manifest"]["snapshot"]:
            raise Failure("Inventory/source snapshot changed (including additions/deletions); prepare required", 5)
        results = self.results()
        registry(results)
        accepted_so_far = []
        for ident in self.state["active"]:
            task = self.state["tasks"][ident]
            if task["status"] != "accepted":
                continue
            if not self.complete(task["deps"]):
                raise Failure("Incomplete dependency for " + ident)
            if any(self.state["tasks"][i].get("accepted_hash") != h for i, h in task.get("dependency_hashes", {}).items()):
                raise Failure("Changed accepted dependency for " + ident)
            result = self.result(task)
            # Cross-shard facts may reference a later shard via bounded lookup.
            others = [r for r in results if r["task_id"] != ident]
            validate_result(self.root, self.config, task, result, others, self.state["manifest"], self.allowed(task))
            accepted_so_far.append(result)
        owners = [o["path"] for r in results for o in r.get("ownership", [])]
        if len(owners) != len(set(owners)):
            raise Failure("Duplicate primary ownership")

    def validate(self):
        issues = []
        try:
            self.validate_saved()
        except (Failure, OSError, ValueError) as exc:
            issues.append(str(exc))
        integrity_valid = not issues
        status = self.status()
        if not status["pipeline_complete"]:
            issues.append("Required analysis/authoring/review tasks are incomplete or blocked")
        if status["planned_ranges"]["missing_files"] or status["accepted_analysis_ranges"]["missing_files"]:
            issues.append("Eligible source ranges lack accepted analysis")
        if status["indexed_files"] != status["owner_denominator"]:
            issues.append("Eligible files lack primary ownership/index placement")
        if status["semantically_reviewed"] != status["review_denominator"]:
            issues.append("Accepted content has unreviewed blocks/diagrams")
        if status["represented_facts"] != status["fact_denominator"]:
            issues.append("Accepted facts lack chapter/index representation")
        unavailable = [e["path"] for e in self.state["manifest"]["entries"] if e["kind"] in ("unavailable", "unsupported-encoding", "unreadable-directory", "lfs-pointer", "submodule", "submodule-unavailable")]
        if unavailable:
            issues.append("Unavailable/unprocessed source candidates remain: " + ", ".join(unavailable[:10]) + (" (see manifest for remaining entries)" if len(unavailable) > 10 else ""))
        report = {"version": 1, "valid": not issues, "integrity_valid": integrity_valid, "issues": issues, "coverage": status,
                  "limits": ["Delivered/accepted ranges do not prove understanding of every line.", "Citations and matching hashes do not establish semantic entailment.", "Semantic review is a Copilot judgment, not an automated proof.", "Redaction is heuristic and can miss secrets; review repository sensitivity first.", "Tests were read as source; target code was never run by this toolkit.", "Human approval is never assigned by the engine."]}
        atomic(self.home / "validation.json", report)
        return report
