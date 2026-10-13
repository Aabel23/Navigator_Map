# Code Rules

1. One folder = one primary responsibility.
2. Keep modules, functions, and interfaces focused.
3. Prefer explicit data flow over hidden global state.
4. Do not duplicate domain rules across blocks.
5. Do not depend on another block's private/internal implementation.
6. External systems must cross a small, explicit interface.
7. Preserve existing behavior unless the task explicitly changes it.
8. New behavior requires appropriate tests.
9. Do not silently change a public connector/interface.
10. A connector change is an architectural change and must be checked against all consumers.
11. Internal refactors are allowed when documented connectors remain compatible.
12. Configuration must not be hard-coded into domain logic.
13. Do not introduce infrastructure, frameworks, or new blocks without a concrete requirement.
14. Performance work must have a measurable requirement or benchmark.
15. Avoid circular dependencies.


## Change flow
READ → SCOPE → PLAN → IMPLEMENT → TEST → REVIEW → UPDATE DOCS IF NEEDED → COMMIT

# Scope
## Single-Block Session Rule

In one chat session or chat box, the agent must work on **one single block only**.

The agent must:

* Identify the target block before starting work.
* Read and modify only files belonging to that block.
* Keep all reasoning, implementation, testing, and changes focused on the target block.

The agent must **not read, inspect, modify, or refactor other blocks** unless doing so is strictly required to understand or verify an explicitly documented connector/interface of the target block.

When another block must be inspected, the agent should read only the **minimum connector/interface documentation required**. Do not inspect its implementation unless the task explicitly requires a cross-block change.

A task that requires changing responsibilities, connectors, or implementation across multiple blocks is **not a single-block task**. Stop and report the required cross-block change before proceeding.

The goal is to keep each block independently understandable, testable, replaceable, and refactorable without unnecessary coupling.

## Connector documentation rule

Every block must contain `connector.md`.

`connector.md` must identify, at minimum:

- block responsibility
- inputs
- outputs
- connector/interface names
- data or type exchanged
- direction
- consumer/provider relationship
- stable guarantees that consumers may rely on
- forbidden internal details

Other blocks may rely only on documented connectors and public interfaces.

They must not rely on:

- private functions
- internal modules
- internal database structures
- implementation-specific files
- incidental behavior not documented by the connector

## Refactor rule

A block may be internally reorganized, optimized, or rewritten without changing consumers when its documented connector contract remains compatible.

If the connector must change, stop treating the work as a normal refactor. Update the architecture/connection documentation and verify every affected consumer.