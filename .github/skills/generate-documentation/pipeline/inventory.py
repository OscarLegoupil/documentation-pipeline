"""Read-only source inventory, redaction and exact range packet accounting."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
import re
import shutil

from .common import Failure, contained, digest, read_json, run, tokens

VCS = {".git", ".hg", ".svn"}
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".docx", ".xlsx", ".zip", ".gz", ".7z", ".exe", ".dll", ".so", ".o", ".class", ".pyc", ".woff", ".woff2", ".mp4", ".sqlite", ".db"}
SECRET = re.compile(r"(?i)(^\.env($|\.)|(^|[._-])(credentials?|secrets?)([._-]|$)|\.(pem|key|p12|pfx|keystore)$|^id_(rsa|ed25519)$)")
ASSIGN = re.compile(r"(?i)((?:[\w.-]{0,80}(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[\w.-]{0,80})[\"']?\s*[:=]\s*)([\"'])(.*?)(\2)")
BARE = re.compile(r"(?i)((?:password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[:=]\s*)([^\s#;,\"']+)")
KNOWN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{20,})\b")
URI_AUTH = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]{0,30}://)[^\s/@:]+:[^\s/@]+@")


def redact(text):
    output, changed, private = [], [], False
    for number, line in enumerate(text.splitlines(), 1):
        original = line
        if "-----BEGIN " in line and "PRIVATE KEY-----" in line:
            private = True
        if private:
            line = "[REDACTED PRIVATE KEY]"
            if "-----END " in original and "PRIVATE KEY-----" in original:
                private = False
        else:
            if re.search(r"(?i)password|passwd|secret|token|api[_-]?key|access[_-]?key", line):
                line = ASSIGN.sub(lambda m: m[1] + m[2] + "[REDACTED]" + m[4], line)
                line = BARE.sub(lambda m: m[1] + "[REDACTED]", line)
            line = KNOWN.sub("[REDACTED]", line)
            if "://" in line:
                line = URI_AUTH.sub(r"\1[REDACTED]@", line)
        if line != original:
            changed.append(number)
        output.append(line)
    return output, changed


def selected(path, config):
    return any(s == "." or path == s or path.startswith(s + "/") for s in config["scope"])


def exclusion(path, config, is_directory=False):
    for prefix in (".github/skills/generate-documentation", config["state_dir"], config["output_dir"]):
        if path == prefix or path.startswith(prefix + "/"):
            return prefix, "toolkit or generated artifacts"
    parts = path.split("/")
    for i, part in enumerate(parts):
        if part in VCS or (part in config["prune_dirs"] and (i < len(parts) - 1 or is_directory)):
            return "/".join(parts[:i + 1]), "pruned dependency/cache/generated tree"
    for pattern in config["exclude"]:
        if fnmatch.fnmatchcase(path, pattern) or path.startswith(pattern.rstrip("/") + "/"):
            return path, "configured exclusion"
    if SECRET.search(parts[-1]):
        return path, "likely credential file"
    if path == "docgen.toml":
        return path, "toolkit configuration"
    if Path(path).suffix.lower() in BINARY:
        return path, "binary asset"
    if re.search(r"(?:\.min\.(?:js|css)|\.map|\.lock)$", path) or parts[-1] in ("package-lock.json", "yarn.lock", "Cargo.lock"):
        return path, "generated/minified or dependency lock data"
    return None


def link(path):
    try:
        st = path.lstat()
        return path.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def toolkit_tree(directory):
    marker = directory / ".docgen-owned.json"
    if marker.is_file() and not link(marker):
        try:
            return read_json(marker).get("owner") == "generate-documentation"
        except Failure:
            return False
    return False


def walk(root, config):
    """Deterministic non-Git subset: nested .gitignore/.docgenignore, globs and !."""
    records = []

    def descend(directory, inherited):
        rules = list(inherited)
        for name in (".gitignore", ".docgenignore"):
            ignore = directory / name
            if ignore.is_file() and not link(ignore):
                try:
                    for line in ignore.read_text("utf-8").splitlines():
                        if line and not line.startswith("#"):
                            rules.append((directory.relative_to(root).as_posix(), line.strip()))
                except (UnicodeError, OSError):
                    pass  # The file itself is still inventoried and classified below.
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            records.append((directory.relative_to(root).as_posix(), "unreadable-directory", str(exc)))
            return
        for path in entries:
            rel = path.relative_to(root).as_posix()
            if link(path):
                records.append((rel, "symlink", "links/reparse points are not followed"))
                continue
            if path.is_dir() and toolkit_tree(path):
                records.append((rel, "excluded-directory", "toolkit-owned prior state/output tree"))
                continue
            ex = exclusion(rel, config, path.is_dir())
            if path.is_dir() and ex:
                records.append((rel, "excluded-directory", ex[1]))
                continue
            ignored = False
            for base, pattern in rules:
                local = rel if base == "." else rel[len(base) + 1:]
                negate = pattern.startswith("!")
                pattern = pattern.lstrip("!").lstrip("/").rstrip("/")
                match = fnmatch.fnmatchcase(local, pattern) or ("/" not in pattern and any(fnmatch.fnmatchcase(p, pattern) for p in local.split("/")))
                if match:
                    ignored = not negate
            if ignored:
                records.append((rel, "excluded-directory" if path.is_dir() else "excluded", "non-Git ignore rule"))
            elif path.is_dir():
                descend(path, rules)
            else:
                records.append((rel, "file", ""))
    descend(root, [])
    return records


def scan(root, config):
    root = Path(root).resolve()
    git = shutil.which("git")
    metadata = {"kind": "non-git", "commit": None, "dirty": None}
    records, tracked = [], set()
    if git:
        try:
            top = run([git, "rev-parse", "--show-toplevel"], root).strip()
            if Path(top).resolve() == root:
                metadata["kind"] = "git"
        except Failure:
            pass
    if metadata["kind"] == "git":
        try:
            metadata["commit"] = run([git, "rev-parse", "HEAD"], root).strip()
        except Failure:
            metadata["commit"] = None
        # --no-optional-locks avoids refreshing the target's index.
        dirty = run([git, "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=normal"], root, binary=True)
        metadata.update(dirty=bool(dirty), dirty_digest=digest(dirty))
        stages = run([git, "ls-files", "--stage", "-z"], root, binary=True).decode("utf-8", "strict")
        for entry in stages.split("\0"):
            if not entry:
                continue
            meta, rel = entry.split("\t", 1)
            if rel in tracked:
                continue
            tracked.add(rel)
            mode = meta.split()[0]
            records.append((rel, "submodule" if mode == "160000" else "file", "submodule content not traversed" if mode == "160000" else ""))
        untracked = run([git, "ls-files", "--others", "--exclude-standard", "-z"], root, binary=True).decode("utf-8", "strict")
        records.extend((p, "file", "") for p in untracked.split("\0") if p)
        # Record pruned/ignored directories without claiming to inspect their contents.
        ignored = run([git, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"], root, binary=True).decode("utf-8", "strict")
        records.extend((p.rstrip("/"), "excluded-directory" if p.endswith("/") else "excluded", "Git-ignored untracked material") for p in ignored.split("\0") if p)
    else:
        records = walk(root, config)
    entries, excluded, owned_cache = {}, {}, {}
    for rel, kind, reason in sorted(records):
        if not selected(rel, config) and not any(s.startswith(rel + "/") for s in config["scope"]):
            continue
        ex = exclusion(rel, config, kind.endswith("directory") or (root / rel).is_dir())
        if not ex:
            parts = rel.split("/")
            for i in range(1, len(parts)):
                prefix = "/".join(parts[:i])
                if prefix not in owned_cache:
                    owned_cache[prefix] = toolkit_tree(root / prefix)
                if owned_cache[prefix]:
                    ex = (prefix, "toolkit-owned prior state/output tree")
                    break
        if ex:
            p, why = ex
            excluded[p] = {"path": p, "kind": "excluded-directory" if p != rel or (root / rel).is_dir() else "excluded", "reason": why, "eligible": False}
            continue
        entry = {"path": rel, "kind": kind, "reason": reason, "eligible": False, "tracked": rel in tracked, "hash": None, "size": None, "lines": 0, "redacted_lines": []}
        entries[rel] = entry
        if kind == "submodule" and not (root / rel / ".git").exists():
            entry.update(kind="submodule-unavailable", reason="Submodule working content is unavailable; not fetched or traversed")
        if kind != "file":
            continue
        try:
            path = contained(root, rel)
            if link(path):
                raise Failure("links/reparse points are not followed")
            raw = path.read_bytes()
            entry.update(hash=digest(raw), size=len(raw))
            if b"\0" in raw:
                entry.update(kind="binary", reason="NUL bytes")
                continue
            text = raw.decode("utf-8-sig", "strict")
            lines, redacted_lines = redact(text)
            entry.update(lines=len(lines), redacted_lines=redacted_lines)
            if text.startswith("version https://git-lfs.github.com/spec/v1"):
                entry.update(kind="lfs-pointer", reason="Git LFS object is unavailable; pointer is not source")
                continue
            if config["exclude_generated_headers"] and any("@generated" in line.lower() or "automatically generated" in line.lower() or "do not edit" in line.lower() for line in lines[:5]):
                entry.update(kind="generated", reason="generated-file header heuristic; inspect exclusion if inappropriate")
                continue
            entry.update(eligible=True, kind="text", reason="")
        except UnicodeError:
            entry.update(kind="unsupported-encoding", reason="Not strict UTF-8; convert a separate copy explicitly")
        except (OSError, Failure) as exc:
            entry.update(kind="unavailable", reason=str(exc))
    for fixed in (".github/skills/generate-documentation", config["state_dir"], config["output_dir"]):
        if selected(fixed, config):
            excluded[fixed] = {"path": fixed, "kind": "excluded-directory", "reason": "toolkit or generated artifacts", "eligible": False}
    for record in excluded.values():
        record.update(hash=None, size=None, lines=None, redacted_lines=[], inspection="excluded without reading content")
    manifest = {"version": 1, "git": metadata, "entries": sorted([*entries.values(), *excluded.values()], key=lambda e: e["path"])}
    # Git dirty status includes toolkit state after first prepare; do not use it as content identity.
    manifest["snapshot"] = digest({"commit": metadata["commit"], "entries": manifest["entries"]})
    return manifest


def source(root, entry):
    raw = contained(root, entry["path"]).read_bytes()
    if digest(raw) != entry["hash"]:
        raise Failure(f"Source changed: {entry['path']}. Run prepare/rescan before continuing.", 5)
    return redact(raw.decode("utf-8-sig", "strict"))[0]


def packets(root, manifest, config):
    packets, current, errors = [], [], []
    # Leave half of the total packet for analysis dependencies/instructions during later stages.
    budget = min(config["source_tokens"], (config["packet_tokens"] - 1800) // 2)

    def fits(chunks):
        # Reserve estimated result space for one minimal fact + evidence account per chunk.
        # This is a volume constraint, not a fixed file-count limit.
        result_floor = sum(280 + tokens(c["path"]) * 2 for c in chunks)
        return tokens(chunks) <= budget and result_floor <= config["result_tokens"] - 1000

    def flush():
        nonlocal current
        if current:
            packets.append({"chunks": current, "id": "p-" + digest(current)[:20]})
            current = []

    for entry in manifest["entries"]:
        if not entry["eligible"]:
            continue
        lines = source(root, entry)
        if not lines:
            chunk = {"path": entry["path"], "hash": entry["hash"], "start": 0, "end": 0, "text": "", "id": "c-" + digest([entry["path"], entry["hash"], 0])[:20]}
            if not fits(current + [chunk]):
                flush()
            current.append(chunk)
            continue
        start = 0
        while start < len(lines):
            end, chosen = start, []
            while end < len(lines):
                test = chosen + [lines[end]]
                if tokens("\n".join(test)) + 180 > budget:
                    break
                chosen = test
                end += 1
            if end == start:
                errors.append({"path": entry["path"], "start": start + 1, "end": start + 1, "reason": "Single line exceeds source budget; explicitly raise budget or document partial gap"})
                start += 1
                continue
            # Prefer a nearby blank-line boundary, preserving every line exactly once.
            if end < len(lines) and end - start > 12:
                for n in range(end - 1, max(start, end - 20), -1):
                    if not lines[n].strip():
                        end, chosen = n + 1, lines[start:n + 1]
                        break
            chunk = {"path": entry["path"], "hash": entry["hash"], "start": start + 1, "end": end, "text": "\n".join(chosen), "id": "c-" + digest([entry["path"], entry["hash"], start + 1, end])[:20]}
            if not fits(current + [chunk]):
                flush()
            if tokens([chunk]) > budget:
                raise Failure("Chunk metadata exceeds budget; raise source_tokens")
            current.append(chunk)
            start = end
    flush()
    return packets, errors


def range_coverage(manifest, packets):
    ranges = {}
    for packet in packets:
        for chunk in packet["chunks"]:
            ranges.setdefault(chunk["path"], []).append((chunk["start"], chunk["end"]))
    expected, covered, empty, empty_covered, missing = 0, 0, 0, 0, []
    for entry in manifest["entries"]:
        if not entry["eligible"]:
            continue
        n = entry["lines"]
        expected += n
        if n == 0:
            empty += 1
            empty_covered += (0, 0) in ranges.get(entry["path"], [])
            if (0, 0) not in ranges.get(entry["path"], []):
                missing.append(entry["path"])
            continue
        cursor, count = 1, 0
        for start, end in sorted(ranges.get(entry["path"], [])):
            if start < 1 or end > n or end < start:
                raise Failure(f"Invalid packet range: {entry['path']}:{start}-{end}")
            if end >= cursor:
                count += end - max(cursor, start) + 1
                cursor = end + 1
        covered += count
        if count != n:
            missing.append(entry["path"])
    return {"source_lines": expected, "covered_lines": covered, "empty_files": empty, "covered_empty_files": empty_covered, "missing_files": missing}
