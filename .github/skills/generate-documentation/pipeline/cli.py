from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from .common import Failure, SKILL, executable, load_config, lock
from .engine import Engine


def doctor(root):
    config = load_config(root)
    checks = [{"name": "python", "ok": sys.version_info >= (3, 11), "version": sys.version.split()[0], "executable": sys.executable}]
    pins = {line.split("==")[0]: line.split("==")[1].strip().rstrip("\\").strip() for line in (SKILL / "requirements.lock").read_text("utf-8").splitlines() if "==" in line}
    for package, expected in pins.items():
        try:
            version = importlib.metadata.version(package)
            checks.append({"name": package, "ok": version == expected, "version": version, "expected": expected, "action": "none" if version == expected else "Run setup.py to restore the tested lock"})
        except importlib.metadata.PackageNotFoundError:
            checks.append({"name": package, "ok": False, "error": "Run setup.py; use the Python executable recorded in .setup.json"})
    for name in ("pandoc", "dot", "soffice", "pdftoppm"):
        optional = name in ("soffice", "pdftoppm")
        try:
            path = executable(name, config)
            args = [path, "-V" if name == "dot" else "-v" if name == "pdftoppm" else "--version"]
            result = subprocess.run(args, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=True, shell=False)
            version = (result.stdout + result.stderr).strip().splitlines()[0]
            checks.append({"name": name, "ok": True, "optional": optional, "executable": path, "version": version})
        except (Failure, OSError, subprocess.SubprocessError) as exc:
            checks.append({"name": name, "ok": False, "optional": optional, "error": str(exc)})
    try:
        pdf_version = importlib.metadata.version("PyMuPDF")
    except importlib.metadata.PackageNotFoundError:
        pdf_version = None
    checks.append({"name": "PyMuPDF", "ok": bool(pdf_version), "optional": True, "version": pdf_version, "purpose": "Alternative to pdftoppm; install with setup.py --preview"})
    preview_ok = next(c["ok"] for c in checks if c["name"] == "soffice") and (bool(pdf_version) or next(c["ok"] for c in checks if c["name"] == "pdftoppm"))
    return {"ok": all(c["ok"] or c.get("optional", False) for c in checks), "checks": checks, "network": "Runtime commands use no network; Copilot is an online service", "visual_qa": "rendering-available-inspection-pending" if preview_ok else "pending until optional local preview tools are installed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deterministic local documentation engine. All command output is JSON.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--scope", action="append", help="Repeat for multiple repository-relative scope paths")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    prepare = sub.add_parser("prepare", aliases=["rescan"])
    prepare.add_argument("--session")
    prepare.add_argument("--recover", action="store_true", help="Only after stopping the previous chat: recover its worker lease")
    for name in ("next", "accept", "repair", "evidence"):
        p = sub.add_parser(name)
        p.add_argument("--session", required=True)
        if name != "next":
            p.add_argument("--task", required=True)
        if name == "repair":
            p.add_argument("--reason", help="Concrete mechanical/budget correction when no semantic finding exists")
        if name == "evidence":
            p.add_argument("--path", required=True)
            p.add_argument("--start", required=True, type=int)
            p.add_argument("--end", required=True, type=int)
    sub.add_parser("status")
    sub.add_parser("validate")
    export = sub.add_parser("export")
    export.add_argument("--partial", action="store_true", help="Explicit draft export with visible gaps; never bypasses corrupt/stale evidence")
    sub.add_parser("preview")
    layout = sub.add_parser("record-layout")
    layout.add_argument("--pages", required=True, help="Comma-separated actual inspected page numbers, e.g. 1,2,3")
    layout.add_argument("--reviewer", required=True, choices=("copilot", "human", "build-agent"))
    layout.add_argument("--notes", required=True)
    lookup = sub.add_parser("lookup")
    lookup.add_argument("query")
    lookup.add_argument("--limit", type=int, default=10)
    lookup.add_argument("--task", help="Attach bounded matches and original evidence to an issued packet")
    lookup.add_argument("--session")
    sub.add_parser("recover-lock", help="Remove a writer lock only after its OS process has exited")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(args.root.resolve())
            code = 0 if result["ok"] else 3
        else:
            engine = Engine(args.root, args.scope)
            if args.command in ("prepare", "rescan"):
                result = engine.prepare(args.session, args.recover)
            elif args.command == "recover-lock":
                path = engine.home / "writer.lock"
                if not path.exists():
                    result = {"recovered": False, "reason": "No command lock exists"}
                else:
                    pid = int(path.read_text("ascii"))
                    if os.name == "nt":
                        import ctypes
                        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                        alive = bool(handle)
                        if handle:
                            ctypes.windll.kernel32.CloseHandle(handle)
                    else:
                        try:
                            os.kill(pid, 0)
                            alive = True
                        except ProcessLookupError:
                            alive = False
                    if alive:
                        raise Failure(f"Writer process {pid} still exists; stop it before recovery", 4)
                    path.unlink()
                    result = {"recovered": True}
            elif args.command == "status":
                result = engine.status()
            elif not engine.state:
                raise Failure("No matching run. Run prepare first.")
            elif args.command == "next":
                result = engine.next(args.session)
            elif args.command == "accept":
                result = engine.accept(args.task, args.session)
            elif args.command == "repair":
                result = engine.repair(args.task, args.session, args.reason)
            elif args.command == "evidence":
                result = engine.evidence(args.task, args.path, args.start, args.end, args.session)
            elif args.command == "lookup":
                if not 1 <= args.limit <= 50:
                    raise Failure("lookup limit must be 1–50")
                result = engine.lookup(args.query, args.limit, args.task, args.session)
            elif args.command == "validate":
                with lock(engine.home):
                    result = engine.validate()
            elif args.command == "export":
                from .render import export
                result = export(engine, args.partial)
            elif args.command == "preview":
                from .render import preview
                with lock(engine.home):
                    engine.reload()
                    result = preview(engine)
            elif args.command == "record-layout":
                from .render import record_layout
                with lock(engine.home):
                    engine.reload()
                    result = record_layout(engine, [int(p) for p in args.pages.split(",")], args.reviewer, args.notes)
            code = 6 if args.command == "validate" and not result["valid"] else 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (Failure, OSError, ValueError, KeyError, UnicodeError) as exc:
        print(json.dumps({"error": str(exc), "exit_code": getattr(exc, "code", 2)}, ensure_ascii=False))
        return getattr(exc, "code", 2)


if __name__ == "__main__":
    raise SystemExit(main())
