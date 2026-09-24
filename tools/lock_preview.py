"""Refresh the explicitly selected optional renderer lock from official PyPI metadata."""
import json
from pathlib import Path
import urllib.request

version = "1.28.2"
data = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/PyMuPDF/{version}/json", timeout=30))
hashes = sorted({f["digests"]["sha256"] for f in data["urls"]})
dest = Path(__file__).resolve().parents[1] / ".github/skills/generate-documentation/requirements-preview.lock"
dest.write_text("# Optional PDF rasterizer; LibreOffice remains an external prerequisite.\nPyMuPDF==" + version + " \\\n" + " \\\n".join("    --hash=sha256:" + h for h in hashes) + "\n", encoding="utf-8", newline="\n")
