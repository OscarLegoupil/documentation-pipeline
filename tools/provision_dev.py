"""Explicit development-only downloads. Never shipped inside the runtime."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".tools"
DEST.mkdir(exist_ok=True)


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "docgen-development-setup"}), timeout=120).read()


def locks():
    versions = {"python-docx": "1.2.0", "lxml": "6.1.3", "typing_extensions": "4.16.0", "jsonschema": "4.26.0", "attrs": "26.1.0", "jsonschema-specifications": "2025.9.1", "referencing": "0.37.0", "rpds-py": "2026.6.3"}
    rows = ["# Exact transitive versions; hashes from official PyPI release metadata.\n"]
    for name, version in versions.items():
        data = json.loads(fetch(f"https://pypi.org/pypi/{name}/{version}/json"))
        hashes = sorted({f['digests']['sha256'] for f in data['urls']})
        rows.append(name + "==" + version + " \\\n" + " \\\n".join("    --hash=sha256:" + h for h in hashes) + "\n")
    (ROOT / ".github/skills/generate-documentation/requirements.lock").write_text("\n".join(rows), encoding="utf-8")
    return "Wrote hash-locked Python dependencies"


def download_zip(name, url):
    archive = DEST / (name + ".zip")
    if not archive.exists():
        archive.write_bytes(fetch(url))
    target = DEST / name
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            if not (target / member.filename).resolve().is_relative_to(target.resolve()):
                raise ValueError("Unsafe archive path")
        z.extractall(target)
    return {"name": name, "url": url, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


def graphviz():
    html = fetch("https://graphviz.org/download/").decode("utf-8")
    urls = re.findall(r'href="([^"]+)"', html)
    url = next(u for u in urls if "16.1.0" in u and "win64" in u and u.endswith(".zip"))
    return download_zip("graphviz", url)


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor() as pool:
        futures = [pool.submit(locks), pool.submit(download_zip, "pandoc", "https://github.com/jgm/pandoc/releases/download/3.11/pandoc-3.11-windows-x86_64.zip"), pool.submit(graphviz)]
        results = []
        for future in futures:
            try:
                result = future.result()
                print(result, flush=True)
                results.append(result)
            except Exception as exc:
                print(type(exc).__name__, str(exc), flush=True)
        (DEST / "downloads.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
