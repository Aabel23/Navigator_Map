"""Building a routable graph out of published ways.

The property under test throughout is the one the whole block exists for: a
*way* is not an *edge*. A way runs through junctions; an edge runs between
them. Get that wrong and the router sails past the turn it needed, which is
not a crash and does not fail any test that only checks a route came back.
"""

from __future__ import annotations

import pytest

from domain import BBox, GeoPoint
from mapdata import RoadGraphProvider, RoadSegment, build_graph, node_id_for
from mapdata.errors import MapDataError

AREA = BBox(106.690, 10.760, 106.720, 10.790)


def road(rid, points, **over):
    fields = dict(road_class="residential", free_flow_kph=30.0, name="")
    fields.update(over)
    return RoadSegment(id=rid, geometry=tuple(points), **fields)


class Net:
    def __init__(self, segments, fail_with=None):
        self.segments = segments
        self.calls = 0
        self.fail_with = fail_with

    def roads(self, bbox):
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        return self.segments


# --- Splitting -------------------------------------------------------------


def test_a_way_is_split_at_a_junction_another_way_shares() -> None:
    crossing = road("w/1", [(106.70, 10.77), (106.71, 10.77), (106.72, 10.77)])
    joining = road("w/2", [(106.71, 10.77), (106.71, 10.78)])

    build = build_graph([crossing, joining])

    assert sorted(e.id for e in build.graph.edges()) == ["w/1#0", "w/1#1", "w/2#0"]
    assert build.node_count == 4


def test_a_way_with_no_junction_in_it_stays_one_edge() -> None:
    build = build_graph([road("w/1", [(106.70, 10.77), (106.71, 10.77), (106.72, 10.77)])])
    assert [e.id for e in build.graph.edges()] == ["w/1#0"]


def test_the_intermediate_shape_is_kept_on_the_edge() -> None:
    """A route must be drawable without the graph, so the bend has to survive."""
    build = build_graph([road("w/1", [(106.70, 10.77), (106.705, 10.775), (106.71, 10.77)])])
    edge = next(build.graph.edges())
    assert len(edge.geometry) == 3


def test_two_ways_meeting_at_a_point_share_one_node() -> None:
    a = road("w/1", [(106.70, 10.77), (106.71, 10.77)])
    b = road("w/2", [(106.71, 10.77), (106.71, 10.78)])
    build = build_graph([a, b])

    shared = node_id_for((106.71, 10.77))
    edges = {e.id: e for e in build.graph.edges()}
    assert edges["w/1#0"].to_node == shared
    assert edges["w/2#0"].from_node == shared


def test_a_node_id_is_stable_across_builds() -> None:
    first = build_graph([road("w/1", [(106.70, 10.77), (106.71, 10.77)])])
    second = build_graph([road("w/1", [(106.70, 10.77), (106.71, 10.77)])])
    assert set(first.node_coords) == set(second.node_coords)


def test_a_closed_loop_is_skipped_rather_than_crashing() -> None:
    """routing.Edge refuses a self-loop; the builder must not hand it one."""
    build = build_graph([road("w/1", [(106.70, 10.77), (106.705, 10.775), (106.70, 10.77)])])
    assert build.edge_count == 0
    assert build.skipped == 1


def test_a_degenerate_way_is_skipped() -> None:
    class Degenerate:
        id = "w/bad"
        geometry = ((106.70, 10.77),)
        road_class = "residential"
        free_flow_kph = 30.0
        name = ""
        oneway = False

    build = build_graph([Degenerate()])
    assert build.edge_count == 0
    assert build.skipped == 1


# --- Edge facts ------------------------------------------------------------


def test_speed_is_converted_from_kph_to_metres_per_second() -> None:
    build = build_graph([road("w/1", [(106.70, 10.77), (106.71, 10.77)], free_flow_kph=36.0)])
    assert next(build.graph.edges()).speed == pytest.approx(10.0)


def test_a_one_way_becomes_a_one_way_edge() -> None:
    from routing import Direction

    build = build_graph([road("w/1", [(106.70, 10.77), (106.71, 10.77)], oneway=True)])
    assert next(build.graph.edges()).direction is Direction.ONE_WAY


def test_the_road_id_is_carried_on_the_edge() -> None:
    """Traffic and road state key by road; without this they cannot reach an edge."""
    build = build_graph([road("w/1", [(106.70, 10.77), (106.71, 10.77)])])
    assert next(build.graph.edges()).metadata["road_id"] == "w/1"


def test_coordinates_flip_to_routings_latitude_first_order() -> None:
    build = build_graph([road("w/1", [(106.70, 10.77), (106.71, 10.77)])])
    first = next(build.graph.edges()).geometry[0]
    assert (first.latitude, first.longitude) == (10.77, 106.70)


# --- The provider ----------------------------------------------------------


def test_the_built_graph_is_cached_per_area() -> None:
    net = Net(list(_town()))
    provider = RoadGraphProvider(net)

    provider.graph_for(AREA)
    provider.graph_for(AREA)

    assert net.calls == 1


def test_invalidate_forces_a_rebuild() -> None:
    net = Net(list(_town()))
    provider = RoadGraphProvider(net)

    provider.graph_for(AREA)
    provider.invalidate()
    provider.graph_for(AREA)

    assert net.calls == 2


def test_the_cache_is_bounded() -> None:
    net = Net(list(_town()))
    provider = RoadGraphProvider(net, cache_size=1)

    provider.graph_for(AREA)
    provider.graph_for(BBox(107.0, 11.0, 107.01, 11.01))
    provider.graph_for(AREA)

    assert net.calls == 3


def test_a_source_failure_becomes_one_map_data_error() -> None:
    """The routing service above must see one error type, not a source's own."""
    provider = RoadGraphProvider(Net([], fail_with=TimeoutError("upstream slow")))
    with pytest.raises(MapDataError, match="road network unavailable"):
        provider.graph_for(AREA)


def test_road_edges_maps_every_published_way_to_its_edges() -> None:
    provider = RoadGraphProvider(Net(list(_town())))
    mapping = provider.road_edges(AREA)

    assert mapping["way/AB"] == ("way/AB#0",)
    assert all(edge.startswith(road) for road, edges in mapping.items() for edge in edges)


# --- Snapping --------------------------------------------------------------


def test_a_coordinate_snaps_to_the_nearest_junction() -> None:
    view = RoadGraphProvider(Net(list(_town()))).graph_for(AREA)
    assert view.nearest_node(GeoPoint(106.7001, 10.7701), within_m=250) == node_id_for(
        (106.700, 10.770)
    )


def test_a_coordinate_too_far_from_the_network_snaps_to_nothing() -> None:
    """Better than a route that starts a kilometre from the driver."""
    view = RoadGraphProvider(Net(list(_town()))).graph_for(AREA)
    assert view.nearest_node(GeoPoint(106.60, 10.70), within_m=250) is None


def test_snapping_is_deterministic() -> None:
    view = RoadGraphProvider(Net(list(_town()))).graph_for(AREA)
    point = GeoPoint(106.7050, 10.7750)
    assert len({view.nearest_node(point) for _ in range(20)}) == 1


def _town():
    from tests.fixtures import town_roads

    return town_roads()
