"""One question in, every provider's answer out -- and none of their failures.

A caller wants the traffic for a box. It does not want to know that Finland
has a sensor network and Vietnam does not, that one provider needs a padded
box and another needs a station list fetched first, or that one of them is
down right now.

This is the module that turns a list of providers into that single answer, and
it carries exactly three policies -- the same three the old single-block
traffic store carried, which were the part of it worth keeping:

* **Coverage routing.** A provider that declares a region is only asked about
  boxes inside it. That is what makes a world made of national open-data feeds
  usable at all: a Finnish sensor network asked about Ho Chi Minh City should
  say "not mine", not return an empty result that reads like a free-flowing
  city.
* **Measured before modelled.** A fallback provider is consulted only where no
  measuring provider produced anything. Real numbers are never diluted with
  invented ones, and the simulated provider never competes with a sensor.
* **A failure is not fatal.** A provider that raises is dropped from that
  refresh and recorded by name. A route without traffic is worse than one with
  it; a route that never computes is worse than both. The failures are
  returned rather than logged and forgotten, because a map that quietly shows
  an empty city because a feed timed out is worse than one that says so.

Note the module path. ``ingest/traffic/`` is the *ingestion* of traffic data;
the top-level ``traffic`` block is what interprets it. They are different
blocks with confusingly adjacent names, and a module here that wants the other
one is almost certainly a boundary violation rather than a missing import.

Inputs:  a bounding box, and a list of TrafficProvider
Outputs: Observations batches, one per provider that answered, plus failures
Not here: levels, road attachment, cost -- every one of those is `traffic`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from domain import BBox

from ..errors import IngestError
from ..models import Observations
from ..provider import TrafficProvider

__all__ = ["Collection", "TrafficCollector"]


@dataclass(frozen=True, slots=True)
class Collection:
    """What one refresh produced.

    Attributes:
        area: The box asked about.
        batches: One per provider that answered, in the order asked.
        failures: ``(provider name, message)`` for each that did not.
        skipped: Providers that declined the box as outside their coverage.
            Not a failure -- a provider saying "not mine" is the system
            working.
    """

    area: BBox
    batches: tuple[Observations, ...] = ()
    failures: tuple[tuple[str, str], ...] = ()
    skipped: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return all(batch.is_empty for batch in self.batches)

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(batch.source for batch in self.batches)

    def counts(self) -> dict[str, int]:
        totals = {"segments": 0, "observations": 0, "incidents": 0}
        for batch in self.batches:
            for key, value in batch.counts().items():
                totals[key] += value
        return totals

    def incidents(self) -> tuple:
        return tuple(
            incident for batch in self.batches for incident in batch.incidents
        )

    def meta(self) -> dict[str, object]:
        return {
            "area": list(self.area.as_tuple()),
            "sources": list(self.sources),
            "skipped": list(self.skipped),
            "counts": self.counts(),
            "failures": [{"provider": name, "error": text} for name, text in self.failures],
        }


class TrafficCollector:
    """Asks the providers that cover a box, and survives the ones that do not.

    Args:
        providers: Measuring providers, in preference order.
        fallback: Consulted only when no measuring provider returned anything
            for the box. This is where a modelled provider belongs, and the
            "only when" is what keeps it from competing with a sensor.
    """

    def __init__(
        self,
        providers: Sequence[TrafficProvider] = (),
        *,
        fallback: TrafficProvider | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._fallback = fallback

    @property
    def providers(self) -> tuple[TrafficProvider, ...]:
        """Every provider, fallback last. Read-only."""
        if self._fallback is None:
            return self._providers
        return self._providers + (self._fallback,)

    def collect(self, area: BBox) -> Collection:
        """Fetch from every provider covering ``area``."""
        batches: list[Observations] = []
        failures: list[tuple[str, str]] = []
        skipped: list[str] = []
        measured = False

        for provider in self._providers:
            if not provider.covers(area):
                skipped.append(provider.name)
                continue
            batch = self._try(provider, area, failures)
            if batch is None:
                continue
            batches.append(batch)
            measured = measured or not batch.is_empty

        if not measured and self._fallback is not None:
            if self._fallback.covers(area):
                batch = self._try(self._fallback, area, failures)
                if batch is not None:
                    batches.append(batch)
            else:
                skipped.append(self._fallback.name)

        return Collection(
            area=area,
            batches=tuple(batches),
            failures=tuple(failures),
            skipped=tuple(skipped),
        )

    def describe(self) -> dict[str, object]:
        return {
            "providers": [p.name for p in self._providers],
            "fallback": self._fallback.name if self._fallback else None,
        }

    def _try(
        self, provider: TrafficProvider, area: BBox, failures: list[tuple[str, str]]
    ) -> Observations | None:
        try:
            return provider.fetch(area)
        except IngestError as err:
            failures.append((provider.name, str(err)))
            return None
        except Exception as err:  # noqa: BLE001 - a provider bug must not stop the rest
            failures.append((provider.name, f"{type(err).__name__}: {err}"))
            return None
