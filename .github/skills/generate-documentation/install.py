#!/usr/bin/env python3
"""Copy toolkit-owned files only, with conflict checks and a hash ownership manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
from pipeline.common import Failure, atomic, contained, read_json
from pipeline import VERSION

NAME = ".toolkit-manifest.json"
RELATIVE = ".github/skills/generate-documentation"


def files(source):
    manifest = source / NAME
    if manifest.exists():
        record = read_json(manifest)
        if record.get("owner") != "generate-documentation":
            raise Failure("Source ownership manifest is invalid")
        for name, expected in record["files"].items():
            path = contained(source, name)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise Failure(f"Release-owned source differs from manifest: {name}. Use a verified release or rebuild the development package.")
        return record["files"]
    # Development checkout before packaging; a release always carries the manifest.
    return {p.relative_to(source).as_posix(): hashlib.sha256(contained(source, p.relative_to(source).as_posix()).read_bytes()).hexdigest() for p in sorted(source.rglob("*")) if p.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(source).parts)}


def install(source, repo, dry_run=False):
    source, repo = Path(source).resolve(), Path(repo).resolve()
    if not repo.is_dir():
        raise Failure("Destination repository must already exist")
    dest = contained(repo, RELATIVE)
    if source == dest:
        raise Failure("Source and destination skill are the same")
    new = files(source)
    if "SKILL.md" not in new or "templates/reference.docx" not in new:
        raise Failure("Source is not a complete runtime release")
    old = read_json(dest / NAME) if (dest / NAME).exists() else {"files": {}}
    if old.get("owner", "generate-documentation") != "generate-documentation":
        raise Failure("Destination manifest belongs to another owner")
    conflicts, writes, removals = [], [], []
    for name, expected in new.items():
        target = contained(dest, name)
        if target.exists():
            if not target.is_file():
                conflicts.append(name)
                continue
            current = hashlib.sha256(target.read_bytes()).hexdigest()
            if current == expected:
                continue
            if current != old["files"].get(name):
                conflicts.append(name)
                continue
        writes.append(name)
    for name, expected in old["files"].items():
        if name not in new:
            target = contained(dest, name)
            if target.exists():
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                    conflicts.append(name)
                else:
                    removals.append(name)
    report = {"version": VERSION, "destination": str(dest), "dry_run": dry_run, "copy": writes, "remove_obsolete_owned": removals, "conflicts": conflicts}
    if conflicts or dry_run:
        return report
    # Conflict detection is completed before any mutation; ownership manifest commits last.
    for name in writes:
        atomic(contained(dest, name), contained(source, name).read_bytes())
    for name in removals:
        contained(dest, name).unlink()
    atomic(dest / NAME, {"owner": "generate-documentation", "version": VERSION, "files": new})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        report = install(Path(__file__).resolve().parent, args.repository, args.dry_run)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 4 if report["conflicts"] else 0
    except Failure as exc:
        print(json.dumps({"error": str(exc)}))
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
