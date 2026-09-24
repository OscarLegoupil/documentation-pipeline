"""Create a reproducible ZIP of the self-contained, toolkit-owned runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".github/skills/generate-documentation"
sys.path.insert(0, str(SKILL))
from pipeline.common import atomic
from pipeline import VERSION


def package():
    files = {}
    for p in sorted(SKILL.rglob("*")):
        parts = p.relative_to(SKILL).parts
        owned_dotfile = len(parts) == 1 and p.name in (".gitattributes", ".gitignore")
        if not p.is_file() or (not owned_dotfile and any(x.startswith(".") or x == "__pycache__" for x in parts)):
            continue
        if p.is_symlink():
            raise ValueError("Release must not include symlinks")
        raw = p.read_bytes()
        if p.suffix != ".docx" and b"\r\n" in raw:
            raise ValueError("Runtime text must use LF line endings to preserve ownership hashes after Git checkout: " + str(p))
        files[p.relative_to(SKILL).as_posix()] = hashlib.sha256(raw).hexdigest()
    for required in ("SKILL.md", "docgen.py", "install.py", "setup.py", "templates/reference.docx", "schemas/result.schema.json", "requirements.lock"):
        if required not in files:
            raise ValueError("Missing runtime resource: " + required)
    manifest = SKILL / ".toolkit-manifest.json"
    atomic(manifest, {"owner": "generate-documentation", "version": VERSION, "files": files})
    dest = ROOT / "releases"
    dest.mkdir(exist_ok=True)
    archive = dest / f"copilot-docgen-{VERSION}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted([*files, manifest.name]):
            info = zipfile.ZipInfo(".github/skills/generate-documentation/" + name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, (SKILL / name).read_bytes())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    atomic(dest / "SHA256SUMS", checksum + "  " + archive.name + "\n")
    print(json.dumps({"zip": str(archive), "sha256": checksum, "runtime_files": len(files) + 1}, indent=2))
    return archive


if __name__ == "__main__":
    package()
