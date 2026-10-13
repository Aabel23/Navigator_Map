"""Attaching, classifying, holding and pricing traffic.

The four steps, in order, with the rules that are easy to get wrong and
invisible when they are:

* attaching a measurement to the *wrong* road, which invents a jam
* letting a model displace a sensor, which hides a real one
* serving a stale reading, which routes on history
* pricing standstill as impassable, which sends a driver round the city
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain import BBox
from traffic import (
    RoadIndex,
    RoadSpeed,
    TrafficCostSource,
    TrafficLevel,
    TrafficState,
    attach,
    level_for_ratio,
    level_for_speed,
    multiplier_for_ratio,
)

T0 = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
AREA = BBox(106.690, 10.760, 106.720, 10.790)


class Road:
    def __init__(self, rid, geometry, free_flow_kph=50.0):
        self.id = rid
        self.geometry = tuple(geometry)
        self.free_flow_kph = free_flow_kph


ROADS = [
    Road("way/main", [(106.700, 10.770), (106.710, 10.770)], 60.0),
    Road("way/side", [(106.700, 10.780), (106.710, 10.780)], 30.0),
]


class Observation:
    def __init__(self, point, speed_kph, source="sensor", confidence=1.0, at=T0, free_flow=None):
        self.point = point
        self.speed_kph = speed_kph
        self.source = source
        self.confidence = confidence
        self.observed_at = at
        self.free_flow_kph = free_flow


class Segment:
    def __init__(self, geometry, speed_kph, road_id=None, source="sensor", at=T0, free_flow=None):
        self.geometry = tuple(geometry)
        self.speed_kph = speed_kph
        self.road_id = road_id
        self.source = source
        self.observed_at = at
        self.free_flow_kph = free_flow
        self.confidence = 1.0


class Batch:
    def __init__(self, source="sensor", segments=(), observations=()):
        self.source = source
        self.segments = tuple(segments)
        self.observations = tuple(observations)


# --- Levels ----------------------------------------------------------------


@pytest.mark.parametrize(
    "ratio,expected",
    [
        (1.0, TrafficLevel.FREE_FLOW),
        (0.9, TrafficLevel.FREE_FLOW),
        (0.7, TrafficLevel.LIGHT),
        (0.5, TrafficLevel.MODERATE),
        (0.3, TrafficLevel.HEAVY),
        (0.1, TrafficLevel.STANDSTILL),
    ],
)
def test_a_ratio_classifies_to_its_level(ratio, expected) -> None:
    assert level_for_ratio(ratio) is expected


def test_no_reading_is_unknown_rather_than_free_flowing() -> None:
    assert level_for_ratio(None) is TrafficLevel.UNKNOWN
    assert level_for_speed(40.0, None) is TrafficLevel.UNKNOWN


def test_unknown_never_compares_as_congestion() -> None:
    assert TrafficLevel.UNKNOWN < TrafficLevel.FREE_FLOW


# --- Cost ------------------------------------------------------------------


def test_half_speed_costs_twice() -> None:
    assert multiplier_for_ratio(0.5) == pytest.approx(2.0)


def test_free_flow_costs_nothing_extra() -> None:
    assert multiplier_for_ratio(1.0) == 1.0


def test_traffic_faster_than_free_flow_never_speeds_a_road_up() -> None:
    """Below 1.0 would make routing's A* heuristic inadmissible."""
    assert multiplier_for_ratio(1.5) == 1.0


def test_standstill_is_capped_rather_than_infinite() -> None:
    """A jam is not a closure; treating it as one sends a driver round the city."""
    assert multiplier_for_ratio(0.001) == 8.0


def test_no_reading_costs_nothing() -> None:
    assert multiplier_for_ratio(None) == 1.0


# --- Attaching -------------------------------------------------------------


def test_a_point_observation_snaps_to_the_nearest_road() -> None:
    batch = Batch(observations=[Observation((106.7001, 10.7701), 30.0)])
    readings = attach([batch], RoadIndex(ROADS))
    assert set(readings) == {"way/main"}


def test_an_observation_far_from_every_road_is_dropped() -> None:
    """A reading attributed to a street 800 m away invents a jam."""
    batch = Batch(observations=[Observation((106.60, 10.60), 30.0)])
    assert attach([batch], RoadIndex(ROADS)) == {}


def test_a_segment_that_names_its_road_is_believed() -> None:
    batch = Batch(
        segments=[Segment([(106.60, 10.60), (106.61, 10.60)], 20.0, road_id="way/side")]
    )
    readings = attach([batch], RoadIndex(ROADS))
    assert set(readings) == {"way/side"}


def test_the_free_flow_reference_comes_from_the_road_when_absent() -> None:
    batch = Batch(observations=[Observation((106.7001, 10.7701), 30.0)])
    reading = attach([batch], RoadIndex(ROADS))["way/main"]
    assert reading.free_flow_kph == 60.0
    assert reading.ratio == pytest.approx(0.5)


def test_a_measurement_beats_a_model_for_the_same_road() -> None:
    measured = Batch("sensor", observations=[Observation((106.7001, 10.7701), 50.0)])
    modelled = Batch(
        "simulated",
        observations=[Observation((106.7001, 10.7701), 10.0, source="simulated", confidence=0.15)],
    )

    for order in ([measured, modelled], [modelled, measured]):
        reading = attach(order, RoadIndex(ROADS))["way/main"]
        assert reading.source == "sensor"


def test_readings_that_disagree_are_ranked_not_averaged() -> None:
    """An average of a sensor and a model is a number with no honest source."""
    low = Batch("a", observations=[Observation((106.7001, 10.7701), 10.0, confidence=0.3)])
    high = Batch("b", observations=[Observation((106.7001, 10.7701), 50.0, confidence=0.9)])

    reading = attach([low, high], RoadIndex(ROADS))["way/main"]
    assert reading.speed_kph == 50.0


def test_an_observation_with_no_speed_contributes_nothing() -> None:
    batch = Batch(observations=[Observation((106.7001, 10.7701), None)])
    assert attach([batch], RoadIndex(ROADS)) == {}


# --- State -----------------------------------------------------------------


def test_a_reading_expires_rather_than_going_stale() -> None:
    now = T0
    state = TrafficState(max_age_s=300.0, clock=lambda: now)
    state.apply([Batch(observations=[Observation((106.7001, 10.7701), 30.0, at=T0)])], ROADS)
    assert len(state.fresh()) == 1

    now = T0 + timedelta(seconds=301)
    assert state.fresh() == {}
    assert state.expire() == 1


def test_a_fresh_model_does_not_displace_a_recent_sensor_reading() -> None:
    """Recent and true are different properties, and only one matters here."""
    state = TrafficState(clock=lambda: T0 + timedelta(minutes=1))
    state.apply([Batch("sensor", observations=[Observation((106.7001, 10.7701), 50.0)])], ROADS)
    state.apply(
        [
            Batch(
                "simulated",
                observations=[
                    Observation(
                        (106.7001, 10.7701),
                        5.0,
                        source="simulated",
                        confidence=0.15,
                        at=T0 + timedelta(seconds=59),
                    )
                ],
            )
        ],
        ROADS,
    )
    assert state.fresh()["way/main"].source == "sensor"


def test_a_failure_is_recorded_and_reported_not_swallowed() -> None:
    state = TrafficState(clock=lambda: T0)
    state.record_failure("digitraffic", "timed out")

    snapshot = state.snapshot(AREA)
    assert snapshot.failures == (("digitraffic", "timed out"),)


def test_a_failure_clears_once_the_source_answers_again() -> None:
    state = TrafficState(clock=lambda: T0)
    state.record_failure("digitraffic", "timed out")
    state.clear_failures("digitraffic")
    assert state.snapshot(AREA).failures == ()


def test_a_snapshot_is_limited_to_the_roads_it_was_given() -> None:
    state = TrafficState(clock=lambda: T0)
    state.apply(
        [
            Batch(
                observations=[
                    Observation((106.7001, 10.7701), 30.0),
                    Observation((106.7001, 10.7801), 10.0),
                ]
            )
        ],
        ROADS,
    )
    snapshot = state.snapshot(AREA, [ROADS[0]])
    assert [speed.road_id for speed in snapshot.speeds] == ["way/main"]


def test_a_snapshot_of_only_modelled_readings_says_so() -> None:
    state = TrafficState(clock=lambda: T0)
    state.apply(
        [
            Batch(
                "simulated",
                observations=[
                    Observation((106.7001, 10.7701), 10.0, source="simulated", confidence=0.15)
                ],
            )
        ],
        ROADS,
    )
    assert state.snapshot(AREA).is_simulated is True


def test_worst_first_puts_the_jam_at_the_top() -> None:
    state = TrafficState(clock=lambda: T0)
    state.apply(
        [
            Batch(
                observations=[
                    Observation((106.7001, 10.7701), 58.0),
                    Observation((106.7001, 10.7801), 4.0),
                ]
            )
        ],
        ROADS,
    )
    assert state.snapshot(AREA).worst_first()[0].road_id == "way/side"


# --- The cost provider -----------------------------------------------------


class Edges:
    def __init__(self, mapping=None, fail_with=None):
        self.mapping = mapping or {
            "way/main": ("way/main#0", "way/main#1"),
            "way/side": ("way/side#0",),
        }
        self.fail_with = fail_with

    def road_edges(self, area):
        if self.fail_with:
            raise self.fail_with
        return self.mapping


def test_a_road_reading_becomes_a_multiplier_on_every_edge_of_that_road() -> None:
    state = TrafficState(clock=lambda: T0)
    state.apply([Batch(observations=[Observation((106.7001, 10.7701), 30.0)])], ROADS)

    multipliers = TrafficCostSource(state, Edges()).multipliers_for(AREA)

    assert multipliers == {"way/main#0": pytest.approx(2.0), "way/main#1": pytest.approx(2.0)}


def test_an_edge_with_no_reading_is_absent_not_one_point_zero() -> None:
    """Absent already means free flow to the cost model; a full table costs for nothing."""
    state = TrafficState(clock=lambda: T0)
    state.apply([Batch(observations=[Observation((106.7001, 10.7701), 30.0)])], ROADS)

    assert "way/side#0" not in TrafficCostSource(state, Edges()).multipliers_for(AREA)


def test_a_free_flowing_road_produces_no_entry() -> None:
    state = TrafficState(clock=lambda: T0)
    state.apply([Batch(observations=[Observation((106.7001, 10.7701), 60.0)])], ROADS)
    assert TrafficCostSource(state, Edges()).multipliers_for(AREA) == {}


def test_every_multiplier_is_at_least_one() -> None:
    """routing.DynamicCostModel rejects anything lower, and would be right to."""
    state = TrafficState(clock=lambda: T0)
    state.apply([Batch(observations=[Observation((106.7001, 10.7701), 200.0)])], ROADS)
    assert all(v >= 1.0 for v in TrafficCostSource(state, Edges()).multipliers_for(AREA).values())


def test_a_missing_edge_mapping_degrades_to_no_traffic_not_an_error() -> None:
    state = TrafficState(clock=lambda: T0)
    state.apply([Batch(observations=[Observation((106.7001, 10.7701), 30.0)])], ROADS)

    source = TrafficCostSource(state, Edges(fail_with=RuntimeError("no map")))
    assert source.multipliers_for(AREA) == {}


def test_an_empty_state_asks_the_edge_index_for_nothing() -> None:
    class Boom:
        def road_edges(self, area):
            raise AssertionError("must not be asked when there is nothing to say")

    assert TrafficCostSource(TrafficState(), Boom()).multipliers_for(AREA) == {}


# --- Models ----------------------------------------------------------------


def test_a_naive_observation_time_is_refused() -> None:
    with pytest.raises(ValueError, match="naive"):
        RoadSpeed(
            road_id="r", speed_kph=10, free_flow_kph=50, observed_at=datetime(2026, 1, 1), source="x"
        )


def test_a_non_positive_free_flow_is_refused() -> None:
    with pytest.raises(ValueError, match="free flow"):
        RoadSpeed(road_id="r", speed_kph=10, free_flow_kph=0, observed_at=T0, source="x")
