"""Unit tests for the spherical geometry helpers."""

import pytest

from routing import LatLon
from routing.geometry import haversine_m, initial_bearing, polyline_length_m, turn_angle

SAIGON = LatLon(10.7769, 106.7009)
HANOI = LatLon(21.0278, 105.8342)


def test_latlon_rejects_out_of_range_latitude():
    with pytest.raises(ValueError):
        LatLon(91.0, 0.0)


def test_latlon_rejects_out_of_range_longitude():
    with pytest.raises(ValueError):
        LatLon(0.0, 181.0)


def test_haversine_is_zero_for_the_same_point():
    assert haversine_m(SAIGON, SAIGON) == 0.0


def test_haversine_matches_a_known_distance():
    # Ho Chi Minh City to Hanoi is about 1150 km great-circle.
    assert haversine_m(SAIGON, HANOI) == pytest.approx(1_150_000, rel=0.02)


def test_haversine_is_symmetric():
    assert haversine_m(SAIGON, HANOI) == pytest.approx(haversine_m(HANOI, SAIGON))


def test_bearing_due_east_is_ninety():
    assert initial_bearing(LatLon(0.0, 0.0), LatLon(0.0, 1.0)) == pytest.approx(90.0)


def test_bearing_due_north_is_zero():
    assert initial_bearing(LatLon(0.0, 0.0), LatLon(1.0, 0.0)) == pytest.approx(0.0)


def test_bearing_due_west_is_two_seventy():
    assert initial_bearing(LatLon(0.0, 0.0), LatLon(0.0, -1.0)) == pytest.approx(270.0)


def test_bearing_of_a_zero_length_segment_is_defined():
    """Returns 0.0 rather than raising, so callers need no special case."""
    assert initial_bearing(SAIGON, SAIGON) == 0.0


def test_turn_angle_right_is_positive():
    assert turn_angle(0.0, 90.0) == pytest.approx(90.0)


def test_turn_angle_left_is_negative():
    assert turn_angle(90.0, 0.0) == pytest.approx(-90.0)


def test_turn_angle_wraps_across_north():
    assert turn_angle(350.0, 10.0) == pytest.approx(20.0)
    assert turn_angle(10.0, 350.0) == pytest.approx(-20.0)


def test_turn_angle_of_a_reversal_is_one_eighty():
    assert abs(turn_angle(0.0, 180.0)) == pytest.approx(180.0)


def test_polyline_length_sums_its_segments():
    points = (LatLon(0.0, 0.0), LatLon(0.0, 0.01), LatLon(0.0, 0.02))
    expected = haversine_m(points[0], points[1]) + haversine_m(points[1], points[2])
    assert polyline_length_m(points) == pytest.approx(expected)


def test_polyline_length_of_one_point_is_zero():
    assert polyline_length_m((SAIGON,)) == 0.0
