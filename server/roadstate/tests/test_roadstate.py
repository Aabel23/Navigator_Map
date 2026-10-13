"""Classifying, keeping and applying road conditions.

The rule this whole suite circles is the one that separates this block from
`traffic`: **a closure is a constraint, a condition is a cost.** Almost every
test below is a way of checking that the two never get mixed up, because the
mixed-up version does not crash -- it quietly routes a driver down a closed
street, or twenty kilometres around a queue.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain import BBox
from roadstate import (
    ConditionKind,
    RoadCondition,
    RoadStateSource,
    RoadStateStore,
    Severity,
    attribute,
    classify,
    classify_all,
)
from storage import InMemoryStorage

T0 = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
AREA = BBox(106.690, 10.760, 106.720, 10.790)


def report(**over):
    base = dict(
        id="r1",
        geometry=[[106.700, 10.770], [106.710, 10.770]],
        reported_at=T0,
        source="operator",
    )
    base.update(over)
    return base


@pytest.fixture
def store():
    backend = InMemoryStorage()
    backend.migrate()
    yield RoadStateStore(backend.documents, clock=lambda: T0)
    backend.close()


# --- Classification --------------------------------------------------------


def test_a_closure_is_recognised_and_always_blocking() -> None:
    condition = classify(report(title="Road closed after flooding"))
    assert condition.kind is ConditionKind.CLOSURE
    assert condition.blocking is True


def test_a_partial_closure_is_not_a_closure() -> None:
    """"Partially closed" contains "closed"; routing around it would be wrong."""
    condition = classify(report(title="Partially closed, one lane open"))
    assert condition.kind is not ConditionKind.CLOSURE
    assert condition.blocking is False


def test_flooding_is_recognised_from_its_kind() -> None:
    assert classify(report(kind="flooding", title="Water on road")).kind is ConditionKind.FLOODING


def test_deep_water_blocks_the_road() -> None:
    condition = classify(report(title="Flooded", depth_cm=45))
    assert condition.blocking is True
    assert condition.severity is Severity.CRITICAL


def test_shallow_water_slows_the_road_without_blocking_it() -> None:
    condition = classify(report(title="Flooded", depth_cm=10))
    assert condition.blocking is False
    assert condition.multiplier() > 1.0


def test_flooding_with_no_depth_falls_back_to_the_declared_severity() -> None:
    condition = classify(report(title="Flooded street", severity="high"))
    assert condition.kind is ConditionKind.FLOODING
    assert condition.severity is Severity.HIGH


def test_roadworks_are_recognised_and_are_not_blocking_by_default() -> None:
    condition = classify(report(kind="roadworks", title="Resurfacing"))
    assert condition.kind is ConditionKind.CONSTRUCTION
    assert condition.blocking is False


def test_works_severity_follows_how_many_lanes_are_left() -> None:
    full = classify(report(kind="roadworks", lanes_closed=2, lanes_total=2))
    half = classify(report(kind="roadworks", lanes_closed=1, lanes_total=4))
    assert full.severity is Severity.CRITICAL
    assert half.severity is Severity.MEDIUM


def test_anything_unrecognised_still_becomes_a_condition() -> None:
    condition = classify(report(title="Broken down lorry"))
    assert condition.kind is ConditionKind.INCIDENT


def test_a_surface_hazard_is_distinguished_from_a_vehicle_incident() -> None:
    assert classify(report(title="Debris on carriageway")).kind is ConditionKind.HAZARD


def test_classification_order_puts_closure_before_flooding() -> None:
    """A flooded street that is closed is closed. The stronger claim wins."""
    condition = classify(report(title="Street flooded and closed to traffic"))
    assert condition.kind is ConditionKind.CLOSURE


def test_one_malformed_report_does_not_cost_the_batch() -> None:
    good = report(id="ok")
    bad = {"id": "no-geometry", "reported_at": T0}
    assert [c.id for c in classify_all([good, bad])] == ["ok"]


def test_a_closure_that_is_not_blocking_is_a_contradiction() -> None:
    with pytest.raises(ValueError, match="closure that is not blocking"):
        RoadCondition(
            id="x",
            kind=ConditionKind.CLOSURE,
            severity=Severity.HIGH,
            geometry=((106.7, 10.77),),
            source="test",
            blocking=False,
        )


# --- Multipliers -----------------------------------------------------------


def test_a_blocking_condition_has_no_multiplier() -> None:
    """It is excluded by a constraint; a cost as well would be two mechanisms."""
    assert classify(report(title="Road closed")).multiplier() == 1.0


def test_worse_severity_costs_more() -> None:
    low = classify(report(kind="flooding", severity="low"))
    high = classify(report(kind="flooding", severity="high"))
    assert high.multiplier() > low.multiplier()


def test_every_multiplier_is_at_least_one() -> None:
    for kind in ConditionKind:
        for severity in Severity:
            condition = RoadCondition(
                id="x",
                kind=kind,
                severity=severity,
                geometry=((106.7, 10.77),),
                source="t",
                blocking=kind is ConditionKind.CLOSURE,
            )
            assert condition.multiplier() >= 1.0


# --- The store -------------------------------------------------------------


def test_a_condition_survives_the_round_trip(store) -> None:
    original = classify(report(road_ids=("way/1",), ends_at=T0 + timedelta(hours=2)))
    store.record([original])

    found = store.get(original.id)
    assert found == original


def test_recording_the_same_id_twice_replaces_it(store) -> None:
    store.record([classify(report(title="Road closed"))])
    store.record([classify(report(title="Road closed"))])
    assert store.count() == 1


def test_a_condition_outside_the_box_is_not_in_force_here(store) -> None:
    store.record([classify(report())])
    assert store.active_in(BBox(1.0, 1.0, 2.0, 2.0)) == ()


def test_a_condition_that_has_not_started_is_not_in_force(store) -> None:
    store.record([classify(report(starts_at=T0 + timedelta(hours=1)))])
    assert store.active_in(AREA) == ()


def test_a_condition_that_has_ended_is_not_in_force(store) -> None:
    store.record(
        [classify(report(starts_at=T0 - timedelta(hours=2), ends_at=T0 - timedelta(hours=1)))]
    )
    assert store.active_in(AREA) == ()


def test_an_open_ended_condition_stops_being_believed_eventually(store) -> None:
    """A crash nobody withdrew must not divert traffic for a week."""
    store.record([classify(report(reported_at=T0 - timedelta(hours=7)))])
    assert store.active_in(AREA) == ()


def test_an_open_ended_condition_is_believed_while_it_is_recent(store) -> None:
    store.record([classify(report(reported_at=T0 - timedelta(minutes=30)))])
    assert len(store.active_in(AREA)) == 1


def test_a_condition_with_an_end_time_is_honoured_however_old(store) -> None:
    store.record(
        [
            classify(
                report(
                    reported_at=T0 - timedelta(days=30),
                    starts_at=T0 - timedelta(days=30),
                    ends_at=T0 + timedelta(days=30),
                )
            )
        ]
    )
    assert len(store.active_in(AREA)) == 1


def test_withdrawing_removes_a_condition(store) -> None:
    condition = classify(report())
    store.record([condition])

    assert store.withdraw(condition.id) is True
    assert store.withdraw(condition.id) is False


# --- Attribution -----------------------------------------------------------


class Road:
    def __init__(self, rid, geometry):
        self.id = rid
        self.geometry = tuple(geometry)


ROADS = [
    Road("way/main", [(106.700, 10.770), (106.710, 10.770)]),
    Road("way/side", [(106.700, 10.780), (106.710, 10.780)]),
]


def test_a_condition_with_no_roads_is_attached_by_proximity() -> None:
    condition = classify(report(geometry=[[106.7001, 10.7701]]))
    assert attribute([condition], ROADS)[0].road_ids == ("way/main",)


def test_a_condition_that_names_its_roads_is_left_alone() -> None:
    """The source knew better than a proximity guess."""
    condition = classify(report(road_ids=("way/authoritative",)))
    assert attribute([condition], ROADS)[0].road_ids == ("way/authoritative",)


def test_a_long_condition_is_attached_along_its_whole_length() -> None:
    """Attaching only the midpoint would leave the rest of a closure open."""
    condition = classify(report(geometry=[[106.7001, 10.7701], [106.7001, 10.7801]]))
    assert set(attribute([condition], ROADS)[0].road_ids) == {"way/main", "way/side"}


def test_a_condition_nowhere_near_a_road_is_kept_but_unattached() -> None:
    """Still worth drawing: "there is a crash here" is useful without a road id."""
    condition = classify(report(geometry=[[106.60, 10.60]]))
    assert attribute([condition], ROADS)[0].road_ids == ()


# --- The provider ----------------------------------------------------------


class Edges:
    def __init__(self, fail_with=None):
        self.fail_with = fail_with

    def road_edges(self, area):
        if self.fail_with:
            raise self.fail_with
        return {"way/main": ("way/main#0", "way/main#1"), "way/side": ("way/side#0",)}


def test_a_closure_becomes_blocked_edges_not_a_cost(store) -> None:
    store.record([classify(report(title="Road closed", road_ids=("way/main",)))])
    source = RoadStateSource(store, Edges())

    assert source.blocked_edges(AREA) == frozenset({"way/main#0", "way/main#1"})
    assert source.multipliers_for(AREA) == {}


def test_a_non_blocking_condition_becomes_a_cost_not_a_block(store) -> None:
    store.record([classify(report(kind="roadworks", road_ids=("way/side",)))])
    source = RoadStateSource(store, Edges())

    assert source.blocked_edges(AREA) == frozenset()
    assert source.multipliers_for(AREA) == {"way/side#0": pytest.approx(1.6)}


def test_two_conditions_on_one_road_take_the_worse_not_the_product(store) -> None:
    """A crash and the queue behind it are one event reported twice."""
    store.record(
        [
            classify(report(id="a", kind="roadworks", severity="low", road_ids=("way/side",))),
            classify(report(id="b", kind="flooding", severity="high", road_ids=("way/side",))),
        ]
    )
    value = RoadStateSource(store, Edges()).multipliers_for(AREA)["way/side#0"]
    assert value == pytest.approx(4.0)


def test_a_missing_edge_mapping_fails_loudly_for_closures(store) -> None:
    """Returning an empty set would route a driver through a closure."""
    store.record([classify(report(title="Road closed", road_ids=("way/main",)))])
    source = RoadStateSource(store, Edges(fail_with=RuntimeError("no map")))

    with pytest.raises(RuntimeError):
        source.blocked_edges(AREA)


def test_a_missing_edge_mapping_degrades_quietly_for_costs(store) -> None:
    store.record([classify(report(kind="roadworks", road_ids=("way/side",)))])
    source = RoadStateSource(store, Edges(fail_with=RuntimeError("no map")))

    assert source.multipliers_for(AREA) == {}
