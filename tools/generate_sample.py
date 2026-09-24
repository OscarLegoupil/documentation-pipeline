"""Build a document from hand-authored fixture artifacts, never target-client content."""
import argparse
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from support import Engine, fixture, finish_fixture
from pipeline.render import export, preview
from pipeline.common import atomic

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "samples/maintenance-style")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="docgen sample ü ") as tmp:
        root = fixture(root=tmp)
        engine = Engine(root)
        session = engine.prepare()["session"]
        status = finish_fixture(engine, session, layout=True)
        if not status["pipeline_complete"]:
            raise RuntimeError(status)
        progress = engine.state.get("progress_preview")
        if not progress or engine.state.get("progress_error"):
            raise RuntimeError("Automatic progress preview failed: " + str(engine.state.get("progress_error")))
        if args.preview:
            # Exercise the ordinary local renderer on the saved incremental artifact as well.
            engine.state["build"] = {"docx": str(Path(progress["directory"]) / "documentation-progress.docx")}
            preview(engine)
        build = export(engine)
        if args.preview:
            preview(engine)
        target = args.output.resolve()
        if target.exists() and not (target / "FIXTURE.txt").exists():
            raise RuntimeError("Refusing to overwrite an unowned sample folder")
        if target.exists():
            allowed = (ROOT / "samples").resolve()
            if target == allowed or not target.is_relative_to(allowed):
                raise RuntimeError("Repeated sample builds must stay inside the workspace samples directory; choose a new output path")
            # Verified absolute toolkit-owned target; no application/project tree is removed.
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        atomic(target / "FIXTURE.txt", "Hand-authored synthetic artifacts; this sample does not certify Copilot integration or semantic review.\n")
        shutil.copytree(build["directory"], target, dirs_exist_ok=True)
        shutil.copytree(progress["directory"], target / "progress")
        print(target / "documentation.docx")
        print(target / "progress/documentation-progress.docx")
