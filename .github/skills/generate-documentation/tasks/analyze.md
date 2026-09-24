# Extract evidence-backed facts · version 1

Analyze every supplied chunk, using its exact path/hash/range/chunk ID. List all chunk IDs in `chunks`. Every chunk needs evidence tied to at least one fact; an empty file can support the narrow observed fact that it is empty. Never substitute a manifest listing or empty fact sheet for analysis. Do not paraphrase every line.

Return evidence, stable facts and typed relations. Cover relevant responsibilities, public/exported interfaces (inputs and outputs, shape, source/destination and timing), configuration names/usage without values that may be secret, data contracts, imports, entry points, state transitions, effects, errors/retries, concurrency/idempotency, and explicit rationale. In `categories`, describe the relevant fact IDs or precisely why that category is inapplicable/unresolved. Trivial modules need few facts, not manufactured complexity.

Every detected entry/trigger is a separate `entry-point` fact, including multiple triggers declaring the same handler. A static import is an `import` relation, not automatically a call or network connection. Relation endpoints are eligible file paths or `external:description`; dependencies outside a selected folder remain external to this scope. Dynamic injection, reflection, generated names or missing external config can stay unresolved. Tests express expectations; declarations express intended resources, not deployed names. README intent cannot silently overrule implementation.

Use fact statuses/bases and conflict IDs precisely. Explanations say why an inference follows or what an unknown needs. Summary retains the key fact IDs. If chunk boundaries hide a signature/transition, request bounded registered evidence through the coordinator, then use the updated packet fingerprint.

When `repair_findings` are supplied, correct the underlying facts against original evidence and return the complete revised shard. Do not force an author to preserve an incorrect fact. Keep supported IDs stable; the engine invalidates downstream content when this acceptance changes.
