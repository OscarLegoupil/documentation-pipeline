# Maintenance chapter pattern · version 1

Use the following logical order, with repository-supported content only. The engine supplies headings and numbering; model blocks use ordinary Markdown and fact links.

1. Where it fits: responsibility, upstream/downstream ownership and constraints.
2. Inputs table: Input | Type / Shape | Source | When | Source note.
3. Outputs table: Output | Type / Shape | Destination | When | Source note.
4. Optional focused context diagram specification, then significant workflows.
5. Important interfaces/components, configuration and data contracts.
6. State/lifecycle, failure handling, retries, concurrency/idempotency where applicable.
7. Maintenance implications: safe change boundaries, test expectations, contradictions and unknowns.

The component index is generated from reconciled ownership; trivial helpers need only a concise placement/reason. Cross-cutting chapters are justified by real ownership, not a catch-all category. Tests and deployment declarations are static evidence only. Omit meaningless cloud tables and isolated-utility diagrams. Tables require citations on each factual body row. Source notes become unobtrusive evidence links in the document.
