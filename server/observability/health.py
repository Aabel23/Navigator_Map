"""Health: what is wired up, and whether it works.

Two questions, and conflating them is how a deployment ends up restarting a
process that was fine:

* **Live** -- is this process running and able to answer at all? Nothing is
  checked. If the handler runs, the answer is yes.
* **Ready** -- can it do its job right now? Every registered check runs. A
  server whose database is unreachable is live but not ready, and should stop
  receiving traffic without being killed.

A check is a function returning ``(ok, detail)``. It must not raise -- one that
does is reported as failed with its exception as the detail, because a health
endpoint that can itself fail is worse than useless during an incident.

Checks are *registered* rather than discovered. What a server should be able to
do depends on how it was composed, and a check that scanned for subsystems
would report a missing traffic source as healthy on a server that never had
one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Mapping

__all__ = ["Check", "HealthRegistry", "CheckResult"]

CheckFn = Callable[[], "tuple[bool, object]"]


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: object = None
    duration_ms: float = 0.0
    critical: bool = True

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "critical": self.critical,
            "detail": self.detail,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass(frozen=True, slots=True)
class Check:
    """One named thing that can be verified.

    Attributes:
        name: Appears in the response. Keep it stable; a dashboard keys on it.
        run: Returns ``(ok, detail)``.
        critical: Whether failing makes the whole server not ready. A missing
            traffic feed is not critical -- routes still compute, on free-flow
            speeds -- and reporting it as a hard failure would take a working
            server out of rotation over a degraded feature.
    """

    name: str
    run: CheckFn
    critical: bool = True


class HealthRegistry:
    """The checks this particular server was composed with."""

    def __init__(self) -> None:
        self._checks: list[Check] = []

    def register(self, name: str, run: CheckFn, *, critical: bool = True) -> None:
        self._checks.append(Check(name=name, run=run, critical=critical))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(check.name for check in self._checks)

    def run(self) -> tuple[CheckResult, ...]:
        results: list[CheckResult] = []
        for check in self._checks:
            started = time.perf_counter()
            try:
                ok, detail = check.run()
            except Exception as err:  # noqa: BLE001 - a health check must not raise
                ok, detail = False, f"{type(err).__name__}: {err}"
            results.append(
                CheckResult(
                    name=check.name,
                    ok=bool(ok),
                    detail=detail,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    critical=check.critical,
                )
            )
        return tuple(results)

    def ready(self) -> tuple[bool, dict[str, object]]:
        """Whether every critical check passes, and the full report."""
        results = self.run()
        ok = all(result.ok for result in results if result.critical)
        degraded = [r.name for r in results if not r.ok and not r.critical]
        return ok, {
            "ready": ok,
            "degraded": degraded,
            "checks": [result.to_payload() for result in results],
        }
