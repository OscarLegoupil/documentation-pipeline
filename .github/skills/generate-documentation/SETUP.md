# Copy, set up, run

Requires Python 3.11+, Pandoc 3.x and Graphviz `dot`. Python 3.11.9, Pandoc 3.11 and Graphviz 16.1.0 were exercised during this build; see the toolkit repository's compatibility record for the full check status. This folder is the entire runtime. No Copilot CLI, API credentials, model SDK or target dependencies are needed.

From an extracted release, Windows PowerShell first:

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

Manual installation: copy this **single folder** to `.github/skills/generate-documentation/` in the target. If that destination exists, use the installer for conflict-aware upgrade. Do not merge/overwrite a customized skill silently. The installer touches only owned files and leaves existing instructions/settings/docs/application files alone. A modified owned file blocks the whole installation; inspect and retain your edits or choose a separate checkout before retrying. `.toolkit-manifest.json` records version and original hashes. Environment/setup records are not portable: run setup again after moving the folder.

`setup.py` explicitly downloads hash-locked Python wheels into this folder's `.venv`; it does not activate it, change global PATH or install target packages. Use its recorded `python` executable thereafter. For air-gapped setup, pre-download the locked wheels for the destination OS/Python with `pip download --require-hashes --only-binary=:all: -r requirements.lock -d wheelhouse`, then run `setup.py --wheelhouse /path/to/wheelhouse`. Optional preview wheels also need `requirements-preview.lock`.

On Debian/Ubuntu, the chosen Python installation also needs its matching `python3-venv`/`ensurepip` package. If setup reports that it is missing, install that prerequisite explicitly through your approved system administration process; the toolkit does not change system packages.

Install external tools explicitly through approved organizational channels or official distributions: [Pandoc](https://pandoc.org/installing.html), [Graphviz](https://graphviz.org/download/), optional [LibreOffice](https://www.libreoffice.org/download/). On Windows, portable ZIP tools can remain in a local tools directory. On macOS/Linux, an approved package manager is also suitable. No installer runs automatically. Doctor reports missing executables; configure absolute executable paths in optional target `docgen.toml` if they are not on PATH:

```toml
[executables]
pandoc = 'C:/tools/pandoc/pandoc.exe'
dot = 'C:/tools/graphviz/bin/dot.exe'
soffice = 'C:/tools/LibreOffice/program/soffice.exe'
```

Local visual preview needs LibreOffice plus either `pdftoppm` (Poppler) or the optional pinned PyMuPDF renderer (`setup.py --preview`). PyMuPDF is distributed separately under its upstream license. Basic Word export does not require either preview tool and reports layout QA pending. All document/diagram processing stays local; there are no remote fonts, images, diagram services or telemetry in the toolkit. Copilot uses its normal online service.

Open the target in VS Code. Select **GitHub Copilot** as the agent/provider and a subscription-available model. Invoke `/generate-documentation`. Optional examples: `scope=src`, `action=status`, `action=validate`, `action=export`. These are plain skill arguments interpreted by Copilot, not editor command flags. The same command resumes matching work in a new chat after stopping the previous coordinator. No prompt file or global instructions are installed.

For direct inspection, use the recorded Python with `docgen.py --root /repo [--scope src] status`. `prepare` returns a coordinator session token; keep it for `next`, `accept`, `repair`, `lookup --task` and `evidence`. Recover a stopped chat with `prepare --recover`. Never recover a still-running coordinator. Every command emits JSON; use `--help` for arguments. `export` only rebuilds accepted artifacts and never invokes a model. A user-requested draft uses `export --partial` and is conspicuously named `DRAFT-INCOMPLETE.docx`.

Generated state lives in `.docgen/runs/<scope-id>/`; documents live in `docs/generated/<scope-id>/build-*/`. No automatic Git edits occur. You can manually add these paths to ignore rules according to your repository's policy; the toolkit self-excludes them regardless. Source hashes, accepted facts and reviews remain auditable on disk. Coverage is accounting, not proof of comprehension or correctness.
