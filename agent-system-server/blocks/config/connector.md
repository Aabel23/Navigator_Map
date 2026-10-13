# config — Connector

## Responsibility

Hold everything a deployment may change, read it once, and refuse what it
cannot use.

No module below this one reads the environment. A subsystem that did would be
untestable without setting a variable and undiscoverable without grepping for
one.

## Inputs

- environment variables, all prefixed `MAP_`
- nothing else

## Outputs

- `Settings` — a frozen dataclass whose field list *is* the configuration
  surface. There is no other knob.
- `SettingsError` — raised at startup when a value cannot be used

## Connectors

### `config → api`
The composition root reads settings once and hands each block what it needs.

### `config → everything else`
Indirectly, through constructor arguments. No block reads settings itself.

## Stable guarantees consumers may rely on

- Every setting has a default that works. A fresh checkout with no environment
  starts, fetches map data, models traffic and answers a route request.
- An unreadable value raises at startup, naming the variable. A server that
  silently ran on the default port because `MAP_PORT` was `"eight thousand"`
  would be found out much later, by someone else.
- Naming a storage backend that has no adapter fails at startup, not at the
  first query.
- Booleans accept `1/true/yes/on` and their negatives, case insensitive.
- `describe()` returns configuration as plain data for the health endpoint,
  and is the place anything secret must be redacted.

## Boundary rule

Configuration must not be hard-coded into domain logic, and domain logic must
not appear here. This block converts strings into values and checks them; it
decides nothing those values feed.

## Forbidden internal details

- how coercion works
- the `MAP_` prefix as a thing to construct rather than to read

## Inside the block

```text
config/
├── __init__.py    the public surface: Settings, SettingsError
└── settings.py    the field list, the parsers, and from_env()
```

**How they work together.** There is one real module. `settings.py` declares
every configurable value as a dataclass field with its default, and
`from_env()` walks those fields, reads `MAP_<NAME>` for each, converts it, and
raises `SettingsError` naming the variable if the conversion fails. Adding a
setting is adding a field; nothing else changes, and nothing has to be
registered anywhere.

The ones that most change behaviour:

```bash
MAP_STORAGE_BACKEND=sqlite      # or memory
MAP_DATABASE_PATH=data/server.db
MAP_DEFAULT_AREA=106.675,10.758,106.725,10.798
MAP_TRAFFIC_ENABLED=1           # price routes with live traffic
MAP_TRAFFIC_SIMULATED=1         # model traffic where no feed covers the area
MAP_DIGITRAFFIC_ENABLED=1       # Finland's free, keyless sensor feed
MAP_ROADSTATE_ENABLED=1         # let closures affect routes
```
