"""Run with the selected toolkit Python to rebuild the bundled style."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.style import build_reference

if __name__ == "__main__":
    build_reference(Path(__file__).with_name("reference.docx"))
