#!/usr/bin/env python3
"""Explicit network-enabled dependency setup; runtime never installs packages."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, help="Install offline from an explicitly prepared wheel directory")
    parser.add_argument("--preview", action="store_true", help="Also install the optional pinned PyMuPDF page renderer")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    home = Path(__file__).resolve().parent
    env = home / ".venv"
    if env.is_symlink():
        parser.error("Toolkit environment must not be a symlink")
    venv.EnvBuilder(with_pip=True).create(env)
    python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    cmd = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:", "-r", str(home / "requirements.lock")]
    if args.wheelhouse:
        cmd.extend(["--no-index", "--find-links", str(args.wheelhouse.resolve())])
    if args.preview:
        cmd.extend(["-r", str(home / "requirements-preview.lock")])
    subprocess.run(cmd, cwd=home, check=True, timeout=600, shell=False)
    record = {"python": str(python), "base_python": sys.executable, "python_version": sys.version, "entry": str(home / "docgen.py")}
    (home / ".setup.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
