# Fixture acceptance record

Checked on 2026-09-23 after adding incremental Word previews. Both documents use **hand-authored synthetic fixture artifacts**, not live Copilot output. These checks exercise deterministic processing and layout; they do not certify Copilot's semantic analysis.

## Executed checks

- Windows 11, Python 3.11.9: **17 core tests** and **11 document integration tests** passed, using actual Pandoc 3.11 and Graphviz 16.1.0.
- Ubuntu 24.04.2 under WSL, Python 3.12.3: **17 core tests** passed.
- `python tools/test.py smoke` exported both DOCX files and rendered them locally through LibreOffice 25.8.7.3 and PyMuPDF 1.28.2.
- The incremental regression completes one subsystem while another remains pending and a third is blocked. It checks the draft label/progress page, omitted unfinished chapters, embedded diagram, strict final-export refusal, and byte-for-byte preservation after Pandoc failure and a locked destination. A retry from saved state updates the preview without new analysis; an unchanged preview is reused. The large fixture checks that one reviewed section does not complete a multi-section subsystem and that source invalidation marks the saved preview historical.

| Document | Pages inspected | DOCX bookmarks / internal links | Tables / repeating headers | Embedded diagrams | Valid PDF internal links |
|---|---:|---:|---:|---:|---:|
| `documentation.docx` | 8 / 8 | 18 / 78 | 6 / 6 | 1 | 75 |
| `progress/documentation-progress.docx` | 8 / 8 | 17 / 75 | 6 / 6 | 1 | 73 |

All expected DOCX bookmark targets were present. PDF text checks found the final table row, preserved accented/Cyrillic text, valid link destinations and no text blocks outside page boundaries.

## Image inspection

**All 16 rendered page images were inspected.** Both documents have readable covers, visible linked contents, numbered headings, repeated table headers, long paths, Unicode, code, diagrams/captions and evidence notes. No visible clipping or overlap was found. The incremental document prominently says **Incomplete draft** and has a separate subsystem progress page. This single-subsystem style sample shows its completed chapter before overview synthesis; the multi-subsystem regression exercises nonempty pending and blocked rows.

The diagram geometry check reports 14-point effective text. Editable specifications/DOT, SVG and PNG are included. Actual image inspection is recorded separately in each document's `preview/preview.json` and `build.json`; generation-time layout labels inside the unchanged DOCX remain historical. Neither DOCX was modified after rendering. Human approval is **not assigned**.

## Artifact identity and limits

- Final DOCX SHA-256: `b8ad336620b0c8794c956115c39f1e2bfce3780c5da0d13a4418ea8c80f82fab`
- Incremental DOCX SHA-256: `5d5ad6449f693c49ad9e32e35126fdb4c614546371b72dc1364946db4baec52d`
- Release ZIP SHA-256: `365f3ec23cb3ffeb0c46bbf46ae4d24a0df871ad746ec032cdcb4e5040bef45d`

Before the initial Git publication on 2026-09-24, runtime text and sample Markdown were normalized to LF so Git checkout preserves installer ownership and sample file hashes. The release ZIP and sample metadata were updated; the inspected DOCX/PDF/page-image bytes were unchanged.

Inspection used LibreOffice-rendered pages, not Microsoft Word's desktop renderer. Live authenticated Copilot invocation, native worker writes/provider inheritance and Copilot interrupt/resume remain unverified. Remote CI, native Linux document rendering, the Poppler alternative and macOS execution were not run here. See [the live smoke procedure](../../docs/live-copilot-smoke.md) and [compatibility record](../../docs/compatibility.md).
