"""The shared vocabulary, and the proximity search built on it.

Small types, but everything above depends on them being exactly right. A
bounding box that got ``intersects`` subtly wrong would show up as missing
roads at a tile edge; a spatial index that stopped widening a ring too early
would show up as a route starting at the wrong junction, occasionally.
"""

from __future__ import annotations

import pytest

from domain import BBox, GeoPoint, SpatialIndex, densify, haversine_m, index_of_polylines

HCMC = BBox(106.675, 10.758, 106.725, 10.798)


# --- GeoPoint --------------------------------------------------------------


def test_a_swapped_pair_is_refused_rather_than_landing_in_the_atlantic() -> None:
    with pytest.raises(ValueError, match="latitude"):
        GeoPoint(10.77, 106.70)


def test_a_point_parses_from_a_query_string() -> None:
    assert GeoPoint.parse("106.70,10.77") == GeoPoint(106.70, 10.77)


def test_distance_is_in_metres() -> None:
    a = GeoPoint(106.700, 10.770)
    b = GeoPoint(106.710, 10.770)
    assert 1000 < a.distance_to(b) < 1200


# --- BBox ------------------------------------------------------------------


def test_a_box_parses_from_west_south_east_north() -> None:
    assert BBox.parse("106.675,10.758,106.725,10.798") == HCMC


def test_an_inverted_box_is_refused() -> None:
    with pytest.raises(ValueError, match="east of"):
        BBox(2.0, 0.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="north of"):
        BBox(0.0, 2.0, 1.0, 1.0)


def test_a_wrong_length_string_is_refused() -> None:
    with pytest.raises(ValueError, match="west,south,east,north"):
        BBox.parse("106.7,10.7")


def test_two_boxes_sharing_only_an_edge_intersect() -> None:
    assert HCMC.intersects(BBox(106.725, 10.758, 106.8, 10.798))


def test_disjoint_boxes_do_not_intersect() -> None:
    assert not HCMC.intersects(BBox(1.0, 1.0, 2.0, 2.0))


def test_covering_points_produces_a_box_that_holds_them() -> None:
    points = [(106.70, 10.77), (106.71, 10.78)]
    area = BBox.covering(points, pad_degrees=0.01)
    assert all(area.contains(point) for point in points)
    assert area.west < 106.70


def test_covering_nothing_is_an_error_rather_than_the_whole_world() -> None:
    with pytest.raises(ValueError, match="empty"):
        BBox.covering([])


def test_quantizing_rounds_outward_so_a_cached_area_is_never_too_small() -> None:
    area = BBox(106.6751, 10.7581, 106.7249, 10.7979).quantized(2)
    assert area.west <= 106.6751
    assert area.east >= 106.7249


def test_quantizing_makes_nearby_boxes_share_a_key() -> None:
    a = BBox(106.7001, 10.7701, 106.7099, 10.7799).quantized(2)
    b = BBox(106.7002, 10.7702, 106.7098, 10.7798).quantized(2)
    assert a.as_tuple() == b.as_tuple()


# --- SpatialIndex ----------------------------------------------------------


def test_an_empty_index_finds_nothing() -> None:
    assert SpatialIndex([]).nearest((106.7, 10.77)) is None


def test_the_nearest_label_wins() -> None:
    index = SpatialIndex([("near", (106.7001, 10.77)), ("far", (106.75, 10.77))])
    assert index.nearest_label((106.70, 10.77)) == "near"


def test_a_limit_excludes_everything_beyond_it() -> None:
    index = SpatialIndex([("far", (106.75, 10.77))])
    assert index.nearest_label((106.70, 10.77), within_m=100) is None


def test_the_search_widens_past_its_own_cell() -> None:
    """A candidate one cell over must still be found."""
    index = SpatialIndex([("next-cell", (106.709, 10.77))])
    assert index.nearest_label((106.7001, 10.77), within_m=2000) == "next-cell"


def test_a_tie_is_broken_deterministically() -> None:
    index = SpatialIndex([("b", (106.70, 10.77)), ("a", (106.70, 10.77))])
    assert {index.nearest_label((106.70, 10.77)) for _ in range(20)} == {"a"}


def test_the_reported_distance_matches_the_geometry() -> None:
    index = SpatialIndex([("x", (106.71, 10.77))])
    label, metres = index.nearest((106.70, 10.77))
    assert label == "x"
    assert metres == pytest.approx(haversine_m((106.70, 10.77), (106.71, 10.77)))


def test_within_lists_the_labels_inside_a_box() -> None:
    index = SpatialIndex([("in", (106.70, 10.77)), ("out", (1.0, 1.0))])
    assert index.within(HCMC) == ("in",)


def test_an_unbounded_search_terminates_when_nothing_is_near() -> None:
    index = SpatialIndex([("x", (0.0, 0.0))])
    assert index.nearest_label((106.70, 10.77)) == "x"


# --- Polyline indexing -----------------------------------------------------


class Road:
    def __init__(self, rid, geometry):
        self.id = rid
        self.geometry = tuple(geometry)


def test_a_point_beside_the_middle_of_a_long_span_still_finds_its_road() -> None:
    """A vertex-only index would measure this as half a kilometre away."""
    road = Road("way/long", [(106.700, 10.770), (106.710, 10.770)])
    index = index_of_polylines([road])
    assert index.nearest_label((106.705, 10.7701), within_m=120) == "way/long"


def test_densifying_leaves_no_gap_wider_than_the_step() -> None:
    filled = densify([(106.700, 10.770), (106.710, 10.770)], step_m=50.0)
    gaps = [haversine_m(filled[i], filled[i + 1]) for i in range(len(filled) - 1)]
    assert max(gaps) <= 50.0 + 1e-6


def test_densifying_keeps_the_original_vertices() -> None:
    points = [(106.700, 10.770), (106.705, 10.775), (106.710, 10.770)]
    filled = densify(points, step_m=50.0)
    for point in points:
        assert point in filled


def test_a_single_point_geometry_is_left_alone() -> None:
    assert densify([(106.7, 10.77)]) == [(106.7, 10.77)]
