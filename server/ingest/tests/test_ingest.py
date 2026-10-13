"""The door: what gets in, what gets refused, and what happens when a feed dies.

Ingest is the only place in the server that touches untrusted input, so most
of this suite is about refusal. The rest is about the collector's three
policies -- coverage routing, measured before modelled, and a failure that
does not take the rest down with it -- each of which only shows up when
something goes wrong, which is exactly when nobody is testing by hand.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain import BBox
from ingest import (
    Observations,
    TrafficObservation,
    TrafficCollector,
    TrafficProvider,
    normalize_report,
    normalize_reports,
    parse_probe,
    probes_to_observations,
)
from ingest.errors import BadResponse, ProviderUnavailable

NOW = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
AREA = BBox(106.690, 10.760, 106.720, 10.790)
FINLAND = BBox(19.0, 59.5, 31.7, 70.2)


def raw_probe(**over):
    base = {
        "device_id": "d1",
        "lon": 106.70,
        "lat": 10.77,
        "speed_kph": 24.0,
        "observed_at": NOW.isoformat(),
    }
    base.update(over)
    return base


# --- GPS probes ------------------------------------------------------------


def test_a_well_formed_probe_is_accepted() -> None:
    probe = parse_probe(raw_probe(), now=NOW)
    assert probe.point == (106.70, 10.77)
    assert probe.speed_kph == 24.0


def test_a_probe_with_no_position_is_refused() -> None:
    with pytest.raises(BadResponse, match="position"):
        parse_probe({"observed_at": NOW.isoformat()}, now=NOW)


def test_a_swapped_coordinate_pair_is_refused() -> None:
    """106.7 as a latitude lands in the Gulf of Guinea and looks like a road."""
    with pytest.raises(BadResponse, match="out of range"):
        parse_probe(raw_probe(lon=10.77, lat=106.70), now=NOW)


def test_a_naive_timestamp_is_refused_rather_than_assumed() -> None:
    with pytest.raises(BadResponse, match="timezone"):
        parse_probe(raw_probe(observed_at="2026-09-13T08:00:00"), now=NOW)


def test_a_probe_from_the_future_is_refused() -> None:
    with pytest.raises(BadResponse, match="future"):
        parse_probe(raw_probe(observed_at=(NOW + timedelta(hours=1)).isoformat()), now=NOW)


def test_a_probe_too_old_to_matter_is_refused() -> None:
    with pytest.raises(BadResponse, match="too old"):
        parse_probe(raw_probe(observed_at=(NOW - timedelta(hours=1)).isoformat()), now=NOW)


def test_an_implausible_speed_is_dropped_but_the_probe_is_kept() -> None:
    """The position is still good; one bad reading should not cost it."""
    probe = parse_probe(raw_probe(speed_kph=900.0), now=NOW)
    assert probe.speed_kph is None


def test_a_stationary_probe_is_not_congestion() -> None:
    """A car park full of parked cars is not a traffic jam."""
    probe = parse_probe(raw_probe(speed_kph=0.5), now=NOW)
    batch = probes_to_observations([probe])
    assert batch.observations == ()


def test_moving_probes_become_observations() -> None:
    batch = probes_to_observations([parse_probe(raw_probe(), now=NOW)])
    assert len(batch.observations) == 1
    assert batch.observations[0].source == "gps-probe"


def test_a_probe_observation_carries_no_free_flow_reference() -> None:
    """A probe knows its own speed and nothing about what the road can do."""
    batch = probes_to_observations([parse_probe(raw_probe(), now=NOW)])
    assert batch.observations[0].free_flow_kph is None


def test_probe_confidence_sits_between_a_model_and_a_sensor() -> None:
    from ingest import PROBE_CONFIDENCE

    assert 0.15 < PROBE_CONFIDENCE < 1.0


# --- Incident reports ------------------------------------------------------


def test_a_point_report_is_accepted_as_lon_lat() -> None:
    report = normalize_report({"id": "1", "lon": 106.7, "lat": 10.77}, now=NOW)
    assert report["geometry"] == [[106.7, 10.77]]


def test_a_report_with_no_id_is_refused() -> None:
    with pytest.raises(BadResponse, match="no id"):
        normalize_report({"lon": 106.7, "lat": 10.77}, now=NOW)


def test_a_report_with_no_geometry_is_refused() -> None:
    with pytest.raises(BadResponse, match="geometry"):
        normalize_report({"id": "1"}, now=NOW)


def test_a_report_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(BadResponse, match="ends before"):
        normalize_report(
            {
                "id": "1",
                "lon": 106.7,
                "lat": 10.77,
                "starts_at": NOW,
                "ends_at": NOW - timedelta(hours=1),
            },
            now=NOW,
        )


def test_provenance_is_stamped_on_every_report() -> None:
    report = normalize_report({"id": "1", "lon": 106.7, "lat": 10.77}, source="operator", now=NOW)
    assert report["source"] == "operator"
    assert report["id"].startswith("operator:")


def test_an_id_that_already_carries_its_source_is_not_prefixed_twice() -> None:
    report = normalize_report({"id": "digitraffic:abc", "lon": 106.7, "lat": 10.77}, now=NOW)
    assert report["id"] == "digitraffic:abc"


def test_ingest_makes_no_judgement_about_what_a_report_means() -> None:
    """Kind and severity pass through as text. `roadstate` decides."""
    report = normalize_report(
        {"id": "1", "lon": 106.7, "lat": 10.77, "kind": "FLOODING", "severity": "HIGH"}, now=NOW
    )
    assert report["kind"] == "flooding"
    assert report["severity"] == "high"


def test_a_batch_returns_both_what_passed_and_why_the_rest_did_not() -> None:
    good, bad = normalize_reports([{"id": "1", "lon": 106.7, "lat": 10.77}, {"id": "2"}])
    assert len(good) == 1
    assert len(bad) == 1


# --- The collector ---------------------------------------------------------


class Fake(TrafficProvider):
    def __init__(self, name, area=None, empty=False, raises=None):
        self.name = name
        self._area = area
        self._empty = empty
        self._raises = raises
        self.calls = 0

    def coverage(self):
        return self._area

    def fetch(self, bbox):
        self.calls += 1
        if self._raises:
            raise self._raises
        if self._empty:
            return Observations.empty(bbox, self.name)
        return Observations(
            bbox=bbox,
            source=self.name,
            observed_at=NOW,
            observations=(
                TrafficObservation(
                    id=f"{self.name}:1",
                    point=bbox.center,
                    observed_at=NOW,
                    source=self.name,
                    speed_kph=30.0,
                ),
            ),
        )


def test_a_provider_outside_its_coverage_is_not_asked() -> None:
    """A Finnish sensor network asked about Vietnam should say "not mine"."""
    finland = Fake("digitraffic", area=FINLAND)
    collection = TrafficCollector([finland]).collect(AREA)

    assert finland.calls == 0
    assert collection.skipped == ("digitraffic",)


def test_a_provider_inside_its_coverage_is_asked() -> None:
    finland = Fake("digitraffic", area=FINLAND)
    TrafficCollector([finland]).collect(BBox(24.6, 60.1, 25.2, 60.35))
    assert finland.calls == 1


def test_the_fallback_is_used_only_when_nothing_measured_answered() -> None:
    simulated = Fake("simulated")
    collection = TrafficCollector(
        [Fake("digitraffic", area=FINLAND)], fallback=simulated
    ).collect(AREA)

    assert simulated.calls == 1
    assert collection.sources == ("simulated",)


def test_the_fallback_never_competes_with_a_measurement() -> None:
    simulated = Fake("simulated")
    TrafficCollector([Fake("sensors")], fallback=simulated).collect(AREA)
    assert simulated.calls == 0


def test_an_empty_measured_answer_still_lets_the_fallback_run() -> None:
    """A covering provider with nothing to say is not the same as coverage."""
    simulated = Fake("simulated")
    TrafficCollector([Fake("sensors", empty=True)], fallback=simulated).collect(AREA)
    assert simulated.calls == 1


def test_one_provider_failing_does_not_stop_the_others() -> None:
    collection = TrafficCollector(
        [Fake("broken", raises=ProviderUnavailable("timed out")), Fake("working")]
    ).collect(AREA)

    assert collection.sources == ("working",)
    assert collection.failures == (("broken", "timed out"),)


def test_a_provider_raising_something_unexpected_is_still_contained() -> None:
    collection = TrafficCollector([Fake("buggy", raises=KeyError("oops"))]).collect(AREA)
    assert collection.failures[0][0] == "buggy"
    assert "KeyError" in collection.failures[0][1]


def test_failures_are_reported_rather_than_logged_and_forgotten() -> None:
    """A city that looks clear because a feed timed out is worse than one that says so."""
    collection = TrafficCollector(
        [Fake("broken", raises=ProviderUnavailable("timed out"))]
    ).collect(AREA)
    assert collection.meta()["failures"] == [{"provider": "broken", "error": "timed out"}]
