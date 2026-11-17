"""Reverse geocoding: parsing, caching, and keeping to Nominatim's rate limit.

No network. The HTTP client is a fake that records what it was asked, and the
clock is a counter, so the one-request-a-second rule is checked by arithmetic
rather than by waiting.
"""

from __future__ import annotations

import pytest

from mapdata import BadResponse, NominatimAddressSource, parse_nominatim
from storage import JsonFileCache

BEN_THANH = {
    "name": "Chợ Bến Thành",
    "display_name": "Chợ Bến Thành, Lê Lợi, Phường Bến Thành, Quận 1, Thành phố Hồ Chí Minh, Việt Nam",
    "address": {
        "amenity": "Chợ Bến Thành",
        "house_number": "2",
        "road": "Lê Lợi",
        "quarter": "Phường Bến Thành",
        "city_district": "Quận 1",
        "city": "Thành phố Hồ Chí Minh",
        "country": "Việt Nam",
    },
}


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []
        self.headers: list[dict] = []

    def get_json(self, url, headers=None):
        self.urls.append(url)
        self.headers.append(dict(headers or {}))
        return self.payload


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def source(payload=BEN_THANH, clock=None):
    clock = clock or FakeClock()
    client = FakeClient(payload)
    made = NominatimAddressSource(
        client=client, cache=JsonFileCache(None), clock=clock, sleep=clock.sleep
    )
    return made, client, clock


def test_parse_builds_a_vietnamese_address_line():
    address = parse_nominatim(BEN_THANH, (106.698, 10.772))
    assert address.label == "Chợ Bến Thành, 2 Lê Lợi, Phường Bến Thành, Quận 1, Thành phố Hồ Chí Minh"
    assert address.house_number == "2"
    assert address.street == "Lê Lợi"
    assert address.ward == "Phường Bến Thành"
    assert address.district == "Quận 1"
    assert address.city == "Thành phố Hồ Chí Minh"
    assert address.place_name == "Chợ Bến Thành"
    assert address.point == (106.698, 10.772)


def test_a_name_that_is_just_the_street_is_not_repeated():
    payload = {"name": "Lê Lợi", "address": {"road": "Lê Lợi", "city": "HCM"}}
    address = parse_nominatim(payload, (0.0, 0.0))
    assert address.place_name is None
    assert address.label == "Lê Lợi, HCM"


def test_an_error_body_is_an_answer_not_an_outage():
    address = parse_nominatim({"error": "Unable to geocode"}, (0.0, 0.0))
    assert address.street is None
    assert address.label


def test_a_non_object_is_a_bad_response():
    with pytest.raises(BadResponse):
        parse_nominatim(["nope"], (0.0, 0.0))


def test_request_carries_rounded_point_and_language():
    made, client, _ = source()
    made.reverse((106.698123456, 10.772987654))
    url = client.urls[0]
    assert "lat=10.7730" in url and "lon=106.6981" in url
    assert "format=jsonv2" in url
    assert client.headers[0]["Accept-Language"].startswith("vi")


def test_points_within_about_ten_metres_share_one_request():
    made, client, _ = source()
    first = made.reverse((106.69811, 10.77201))
    second = made.reverse((106.69814, 10.77204))
    assert len(client.urls) == 1
    # Each answer still reports the point that was asked about.
    assert first.point == (106.69811, 10.77201)
    assert second.point == (106.69814, 10.77204)


def test_consecutive_upstream_requests_are_at_least_a_second_apart():
    made, client, clock = source()
    made.reverse((106.70, 10.77))
    clock.now += 0.25
    made.reverse((106.71, 10.78))
    assert len(client.urls) == 2
    assert clock.slept == [pytest.approx(0.75)]


def test_no_wait_once_the_interval_has_passed():
    made, _, clock = source()
    made.reverse((106.70, 10.77))
    clock.now += 5
    made.reverse((106.71, 10.78))
    assert clock.slept == []
