# Portable Copilot documentation pipeline

Copy one skill folder into a repository, open it in VS Code, and invoke `/generate-documentation` in **GitHub Copilot**. Copilot analyzes, writes and reviews; local Python scripts inventory source, checkpoint work, validate evidence, render Graphviz diagrams and build one combined Word document. No model API, API credentials, alternate model runner, Copilot CLI, server or target-project execution is involved.

The product is [`.github/skills/generate-documentation/`](.github/skills/generate-documentation/). The [release ZIP](releases/copilot-docgen-1.0.0.zip) contains that folder, including its installer. The [Word style sample](samples/maintenance-style/documentation.docx) and [incremental Word preview](samples/maintenance-style/progress/documentation-progress.docx) use **hand-authored synthetic fixture artifacts**, not live Copilot output or client documentation.

## Copy and run

Prerequisites: Python 3.11+, Pandoc 3.x, Graphviz `dot`, and an approved GitHub Copilot session in VS Code. Select the **Copilot agent/provider** and a model available through your subscription. There is no hardcoded model or entitlement assumption.

From this repository (or an extracted release), PowerShell:

```powershell
python .github/skills/generate-documentation/install.py 'C:\work\Target Repo' --dry-run
python .github/skills/generate-documentation/install.py 'C:\work\Target Repo'
Set-Location 'C:\work\Target Repo'
python .github/skills/generate-documentation/setup.py
$docgenPython = (Get-Content .github/skills/generate-documentation/.setup.json -Raw | ConvertFrom-Json).python
& $docgenPython .github/skills/generate-documentation/docgen.py doctor
```

macOS/Linux:

```sh
python3 .github/skills/generate-documentation/install.py '/work/Target Repo' --dry-run
python3 .github/skills/generate-documentation/install.py '/work/Target Repo'
cd '/work/Target Repo'
python3 .github/skills/generate-documentation/setup.py
.github/skills/generate-documentation/.venv/bin/python .github/skills/generate-documentation/docgen.py doctor
```

You may instead manually copy just the skill folder to an absent destination. For an existing installation, use the installer: it checks ownership/version hashes, reports customized-file conflicts before making changes, and never touches unrelated instructions, settings, docs or application files. Unpack release ZIPs into a staging directory before installing; do not blindly extract over a customized repository.

Install external tools explicitly from [Pandoc](https://pandoc.org/installing.html) and [Graphviz](https://graphviz.org/download/) or approved organizational packages. Setup downloads only the toolkit's hash-locked Python dependencies into its own `.venv`, records the selected Python path and never activates an environment or changes global PATH. See [portable setup guidance](.github/skills/generate-documentation/SETUP.md) for executable overrides and offline wheel setup.

In VS Code's Copilot chat:

```text
/generate-documentation
/generate-documentation scope=src
/generate-documentation action=status
/generate-documentation action=validate
/generate-documentation action=export
```

These arguments are instructions interpreted by the skill, **not native editor flags**. No arguments means the complete repository and continuation of matching work. Stop the old coordinator before resuming with the same command in a new chat. Fresh native subagents are preferred when the current Copilot host provides them; bounded single-agent mode uses the same queue but requires new chats for genuinely fresh contexts. Neither mode bypasses approvals, policy, context or request limits.

`action=export` only rebuilds accepted content. It never asks a model to rewrite it. Strict export blocks incomplete analysis, stale sources, structural errors and blocking review findings. An explicitly requested partial export is `DRAFT-INCOMPLETE.docx` with its gaps visible. No successful output includes failed diagram source.

## Outputs and verification

State is under `.docgen/runs/<scope-id>/`; outputs are under `docs/generated/<scope-id>/build-*/`. Scope IDs hash normalized relative scope/exclusion settings, so matching basenames in different directories do not collide. Each build includes Markdown, DOCX, editable diagram JSON/DOT, SVG/PNG, evidence index, coverage and quality reports. Application files and Git history are preserved. The toolkit does not modify ignore rules; add artifact paths manually if your policy calls for it.

As each subsystem finishes **all** its chapter sections and required reviews, the engine automatically rebuilds `docs/generated/<scope-id>/documentation-progress.docx`. This **Incomplete draft** contains completed chapters and their rendered diagrams, plus a progress page listing completed, pending and blocked subsystems. It uses saved validated artifacts only, with no new model requests or repeated analysis. Accepted work remains checkpointed if rendering fails; the previous successful preview stays intact, and `status` reports the failure and whether that preview is current. Correct the reported cause (for example, close the preview in Word), then continue with the same slash command; `next` retries the deterministic build. Each successful progress build retains its supporting assets under `progress-build-*/`. The progress preview is separate from the final document, never satisfies strict final-export gates, and does not imply visual inspection or human approval.

The document contains source snapshot/scope, visible linked contents, overview and supported entry points, subsystem chapters with architectural context and inputs/outputs, interfaces, evidenced maintenance/failure/lifecycle details, component indexes, gaps and source references. Diagrams use local Graphviz. Ordered flows and interaction tables deliberately replace sequence-specific Mermaid rendering in v1; no Node/browser/remote renderer is needed.

Basic export works without LibreOffice and reports layout QA **pending**. For a local PDF/page preview, explicitly install LibreOffice and either Poppler `pdftoppm` or `setup.py --preview` for the pinned optional PyMuPDF renderer. Then use the recorded Python:

```powershell
& $docgenPython .github/skills/generate-documentation/docgen.py validate
& $docgenPython .github/skills/generate-documentation/docgen.py export
& $docgenPython .github/skills/generate-documentation/docgen.py preview
```

Inspect every page for clipped content, table headers/wrapping, readable diagrams, Unicode, headings, captions and working contents links. Record the actual inspected page numbers with `record-layout --pages 1,2,3 --reviewer human --notes "observations"` (use the real page list). This updates the companion QA record, not the already inspected DOCX. Rendering alone is not visual inspection. Human approval remains a separate user decision; the engine never assigns it. Copilot is an online service; deterministic processing after explicit setup uses no network.

Coverage distinguishes inventoried/excluded entries, eligible ranges delivered, ranges with accepted analysis, facts/components represented, and blocks subjected to semantic review. Full packet accounting does not prove understanding. A matching citation does not prove that its source supports the claim. Reviews are model judgments, not a hallucination-proof guarantee. Tests in target repositories are read as expectations, never reported as executed by this tool.

## Customize and troubleshoot

Normal use needs no configuration. Optional root `docgen.toml` strictly overrides [defaults](.github/skills/generate-documentation/defaults.toml): scope/exclusions, title/language/audience, output/state paths, branding colors/local logo, volume budgets, repair limit and absolute executable locations. Unknown keys/types and unsafe paths fail early. Example:

```toml
scope = ["packages/library"]
title = "Library maintenance guide"
language = "en"
exclude = ["fixtures/large-export/**"]

[branding]
navy = "17324D"
teal = "007F82"

[executables]
dot = 'C:/tools/graphviz/bin/dot.exe'
```

Inspect the manifest's exclusion reasons. `exclude` adds path patterns; `prune_dirs` replaces the default cache/dependency directory-name list when those names mean something else in your repository. `exclude_generated_headers = false` disables the generated-header heuristic. Toolkit/VCS/credential protections remain enforced. Language controls Copilot-authored content and the Word language tag; generated audit labels remain English in v1.

- Missing dependencies: run `doctor` with the selected toolkit Python; install explicitly or set executable overrides. Do not install target-project dependencies.
- Source changed: `prepare --session TOKEN` rescans; affected extraction and all uncertain downstream dependencies are invalidated. Unchanged extraction is reused by fingerprint. Formatting-only changes require export, not new analysis.
- Interrupted chat: stop its workers, then `prepare --recover` creates a new coordinator lease. Keep valid results; do not edit shared state. `next` reissues the pending task. `recover-lock` only removes a command lock after its OS process has exited.
- Rejected result: fix the specific schema/evidence/range/citation error in the assigned result. Review repairs default to two cycles; then report the remaining blockage rather than loop forever.
- Too-large source line/task: the engine records a gap instead of claiming truncated coverage. For an oversized fact/section dependency, `repair --task ID --session TOKEN --reason "concrete budget failure"` permits a bounded correction with an audit trail. Narrow evidence or split the block; otherwise adjust explicit budgets within supported limits or request an incomplete draft. Do not silently narrow the denominator.
- Secrets: likely credential files never enter packets; other files undergo practical masking with stable line numbers. This is imperfect. Inspect exclusions and sensitivity before sharing a repository with Copilot.

## Development and acceptance

```powershell
python .github/skills/generate-documentation/setup.py --preview
python tools/package.py
python tools/test.py core
python tools/test.py integration
python tools/test.py smoke
```

Core tests require Python dependencies and Git; integration tests **require** Pandoc/Graphviz and fail if missing. Smoke also requires local PDF preview tools. CI has Windows/Linux core jobs and a provisioned Linux document-rendering job; it has not been remotely run as part of this build. Local test/version/layout results are recorded in [compatibility](docs/compatibility.md).

[Architecture, state, schemas and extension guidance](docs/architecture.md) explain the implementation and deliberate limits. [Live Copilot smoke steps](docs/live-copilot-smoke.md) cover actual skill invocation, native worker writes, semantic output and interrupt/resume. That live test remains separate from deterministic fixture tests; a local build cannot certify an unavailable authenticated Copilot integration.
