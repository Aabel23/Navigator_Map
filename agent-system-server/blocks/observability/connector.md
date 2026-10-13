# observability — Connector

## Responsibility

Decide how a log line is shaped and where it goes, and define what "is this
server working" means.

## Inputs

- a log level and a format choice, from `config`
- health checks, registered by whoever composed the server

## Outputs

- `configure(level, as_json)` — sets up the server logger, once
- `get_logger(name)` — a child of it, so configuration applies
- `HealthRegistry` — `register(name, check, critical=)`, `ready()`

## Connectors

### `observability → everything`
Any block may call `get_logger`. None is instrumented from here.

### `api → observability`
The composition root calls `configure` at startup and registers the checks
this particular server should be able to pass.

## Stable guarantees consumers may rely on

- `configure` is safe to call twice; the second call replaces the handlers
  rather than adding a second set.
- The server logger does not propagate to the root, so a library that logs
  elsewhere is unaffected by what this server decided.
- A JSON line carries `time`, `level`, `logger`, `message`, plus any `extra`
  fields merged in — so a structured query can find a value without parsing
  prose.
- A health check that raises is reported as failed with its exception as the
  detail. A health endpoint that can itself fail is worse than useless during
  an incident.
- A failing **non-critical** check degrades rather than failing readiness. A
  missing traffic feed must not take a serving process out of rotation.

## Boundary rule

No subsystem calls `logging.basicConfig`. A library that configures the root
logger takes the decision away from whoever imported it, and the symptom —
duplicated lines, or a level nobody set — appears far from the cause.

What is worth logging is a block's own decision. Nothing here reaches into one
to instrument it.

## Forbidden internal details

- the formatter classes and the field-filtering rule
- how checks are stored or ordered

## Inside the block

```text
observability/
├── __init__.py      the public surface
├── logging.py       configure(), get_logger(), JsonFormatter
└── health.py        Check, CheckResult, HealthRegistry
```

**How they work together.** They do not — deliberately. `logging.py` and
`health.py` share nothing but the block they live in, because they are the two
halves of one question asked by two different audiences: a human reading a log,
and a load balancer reading a status code. Keeping them in one block keeps both
answers configured in one place at startup; keeping them in separate modules
keeps a change to log shape from touching readiness.
