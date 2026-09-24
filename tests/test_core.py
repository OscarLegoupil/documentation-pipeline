import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, SKILL, Engine, fixture, config, artifact, accept_next
from pipeline.common import Failure, atomic, contained, digest, load_config, tokens
from pipeline.contracts import validate_result
from pipeline.inventory import scan, packets, range_coverage, redact


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="toolkit spaces Київ ")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_strict_configuration_and_scope_ids(self):
        config(self.root)
        one = Engine(self.root, ["left/src"]).sid
        two = Engine(self.root, ["right/src"]).sid
        self.assertNotEqual(one, two)
        for text in ('unknown = true', 'scope = []', 'source_tokens = true', 'state_dir = "../escape"', '[executables]\ndot = "relative/dot"', '[branding]\nnavy = "blue"'):
            (self.root / "docgen.toml").write_text(text, encoding="utf-8")
            with self.assertRaises((Failure, ValueError)):
                load_config(self.root)

    def test_inventory_non_git_redaction_and_exclusions(self):
        fixture("mixed", self.root)
        (self.root / ".env").write_text("PRIVATE=do-not-deliver", encoding="utf-8")
        (self.root / "normal.py").write_text('api_key = "example-private-value"\npassword = unsafeLiteral\nvalue = 42\n', encoding="utf-8")
        (self.root / "utf16.txt").write_bytes("non-UTF8".encode("utf-16"))
        (self.root / "lfs.txt").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 900\n")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "a.js").write_text("dependency code")
        (self.root / "build").write_text("A source file may be named build; directory pruning must not exclude it.\n")
        cfg = load_config(self.root)
        manifest = scan(self.root, cfg)
        entries = {e["path"]: e for e in manifest["entries"]}
        self.assertTrue(entries["main.f90"]["eligible"])
        self.assertTrue(entries["notes.md"]["eligible"])
        self.assertFalse(entries["scratch"]["eligible"])
        self.assertFalse(entries[".env"]["eligible"])
        self.assertEqual(entries["node_modules"]["kind"], "excluded-directory")
        self.assertNotIn("node_modules/a.js", entries)
        self.assertTrue(entries["build"]["eligible"])
        self.assertEqual(entries["lfs.txt"]["kind"], "lfs-pointer")
        data, errors = packets(self.root, manifest, cfg)
        raw = json.dumps(data)
        self.assertNotIn("example-private-value", raw)
        self.assertNotIn("unsafeLiteral", raw)
        self.assertEqual(entries["normal.py"]["redacted_lines"], [1, 2])
        self.assertFalse(errors)
        lines, _ = redact("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\nx\n")
        self.assertEqual(len(lines), 4)
        self.assertNotIn("abc", str(lines))

    def test_git_tracked_ignored_untracked_submodule_and_dirty(self):
        git = shutil.which("git")
        self.assertTrue(git, "Git is required by the test matrix")
        def call(*args):
            return subprocess.run([git, *args], cwd=self.root, capture_output=True, check=True)
        call("init", "-q")
        (self.root / ".gitignore").write_text("*.secret.txt\nignored/\n")
        (self.root / "tracked.secret.txt").write_text("tracked source\n")
        call("add", "-f", "tracked.secret.txt", ".gitignore")
        call("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Synthetic fixture only")
        commit = call("rev-parse", "HEAD").stdout.decode().strip()
        call("update-index", "--add", "--cacheinfo", "160000," + commit + ",unavailable-module")
        (self.root / "untracked.secret.txt").write_text("ignored untracked\n")
        (self.root / "tracked.secret.txt").write_text("dirty tracked source\n")
        cfg = load_config(self.root)
        data = scan(self.root, cfg)
        entries = {e["path"]: e for e in data["entries"]}
        # File names containing 'secret' are conservatively excluded, even tracked.
        self.assertFalse(entries["tracked.secret.txt"]["eligible"])
        (self.root / "tracked.keep").write_text("eligible source\n")
        call("add", "tracked.keep")
        (self.root / ".gitignore").write_text("*.keep\nignored/\n")
        data = scan(self.root, cfg)
        self.assertTrue(next(e for e in data["entries"] if e["path"] == "tracked.keep")["eligible"])
        self.assertEqual(next(e for e in data["entries"] if e["path"] == "unavailable-module")["kind"], "submodule-unavailable")
        self.assertTrue(data["git"]["dirty"])
        self.assertEqual(data["git"]["commit"], commit)

    def test_large_packet_accounting_and_empty_file(self):
        (self.root / "empty.py").write_text("")
        (self.root / "many").mkdir()
        for i in range(300):
            (self.root / "many" / f"unit-{i}.code").write_text(f"public unit_{i}\nreturn {i}\n", encoding="utf-8")
        (self.root / "huge.txt").write_text("".join(f"line {i}: a useful bounded source statement\n" for i in range(5000)), encoding="utf-8")
        config(self.root, source_tokens=1200, packet_tokens=4000)
        cfg = load_config(self.root)
        manifest = scan(self.root, cfg)
        data, errors = packets(self.root, manifest, cfg)
        coverage = range_coverage(manifest, data)
        self.assertGreater(len(data), 20)
        self.assertFalse(errors)
        self.assertEqual(coverage["covered_lines"], coverage["source_lines"])
        self.assertEqual(coverage["covered_empty_files"], 1)
        self.assertFalse(coverage["missing_files"])
        self.assertTrue(all(tokens(p["chunks"]) <= 1200 for p in data))
        altered = copy.deepcopy(data)
        altered.pop()
        self.assertTrue(range_coverage(manifest, altered)["missing_files"])
        status = Engine(self.root).prepare()
        self.assertLessEqual(len(status["accepted_analysis_ranges"]["missing_files"]), 10)
        self.assertGreater(status["accepted_analysis_ranges"]["missing_file_count"], 300)

    def test_oversized_single_line_remains_visible_gap(self):
        (self.root / "large.data").write_text("x" * 30000)
        config(self.root, source_tokens=1000, packet_tokens=4000)
        cfg = load_config(self.root)
        manifest = scan(self.root, cfg)
        data, errors = packets(self.root, manifest, cfg)
        self.assertTrue(errors)
        self.assertEqual(range_coverage(manifest, data)["missing_files"], ["large.data"])

    def test_path_containment_and_symlinks(self):
        for path in ("../outside", "/absolute", "C:/absolute", "a\\b", "a/../b", "./a"):
            with self.assertRaises(Failure):
                contained(self.root, path)
        outside = self.root.parent / (self.root.name + " outside")
        outside.mkdir()
        try:
            (outside / "private.txt").write_text("private")
            try:
                (self.root / "escape").symlink_to(outside, target_is_directory=True)
            except OSError:
                if os.name != "nt":
                    raise
                subprocess.run(["cmd", "/c", "mklink", "/J", str(self.root / "escape"), str(outside)], capture_output=True, check=True)
            with self.assertRaises(Failure):
                contained(self.root, "escape/private.txt")
            entries = scan(self.root, load_config(self.root))["entries"]
            self.assertFalse(any(e["path"] == "escape/private.txt" for e in entries))
        finally:
            if (self.root / "escape").exists():
                (self.root / "escape").rmdir() if os.name == "nt" else (self.root / "escape").unlink()
            shutil.rmtree(outside)

    def test_accept_rejects_fabricated_stale_and_invalid_evidence(self):
        fixture(root=self.root)
        engine = Engine(self.root)
        session = engine.prepare()["session"]
        accept_next(engine, session)  # discovery
        receipt = engine.next(session)
        task = engine.state["tasks"][receipt["task_id"]]
        good = artifact(engine, task)
        def attempt(change):
            bad = copy.deepcopy(good)
            change(bad)
            atomic(Path(receipt["result"]), bad)
            with self.assertRaises(Failure):
                engine.accept(task["id"], session)
        attempt(lambda x: x.pop("categories"))
        attempt(lambda x: x["evidence"][0].update(path="fabricated.py"))
        attempt(lambda x: x["evidence"][0].update(start=99999))
        attempt(lambda x: x["evidence"][0].update(snippet="fabricated snippet"))
        attempt(lambda x: x["facts"][0].update(evidence=["missing.fact"]))
        attempt(lambda x: x["evidence"][0].update(path="../outside"))
        attempt(lambda x: x.update(chunks=[]))
        atomic(Path(receipt["result"]), good)
        path = self.root / task["chunks"][0]["path"]
        path.write_text(path.read_text("utf-8") + "\nchanged\n", encoding="utf-8")
        with self.assertRaises(Failure) as caught:
            engine.accept(task["id"], session)
        self.assertEqual(caught.exception.code, 5)
        self.assertEqual(engine.state["tasks"][task["id"]]["status"], "pending")

    def test_resume_preserves_acceptances_and_second_coordinator_fails(self):
        fixture(root=self.root)
        engine = Engine(self.root)
        session = engine.prepare()["session"]
        completed = accept_next(engine, session)
        old_hash = engine.state["tasks"][completed]["accepted_hash"]
        next_task = engine.next(session)
        with self.assertRaises(Failure) as caught:
            Engine(self.root).prepare()
        self.assertEqual(caught.exception.code, 4)
        resumed = Engine(self.root)
        recovered = resumed.prepare(recover=True)
        self.assertNotEqual(recovered["session"], session)
        self.assertEqual(resumed.state["tasks"][completed]["accepted_hash"], old_hash)
        self.assertEqual(resumed.next(recovered["session"])["task_id"], next_task["task_id"])
        with self.assertRaises(Failure):
            resumed.next(session)

    def test_external_evidence_registration_and_secret_refusal(self):
        (self.root / "src").mkdir()
        (self.root / "src/main.txt").write_text("calls shared configuration\n")
        (self.root / "shared.txt").write_text("declared external contract\n")
        (self.root / ".env").write_text("password=fixture\n")
        engine = Engine(self.root, ["src"])
        session = engine.prepare()["session"]
        rec = engine.next(session)
        old = engine.state["tasks"][rec["task_id"]]["input_fingerprint"]
        result = engine.evidence(rec["task_id"], "shared.txt", 1, 1, session)
        self.assertTrue(result["external_to_scope"])
        self.assertNotEqual(old, result["input_fingerprint"])
        with self.assertRaises(Failure):
            engine.evidence(rec["task_id"], ".env", 1, 1, session)

    def test_install_preserves_custom_files_and_conflicts(self):
        spec = importlib.util.spec_from_file_location("toolkit_installer", SKILL / "install.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path in (".github/copilot-instructions.md", ".vscode/settings.json", "docs/existing.md", "application.py"):
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("preserve me\n", encoding="utf-8")
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = module.install(SKILL, self.root, True)
        self.assertFalse(report["conflicts"])
        self.assertFalse((self.root / module.RELATIVE).exists())
        module.install(SKILL, self.root)
        for path, data in before.items():
            self.assertEqual((self.root / path).read_bytes(), data)
        target = self.root / module.RELATIVE / "SKILL.md"
        git = shutil.which("git")
        subprocess.run([git, "init", "-q"], cwd=self.root, check=True, capture_output=True)
        attrs = subprocess.run([git, "check-attr", "eol", "--", module.RELATIVE + "/SKILL.md"], cwd=self.root, check=True, capture_output=True, text=True)
        self.assertIn("eol: lf", attrs.stdout)
        self.assertTrue((self.root / module.RELATIVE / ".gitignore").exists())
        target.write_text("custom instruction", encoding="utf-8")
        report = module.install(SKILL, self.root)
        self.assertIn("SKILL.md", report["conflicts"])
        self.assertEqual(target.read_text("utf-8"), "custom instruction")

    def test_runtime_has_no_model_network_or_target_execution_adapter(self):
        banned = {"openai", "anthropic", "transformers", "torch", "requests", "httpx", "urllib", "socket", "langchain", "sentence_transformers"}
        for path in SKILL.rglob("*.py"):
            if any(p in (".venv", "__pycache__") for p in path.relative_to(SKILL).parts):
                continue
            tree = ast.parse(path.read_text("utf-8"))
            for node in ast.walk(tree):
                imports = [n.name.split(".")[0] for n in node.names] if isinstance(node, ast.Import) else [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module else []
                self.assertFalse(set(imports) & banned, str(path))
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        self.assertFalse(kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True)
        manifest = read_lock_names()
        self.assertEqual(manifest, {"python-docx", "lxml", "typing_extensions", "jsonschema", "attrs", "jsonschema-specifications", "referencing", "rpds-py"})

    def test_inventory_operates_with_network_blocked(self):
        fixture(root=self.root)
        with patch("socket.socket", side_effect=AssertionError("Network forbidden after setup")):
            engine = Engine(self.root)
            session = engine.prepare()["session"]
            self.assertTrue(engine.next(session)["task_id"])

    def test_process_failures_timeouts_and_encoding_are_explicit(self):
        import sys
        from pipeline.common import run
        for program, timeout in (("import sys;sys.exit(7)", 5), ("import time;time.sleep(5)", 0.05), ("import sys;sys.stdout.buffer.write(bytes([255]))", 5)):
            with self.assertRaises(Failure) as caught:
                run([sys.executable, "-c", program], self.root, timeout)
            self.assertEqual(caught.exception.code, 3)

    def test_unreadable_source_is_reported(self):
        from unittest.mock import patch
        (self.root / "unreadable.txt").write_text("fixture data")
        original = Path.read_bytes
        def denied(path):
            if path.name == "unreadable.txt":
                raise PermissionError("Fixture denied read")
            return original(path)
        with patch.object(Path, "read_bytes", denied):
            data = scan(self.root, load_config(self.root))
        entry = next(e for e in data["entries"] if e["path"] == "unreadable.txt")
        self.assertEqual(entry["kind"], "unavailable")
        self.assertIn("denied", entry["reason"])

    def test_copilot_skill_frontmatter_and_local_resources(self):
        import re
        content = (SKILL / "SKILL.md").read_text("utf-8")
        front = content.split("---", 2)[1]
        fields = dict(line.split(":", 1) for line in front.strip().splitlines())
        self.assertEqual(fields["name"].strip(), "generate-documentation")
        self.assertEqual(fields["user-invocable"].strip(), "true")
        self.assertEqual(fields["disable-model-invocation"].strip(), "true")
        self.assertNotIn("context", fields)
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if not target.startswith(("http:", "https:", "#")):
                path = (SKILL / target).resolve()
                self.assertTrue(path.is_relative_to(SKILL.resolve()))
                self.assertTrue(path.is_file(), target)

    def test_release_zip_ownership_hashes_and_no_local_environment(self):
        import zipfile
        archive = ROOT / "releases/copilot-docgen-1.0.0.zip"
        self.assertTrue(archive.exists(), "Run tools/package.py before release acceptance")
        with zipfile.ZipFile(archive) as z:
            prefix = ".github/skills/generate-documentation/"
            self.assertTrue(all(name.startswith(prefix) for name in z.namelist()))
            self.assertFalse(any("/.venv/" in name or "__pycache__" in name or ".setup.json" in name for name in z.namelist()))
            manifest = json.loads(z.read(prefix + ".toolkit-manifest.json"))
            for path, expected in manifest["files"].items():
                self.assertEqual(digest(z.read(prefix + path)), expected)
                self.assertEqual(digest((SKILL / path).read_bytes()), expected)
                if not path.endswith(".docx"):
                    self.assertNotIn(b"\r\n", z.read(prefix + path), "Git LF normalization would invalidate the ownership manifest: " + path)

    def test_atomic_checkpoint_handles_transient_windows_file_locks(self):
        import os
        target = self.root / "checkpoint.json"
        atomic(target, {"revision": 1})
        original = os.replace
        calls = []
        def transient(source, dest):
            calls.append(1)
            if len(calls) < 3:
                exc = PermissionError("Simulated indexer file lock")
                exc.winerror = 32
                raise exc
            return original(source, dest)
        with patch("pipeline.common.os.replace", transient):
            atomic(target, {"revision": 2})
        self.assertEqual(json.loads(target.read_text("utf-8"))["revision"], 2)
        self.assertEqual(len(calls), 3)


def read_lock_names():
    return {line.split("==")[0] for line in (SKILL / "requirements.lock").read_text("utf-8").splitlines() if "==" in line}


if __name__ == "__main__":
    unittest.main()
