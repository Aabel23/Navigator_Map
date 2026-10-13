"""Unit tests for cost models, vehicle profiles, and the A*-safety flags."""

import pytest

from routing import (
    Access,
    CallableCostModel,
    CostContext,
    CostMode,
    DynamicCostModel,
    Edge,
    InvalidRequest,
    StaticCostModel,
    VehicleProfile,
    get_vehicle_profile,
)


@pytest.fixture
def edge():
    return Edge("e1", "A", "B", distance=100.0, speed=10.0, road_class="residential")


@pytest.fixture
def car():
    return CostContext(profile=get_vehicle_profile("car"))


# --- Vehicle profiles ------------------------------------------------------


def test_unknown_profile_name_is_a_routing_error():
    """A KeyError here would escape the block's error hierarchy."""
    with pytest.raises(InvalidRequest):
        get_vehicle_profile("spaceship")


def test_profile_rejects_a_non_positive_speed_factor():
    with pytest.raises(ValueError):
        VehicleProfile(name="stopped", speed_factor=0.0)


def test_profile_rejects_a_penalty_below_one():
    """A bonus, rather than a penalty, would break the heuristic's lower bound."""
    with pytest.raises(ValueError, match="inadmissible"):
        VehicleProfile(name="odd", road_class_penalties={"highway": 0.5})


def test_profile_road_class_restriction(edge):
    restricted = VehicleProfile(name="highway_only", allowed_road_classes=frozenset({"highway"}))
    assert not restricted.may_use(edge)
    assert get_vehicle_profile("car").may_use(edge)


# --- Static costs ----------------------------------------------------------


def test_shortest_mode_costs_distance(edge, car):
    assert StaticCostModel(CostMode.SHORTEST).edge_cost(edge, car) == pytest.approx(100.0)


def test_fastest_mode_costs_time(edge, car):
    assert StaticCostModel(CostMode.FASTEST).edge_cost(edge, car) == pytest.approx(10.0)


def test_speed_factor_changes_time_cost(edge):
    slow = CostContext(profile=VehicleProfile(name="slow", speed_factor=0.5))
    assert StaticCostModel(CostMode.FASTEST).edge_cost(edge, slow) == pytest.approx(20.0)


def test_penalty_multiplies_cost_but_not_travel_time(edge):
    """A penalty says a road is undesirable, not that driving it takes longer."""
    context = CostContext(
        profile=VehicleProfile(name="cautious", road_class_penalties={"residential": 2.0})
    )
    model = StaticCostModel(CostMode.FASTEST)
    assert model.edge_cost(edge, context) == pytest.approx(20.0)
    assert model.travel_time(edge, context) == pytest.approx(10.0)


def test_blocked_edge_costs_infinity(car):
    blocked = Edge("e2", "A", "B", distance=100.0, speed=10.0, access=Access.BLOCKED)
    assert StaticCostModel(CostMode.FASTEST).edge_cost(blocked, car) == float("inf")


def test_disallowed_road_class_costs_infinity(edge):
    context = CostContext(
        profile=VehicleProfile(name="highway_only", allowed_road_classes=frozenset({"highway"}))
    )
    assert StaticCostModel(CostMode.FASTEST).edge_cost(edge, context) == float("inf")


def test_unknown_cost_mode_is_a_routing_error():
    with pytest.raises(InvalidRequest):
        StaticCostModel("cheapest")


def test_static_model_declares_its_unit():
    assert StaticCostModel(CostMode.SHORTEST).mode is CostMode.SHORTEST


def test_turn_cost_and_turn_time_are_zero_by_default(edge, car):
    model = StaticCostModel(CostMode.FASTEST)
    assert model.turn_cost(edge, "B", edge, car) == 0.0
    assert model.turn_time(edge, "B", edge, car) == 0.0


# --- Dynamic costs ---------------------------------------------------------


def test_dynamic_without_multipliers_matches_its_base(edge, car):
    base = StaticCostModel(CostMode.FASTEST)
    assert DynamicCostModel(base).edge_cost(edge, car) == pytest.approx(base.edge_cost(edge, car))


def test_dynamic_multiplier_scales_cost_and_time(edge, car):
    base = StaticCostModel(CostMode.FASTEST)
    congested = DynamicCostModel(base, {"e1": 3.0})
    assert congested.edge_cost(edge, car) == pytest.approx(base.edge_cost(edge, car) * 3.0)
    assert congested.travel_time(edge, car) == pytest.approx(base.travel_time(edge, car) * 3.0)


def test_dynamic_preserves_an_infinite_base_cost(edge):
    context = CostContext(profile=VehicleProfile(name="none", allowed_road_classes=frozenset()))
    congested = DynamicCostModel(StaticCostModel(CostMode.FASTEST), {"e1": 3.0})
    assert congested.edge_cost(edge, context) == float("inf")


def test_dynamic_rejects_a_multiplier_below_one():
    """Conditions may slow a road down; they may not beat its free-flow speed."""
    with pytest.raises(ValueError, match="inadmissible"):
        DynamicCostModel(StaticCostModel(CostMode.FASTEST), {"e1": 0.5})


def test_with_multipliers_returns_a_new_model(edge, car):
    base = DynamicCostModel(StaticCostModel(CostMode.FASTEST), {"e1": 2.0})
    updated = base.with_multipliers({"e1": 4.0})
    assert base.edge_cost(edge, car) == pytest.approx(20.0)
    assert updated.edge_cost(edge, car) == pytest.approx(40.0)


def test_dynamic_inherits_its_base_unit():
    assert DynamicCostModel(StaticCostModel(CostMode.SHORTEST)).mode is CostMode.SHORTEST


# --- Callable model --------------------------------------------------------


def test_callable_model_wraps_a_function(edge, car):
    model = CallableCostModel(lambda e, ctx: e.distance * 2)
    assert model.edge_cost(edge, car) == pytest.approx(200.0)


def test_callable_model_opts_out_of_astar():
    """An arbitrary function cannot promise the bound A* relies on."""
    assert CallableCostModel(lambda e, ctx: 1.0).admits_astar is False
    assert StaticCostModel(CostMode.FASTEST).admits_astar is True
