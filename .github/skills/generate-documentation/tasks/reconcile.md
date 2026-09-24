# Reconcile ownership and relationships · version 1

Read the accepted analysis shard. Use bounded `lookup` through the coordinator for related facts and prior ownership shards; reconcile subsystem slug consistency across actual APIs/ownership, not just directory prefixes. Ask for registered targeted source ranges when declarations and implementations disagree. Do not read the entire repository or all fact sheets.

Assign each `owner_paths` entry exactly once in `ownership` with path, subsystem, reason, fact IDs, unresolved boolean. Oversized files have one primary placement even if analyzed in several packets. Retain uncertain ownership visibly instead of guessing. Cross references may be numerous. Every entry-point fact in this shard must get an `entry_points` row: fact, actual component, owning subsystem, supported downstream relation IDs, and concrete unresolved string (use an empty string when resolved).

Add only new supported typed relations (do not duplicate extraction relation IDs); imports, calls, events, queues, storage, schema, config and deployment declarations are distinct. Include evidence through fact IDs. Keep declaration vs runtime distinctions. Record conflicts with both fact IDs, resolution/explanation and resolved boolean; no unsupported arbitration. Extra source outside scope remains registered external evidence, never added silently to coverage.

When repairing, resolve supplied findings against the underlying facts/source and return the complete revised ownership/relationship shard. Unsupported original facts require repair of their analysis task through the coordinator.
