"""Block tests for turn legality: restrictions, U-turns, and dead ends.

These are the reason a search state is ``(via_edge, node)`` rather than a bare
node. Whether leaving a junction into a given street is legal depends on the
street you arrived by, so a node-only search cannot express any of this.
"""

import pytest

from routing import (
    Edge,
    InMemoryRoadGraph,
    NoRouteFound,
    Node,
    RouteRequest,
    Router,
    TurnKind,
    TurnRestriction,
)

from .fixtures import small_town_graph, town_with_turn_restrictions


# --- Prohibited and mandatory turns ----------------------------------------


def test_a_prohibited_turn_forces_a_detour():
    """Without the restriction B reaches F straight through E on Le Loi."""
    plain = Router(graph=small_town_graph()).find(RouteRequest(origin="B", destination="F"))
    assert plain.segments == ("BE", "EF")

    restricted = Router(graph=town_with_turn_restrictions()).find(
        RouteRequest(origin="B", destination="F")
    )
    assert restricted.segments == ("BC", "CF")
    assert restricted.total_cost > plain.total_cost


def test_a_mandatory_turn_forbids_continuing_straight():
    """Arriving at E on DE, the only permitted exit is EH."""
    restricted = Router(graph=town_with_turn_restrictions())
    route = restricted.find(RouteRequest(origin="D", destination="F", cost_mode="shortest"))
    assert ("DE", "EF") != route.segments[:2]
    assert route.nodes[-1] == "F"


def test_a_restriction_binds_only_its_own_approach():
    """The prohibition is on BE into EF; arriving on EH, the turn is fine."""
    router = Router(graph=town_with_turn_restrictions())
    route = router.find(RouteRequest(origin="H", destination="F", cost_mode="shortest"))
    assert route.segments == ("EH", "EF")


def test_a_restriction_that_severs_the_graph_yields_no_route():
    graph = _corridor()
    graph.add_turn_restriction(TurnRestriction("e0", "n1", "e1", TurnKind.PROHIBITED))
    with pytest.raises(NoRouteFound):
        Router(graph=graph).find(RouteRequest(origin="n0", destination="n2"))


def test_turn_restrictions_do_not_change_an_unaffected_route():
    plain = Router(graph=small_town_graph()).find(RouteRequest(origin="A", destination="D"))
    restricted = Router(graph=town_with_turn_restrictions()).find(
        RouteRequest(origin="A", destination="D")
    )
    assert plain.segments == restricted.segments


# --- U-turns ---------------------------------------------------------------


def test_a_route_does_not_reverse_when_it_has_no_need_to():
    route = Router(graph=_t_junction()).find(RouteRequest(origin="n0", destination="n2"))
    assert route.segments == ("e0", "e1")
    assert len(set(route.segments)) == len(route.segments)


def test_a_dead_end_is_exempt_from_the_u_turn_rule():
    """Turning round in a cul-de-sac is not a manoeuvre the driver chose.

    The mandatory restriction at n1 forces the route down the spur to n2;
    n2 is a dead end, so coming back out of it is allowed without the caller
    having to ask for U-turns at all.
    """
    route = Router(graph=_forced_detour(dead_end=True)).find(
        RouteRequest(origin="n0", destination="n3")
    )
    assert route.segments == ("e0", "e1", "e1", "e2")


def test_a_reversal_at_a_live_junction_needs_permission():
    """Same shape, but n2 has a second arm, so it is not a dead end."""
    with pytest.raises(NoRouteFound):
        Router(graph=_forced_detour(dead_end=False)).find(
            RouteRequest(origin="n0", destination="n3")
        )


def test_allow_u_turns_opens_the_reversal():
    route = Router(graph=_forced_detour(dead_end=False)).find(
        RouteRequest(origin="n0", destination="n3", allow_u_turns=True)
    )
    assert route.segments == ("e0", "e1", "e1", "e2")


# --- Fixtures --------------------------------------------------------------


def _corridor() -> InMemoryRoadGraph:
    """n0 -- n1 -- n2, a straight run with dead ends at both tips."""
    graph = InMemoryRoadGraph()
    for index in range(3):
        graph.add_node(Node(f"n{index}", 10.0, 106.0 + index * 0.01))
    graph.add_edge(Edge("e0", "n0", "n1", distance=1096, speed=10, name="Main"))
    graph.add_edge(Edge("e1", "n1", "n2", distance=1096, speed=10, name="Main"))
    return graph


def _t_junction() -> InMemoryRoadGraph:
    """n0 -- n1 -- n2 with a third arm at n1, so n1 is not a dead end."""
    graph = _corridor()
    graph.add_node(Node("n3", 10.01, 106.01))
    graph.add_edge(Edge("e2", "n1", "n3", distance=1106, speed=10, name="Side"))
    return graph


def _forced_detour(*, dead_end: bool) -> InMemoryRoadGraph:
    """A layout where the only way on is back the way you came.

        n0 --e0-- n1 --e1-- n2 (--e3-- n4, only when dead_end is False)
                   |
                  e2
                   |
                  n3

    Leaving n0 there is one road. A mandatory restriction at n1 says that
    arriving on e0 the only permitted exit is e1, so the route is pushed out
    to n2 before it can ever turn down e2 toward n3. Getting back is a
    reversal along e1 -- free at a dead end, and otherwise only with
    ``allow_u_turns``. With ``dead_end=False`` a further prohibition stops the
    search escaping through e3 instead.
    """
    graph = _t_junction()
    graph.add_turn_restriction(TurnRestriction("e0", "n1", "e1", TurnKind.MANDATORY))
    if dead_end:
        return graph
    graph.add_node(Node("n4", 10.01, 106.02))
    graph.add_edge(Edge("e3", "n2", "n4", distance=1106, speed=10, name="Back Lane"))
    graph.add_turn_restriction(TurnRestriction("e1", "n2", "e3", TurnKind.PROHIBITED))
    return graph
