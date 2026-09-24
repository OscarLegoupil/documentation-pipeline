"""Cross-platform test driver using the toolkit-local selected interpreter."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
skill = root / ".github/skills/generate-documentation"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("core", "integration", "smoke"))
    args = parser.parse_args()
    record = skill / ".setup.json"
    python = json.loads(record.read_text("utf-8"))["python"] if record.exists() else sys.executable
    if args.mode == "smoke":
        cmd = [python, str(root / "tools/generate_sample.py"), "--preview"]
    else:
        pattern = "test_core.py" if args.mode == "core" else "test_integration.py"
        cmd = [python, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"]
    subprocess.run(cmd, cwd=root, check=True, timeout=600)
