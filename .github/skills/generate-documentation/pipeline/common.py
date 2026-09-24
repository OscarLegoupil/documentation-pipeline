from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import time
import tomllib

SKILL = Path(__file__).resolve().parents[1]


class Failure(Exception):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Failure(f"Cannot read JSON {path}: {exc}") from exc


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data if isinstance(data, bytes) else data.encode("utf-8") if isinstance(data, str) else (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=".writing-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(name, path)
                break
            except PermissionError as exc:
                # Windows indexers/antivirus can briefly hold a newly closed file.
                # Bounded retries preserve atomicity and never edit the previous checkpoint.
                if getattr(exc, "winerror", None) not in (5, 32, 33):
                    raise
                if attempt == 4:
                    raise Failure(f"Atomic checkpoint is locked: {path}. Close the process holding it and resume; previous state is preserved.", 4) from exc
                time.sleep(0.05 * (2 ** attempt))
    finally:
        if os.path.exists(name):
            try:
                os.unlink(name)
            except PermissionError:
                pass  # Unaccepted .writing-*.tmp orphan; never used as a checkpoint.


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise Failure(f"Expected a normalized repository-relative path: {value!r}")
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or value != p.as_posix():
        raise Failure(f"Unsafe or non-normalized path: {value!r}")
    return value


def contained(root, value):
    relative(value)
    root = Path(root).resolve()
    path = root / value
    if not path.resolve().is_relative_to(root):
        raise Failure(f"Path escapes allowed root: {value}")
    # Refuse even in-root links for writes and source reads: stable ownership is clearer.
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink() or (parent.exists() and bool(getattr(parent.lstat(), "st_file_attributes", 0) & 0x400)):
            raise Failure(f"Symbolic link/junction is not an allowed artifact path: {value}")
    return path


def run(argv, cwd, timeout=60, input=None, binary=False):
    try:
        raw_input = input.encode("utf-8") if isinstance(input, str) else input
        result = subprocess.run([str(x) for x in argv], cwd=str(cwd), input=raw_input,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                                text=False, shell=False)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise Failure(f"Program failed: {argv[0]} ({exc}). Check doctor and executable overrides.", 3) from exc
    if result.returncode:
        err = result.stderr.decode("utf-8", "backslashreplace")
        raise Failure(f"{argv[0]} exited {result.returncode}: {err[-1800:]}", 3)
    if binary:
        return result.stdout
    try:
        return result.stdout.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise Failure(f"Non-UTF-8 output from {argv[0]}; no text was silently repaired", 3) from exc


def executable(name, config):
    explicit = config["executables"].get(name, "")
    result = explicit or shutil.which(name)
    if not result or (explicit and not Path(explicit).is_file()):
        raise Failure(f"Missing {name}. Install it explicitly or set [executables] {name} in docgen.toml to its absolute executable path.", 3)
    if explicit and not Path(explicit).is_absolute():
        raise Failure(f"Executable override for {name} must be absolute", 2)
    return result


def tokens(value):
    """Conservative volume estimate, not a model tokenizer or context guarantee."""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return (len(value.encode("utf-8")) + 2) // 3


def load_config(root, scope=None):
    config = tomllib.loads((SKILL / "defaults.toml").read_text("utf-8"))
    path = Path(root) / "docgen.toml"
    overrides = tomllib.loads(path.read_text("utf-8")) if path.exists() else {}
    unknown = set(overrides) - set(config)
    if unknown:
        raise Failure(f"Unknown configuration keys: {sorted(unknown)}")
    for key, value in overrides.items():
        if type(value) is not type(config[key]):
            raise Failure(f"Wrong type for configuration {key}")
        if isinstance(value, dict):
            if set(value) - set(config[key]):
                raise Failure(f"Unknown {key} keys: {sorted(set(value) - set(config[key]))}")
            for sub, val in value.items():
                if type(val) is not type(config[key][sub]):
                    raise Failure(f"Wrong type for {key}.{sub}")
            config[key].update(value)
        else:
            config[key] = value
    if scope:
        config["scope"] = scope
    for key in ("scope", "exclude", "prune_dirs"):
        if not all(isinstance(x, str) and x for x in config[key]):
            raise Failure(f"{key} must contain nonempty strings")
    if any(x in (".", "..") or "/" in x or "\\" in x for x in config["prune_dirs"]):
        raise Failure("prune_dirs must contain simple directory names")
    if not config["scope"]:
        raise Failure("scope must not be empty")
    config["scope"] = sorted(set(relative(x.rstrip("/") or ".") for x in config["scope"]))
    for key in ("state_dir", "output_dir"):
        relative(config[key])
        if config[key] == ".":
            raise Failure(f"{key} cannot be the repository root")
        contained(root, config[key])
    a, b = config["state_dir"], config["output_dir"]
    if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
        raise Failure("State and output directories must be separate")
    limits = {"source_tokens": (256, 32000), "packet_tokens": (2048, 64000), "result_tokens": (512, 16000),
              "summary_tokens": (128, 4000), "max_nodes": (2, 16), "repair_cycles": (0, 5), "timeout": (5, 600)}
    for key, (low, high) in limits.items():
        if not low <= config[key] <= high:
            raise Failure(f"{key} must be between {low} and {high}")
    if config["packet_tokens"] < config["source_tokens"] + 1000:
        raise Failure("packet_tokens must reserve at least 1000 tokens above source_tokens")
    import re
    for color in ("navy", "teal"):
        if not re.fullmatch(r"[0-9a-fA-F]{6}", config["branding"][color]):
            raise Failure(f"branding.{color} must be six hex digits")
    if config["branding"]["logo"]:
        p = contained(root, config["branding"]["logo"])
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg") or not p.is_file():
            raise Failure("Logo must be an existing local PNG or JPEG")
    for name, path in config["executables"].items():
        if path and not Path(path).is_absolute():
            raise Failure(f"executables.{name} must be an absolute path")
    config["title"] = config["title"] or Path(root).resolve().name
    if any(not config[x].strip() for x in ("title", "language", "audience")):
        raise Failure("title, language and audience must not be blank")
    return config


def scope_id(config):
    return "scope-" + digest({x: config[x] for x in ("scope", "exclude", "prune_dirs", "exclude_generated_headers")})[:16]


def code_version(presentation=False):
    paths = []
    for directory, dirs, names in os.walk(SKILL):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        paths.extend(Path(directory) / name for name in sorted(names) if not name.startswith("."))
    selected = [p for p in paths if (p.parent.name == "templates" or p.name in ("render.py", "style.py")) == presentation]
    return digest({p.relative_to(SKILL).as_posix(): digest(p.read_bytes()) for p in selected if p.suffix in (".py", ".md", ".json", ".toml", ".lua", ".docx", ".lock")})


@contextlib.contextmanager
def lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "writer.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Failure(f"Another command holds {path}. If its process has stopped, run recover-lock for this scope.", 4)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)
