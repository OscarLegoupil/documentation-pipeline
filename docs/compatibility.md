# Compatibility and acceptance record

Official integration documentation was rechecked on **2026-09-23**. This record distinguishes documentation-backed syntax from actual local and live integration tests.

| Component / environment | Version or target | Check status |
|---|---|---|
| Windows 11 x64 | 10.0.26200 | Local deterministic and document integration tests executed |
| Python, Windows | 3.11.9 | Toolkit-local setup, strict dependency lock, CLI and export exercised |
| Ubuntu under WSL | 24.04.2, Python 3.12.3 | Local core suite executed; native Linux rendering tools not installed |
| Pandoc, Windows | 3.11 | Actual AST parsing, Markdown/DOCX export and bookmark tests |
| Graphviz, Windows | 16.1.0 (20260904.0139) | Actual local SVG/200-DPI PNG generation and geometry checks |
| LibreOffice, Windows | 25.8.7.3 | Local administrative extraction; isolated DOCX-to-PDF preview exercised |
| PDF rasterizer | PyMuPDF 1.28.2 | Local page images generated from the fixture PDF |
| Poppler alternative | `pdftoppm` CLI | Implemented; provisioned in Linux CI, not locally executed |
| VS Code executable | 1.137.0, commit 645f29cc3176500b4b5762ba887cf2a7f0ffdf2c | Version detected only; no authenticated Copilot session exposed to this build |
| Copilot skill / native workers | Current documented VS Code interfaces | Live invocation/provider inheritance/file writes/interrupt-resume **not verified**; follow the live smoke procedure |
| macOS | Python 3.11+, Pandoc 3.x, Graphviz | Portable implementation; no macOS host was available for execution |
| Remote GitHub Actions | Windows/Linux core matrix; provisioned Ubuntu rendering job | Configuration supplied; **not remotely run** |

The WSL distribution lacked `ensurepip`/the matching `python3-venv` OS package. For local core tests only, a workspace-local development venv was seeded with a hash-verified pip wheel; no global Linux packages were installed. Normal Debian/Ubuntu setup requires that explicit prerequisite as documented in the portable setup guide. Linux/macOS wheels are included in the lock's permitted release hashes; availability for every future Python/platform combination is not promised. Python 3.11–3.13 are the intended v1 range; CI exercises 3.11 and 3.13 when run.

## Evidence of implementation checks

The core suite checks Git/non-Git inventories, ignored-but-tracked inclusion, source redaction, symlink/junction containment, missing LFS/submodule material, unsupported encodings/unreadable source, volume/range accounting (300 small files plus 5,000 source lines), stale/fabricated evidence rejection, stopped-session resume and conflicting coordinators, Unicode installation and preservation, process failures/timeouts/encoding errors, strict configuration, shipped skill resources, release ownership hashes, and the absence of runtime model/network clients.

The integration suite requires real Pandoc and Graphviz and fails if absent. It checks fixture pipelines, a larger generated multi-packet workflow with interruption and safe cache reuse, add/delete/rename/shared-contract invalidation, formatting-only reuse, bounded semantic repairs, cross-subsystem calls/declarations/conflicts/unknowns, strict/draft export, missing tools, malformed Markdown/diagrams, corrupted accepted artifacts, actual DOCX headings/bookmarks/internal hyperlinks/images/tables, and rebuilding without network or model requests. Incremental export tests cover completed/pending/blocked chapters, all-section review gates, preservation on Pandoc/replacement failures, and retry without reanalysis. It does not certify semantic intelligence.

`python tools/test.py smoke` produces both the final hand-authored fixture sample and its automatic incremental preview under `samples/maintenance-style/progress/`, with local PDFs and page images. Each companion `preview/preview.json` records rendering and actual inspection separately. [Test counts and observations from all 16 inspected pages](../samples/maintenance-style/ACCEPTANCE.md) are recorded alongside the samples. Human approval remains unassigned. Word-specific structure was checked in the actual DOCX ZIPs; visual pages were rendered by LibreOffice, not certified by a live Microsoft Word desktop session.

## Integration syntax and primary sources

- VS Code documents `.github/skills/<name>/SKILL.md`, slash invocation, `user-invocable`, `disable-model-invocation`, and experimental fork context. The shipped skill uses the two invocation controls and avoids fork context. [Agent skills](https://code.visualstudio.com/docs/agent-customization/agent-skills)
- Prompt files are deprecated/not loaded for Agent Host sessions; the Local agent still supports them. This product ships no prompt file or duplicate slash command. [Prompt files](https://code.visualstudio.com/docs/agent-customization/prompt-files)
- Native subagent support and available tools depend on the host. The documented invocation is `runSubagent` under `agent`; workers inherit the main model unless overridden. The skill inspects actual availability and keeps provider/model inheritance. [Subagents](https://code.visualstudio.com/docs/agents/run/subagents)
- GitHub documents project skills and VS Code agent mode support. The toolkit targets that editor experience; no CLI or cloud-agent runner is included. [GitHub agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills)
- Custom agents can alter tools/models; none are required or installed here. [Custom agents](https://code.visualstudio.com/docs/agent-customization/custom-agents)
- Pandoc documents reference DOCX, AST/filter support and TOC instructions. The exporter instead builds a visible linked contents baseline and checks the resulting Word bookmarks. [Pandoc manual](https://pandoc.org/MANUAL.html)
- Graphviz supplies local SVG and PNG output. [Output formats](https://graphviz.org/docs/outputs/)
- PyMuPDF supplies the optional local PDF rasterizer. [Installation and platform support](https://pymupdf.readthedocs.io/en/latest/installation.html)

The skill's `argument-hint`, `user-invocable` and `disable-model-invocation` fields follow the official VS Code documentation and are checked by the repository's Copilot-frontmatter/resource test. That deterministic check does not substitute for live skill-discovery testing.

## Locked tooling

Core Python releases are pinned with hashes for all published wheels: python-docx 1.2.0; lxml 6.1.3; typing_extensions 4.16.0; jsonschema 4.26.0; attrs 26.1.0; jsonschema-specifications 2025.9.1; referencing 0.37.0; rpds-py 2026.6.3. The last six support strict JSON Schema validation; python-docx/lxml provide narrow Word finishing. Optional PyMuPDF 1.28.2 is in a separate lock. Setup uses `--require-hashes --only-binary=:all:` and doctor checks the installed core versions against the lock.

External binaries are explicitly installed and version-reported, not silently downloaded at runtime. Pandoc 3.x is required; the fully provisioned CI rendering job selects 3.11 and its OS Graphviz/LibreOffice packages. This is tested-content reproducibility, not a promise of byte-identical DOCX ZIPs across fonts/OS/tool versions or deterministic new Copilot prose. Development download/provision scripts are outside the release runtime.
