"""The HTTP surface, over the real stack with fake outside world.

These tests build the actual Flask app, the actual services, the actual
routing engine and the actual storage backend. The only things replaced are
the two edges of the system: the road source and the traffic feeds, which
would otherwise make the suite depend on Overpass and Fintraffic being up.

That is what ``create_app(services=...)`` is for, and why composition is a
separate module. Nothing here monkey-patches anything.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api import create_app
from api.services import IngestService, TrafficService
from config import Settings
from domain import BBox
from ingest import TrafficCollector
from mapdata import RoadGraphProvider
from observability import HealthRegistry
from roadstate import RoadStateSource, RoadStateStore
from routing import RoutingPolicy, RoutingService
from storage import InMemoryStorage
from tests.fixtures import TOWN_AREA, FakeRoadNetwork
from traffic import TrafficCostSource, TrafficState

AREA_QUERY = "106.690,10.760,106.720,10.790"
A = [106.700, 10.770]
C = [106.710, 10.780]


@pytest.fixture
def app():
    """The whole server, with a fake road source and no traffic feeds."""
    from api.composition import Services

    settings = Settings.from_env(
        {"MAP_STORAGE_BACKEND": "memory", "MAP_DEFAULT_AREA": AREA_QUERY, "MAP_LOG_LEVEL": "ERROR"}
    )
    storage = InMemoryStorage()
    storage.migrate()

    roads = FakeRoadNetwork()
    graphs = RoadGraphProvider(roads)
    traffic_state = TrafficState()
    road_state = RoadStateStore(storage.documents)

    ingest = IngestService(
        collector=TrafficCollector(),
        traffic=traffic_state,
        road_state=road_state,
        roads=roads,
    )
    services = Services(
        settings=settings,
        storage=storage,
        roads=roads,
        graphs=graphs,
        traffic_state=traffic_state,
        routing=RoutingService(
            graphs=graphs,
            traffic=TrafficCostSource(traffic_state, graphs),
            road_state=RoadStateSource(road_state, graphs),
            policy=RoutingPolicy(pad_degrees=0.02, snap_radius_m=250.0),
        ),
        ingest=ingest,
        traffic=TrafficService(ingest=ingest, state=traffic_state),
        road_state=road_state,
        health=HealthRegistry(),
    )
    services.health.register("storage", lambda: (storage.healthy(), storage.name))

    made = create_app(settings, services=services)
    made.config["TESTING"] = True
    yield made
    services.close()


@pytest.fixture
def client(app):
    return app.test_client()


def route_body(**over):
    body = {"origin": A, "destination": C}
    body.update(over)
    return body


# --- Health ----------------------------------------------------------------


def test_liveness_checks_nothing_and_says_so(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["live"] is True


def test_readiness_runs_the_checks(client) -> None:
    payload = client.get("/health/ready").get_json()
    assert payload["ready"] is True
    assert payload["checks"][0]["name"] == "storage"


def test_info_reports_what_the_server_was_composed_with(client) -> None:
    payload = client.get("/health/info").get_json()
    assert payload["settings"]["storage_backend"] == "memory"
    assert "routing" in payload


def test_the_root_lists_the_endpoints_it_actually_registered(client) -> None:
    endpoints = client.get("/").get_json()["endpoints"]
    assert "POST /api/v1/route" in endpoints


# --- Routing ---------------------------------------------------------------


def test_a_route_request_returns_a_drawable_route(client) -> None:
    payload = client.post("/api/v1/route", json=route_body()).get_json()

    assert payload["status"] == "ok"
    assert payload["distance_m"] > 0
    assert payload["duration_s"] > 0
    assert payload["geometry"]["type"] == "LineString"
    assert len(payload["geometry"]["coordinates"]) >= 2


def test_the_response_publishes_coordinates_longitude_first(client) -> None:
    """Routing stores them latitude-first; publishing that would break clients."""
    first = client.post("/api/v1/route", json=route_body()).get_json()["geometry"][
        "coordinates"
    ][0]
    assert 106 < first[0] < 107
    assert 10 < first[1] < 11


def test_the_response_carries_manoeuvre_steps(client) -> None:
    steps = client.post("/api/v1/route", json=route_body()).get_json()["steps"]
    assert steps[0]["maneuver"] == "depart"
    assert steps[-1]["maneuver"] == "arrive"


def test_total_cost_is_never_published(client) -> None:
    """It may be penalty-weighted; a client would eventually show it as an ETA."""
    payload = client.post("/api/v1/route", json=route_body()).get_json()
    assert "total_cost" not in payload
    assert "duration_s" in payload


def test_a_route_request_with_no_body_is_a_client_error(client) -> None:
    response = client.post("/api/v1/route")
    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_an_unknown_profile_names_the_field(client) -> None:
    response = client.post("/api/v1/route", json=route_body(profile="hovercraft"))
    assert response.status_code == 400
    assert response.get_json()["field"] == "profile"


def test_an_endpoint_nowhere_near_a_road_is_400_not_500(client) -> None:
    response = client.post("/api/v1/route", json=route_body(origin=[0.0, 0.0]))
    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_request"


def test_a_naive_departure_is_refused_with_an_explanation(client) -> None:
    response = client.post("/api/v1/route", json=route_body(departure="2026-09-13T08:00:00"))
    assert response.status_code == 400
    assert "timezone" in response.get_json()["error"]


def test_an_aware_departure_is_accepted(client) -> None:
    response = client.post(
        "/api/v1/route", json=route_body(departure="2026-09-13T08:00:00+07:00")
    )
    assert response.status_code == 200


def test_waypoints_are_routed_through(client) -> None:
    payload = client.post(
        "/api/v1/route", json=route_body(waypoints=[[106.700, 10.780]])
    ).get_json()
    assert payload["meta"]["waypoints"] == 1


def test_too_many_waypoints_are_refused(client) -> None:
    response = client.post("/api/v1/route", json=route_body(waypoints=[A] * 50))
    assert response.status_code == 400


def test_a_closure_reaches_routing_through_the_api(client) -> None:
    """The whole chain: report -> classify -> store -> constraint -> route."""
    before = client.post("/api/v1/route", json=route_body()).get_json()
    blocked_road = before["segments"][0].split("#")[0]

    accepted = client.post(
        "/api/v1/ingest/reports",
        json={
            "reports": [
                {
                    "id": "closure-1",
                    "title": "Road closed",
                    "geometry": [A, C],
                    "road_ids": [blocked_road],
                }
            ]
        },
    )
    assert accepted.get_json()["accepted"] == 1

    after = client.post("/api/v1/route", json=route_body()).get_json()
    assert not any(segment.startswith(blocked_road) for segment in after["segments"])


# --- Map data --------------------------------------------------------------


def test_roads_come_back_as_geojson(client) -> None:
    payload = client.get(f"/api/v1/mapdata/roads?bbox={AREA_QUERY}").get_json()

    assert payload["type"] == "FeatureCollection"
    assert payload["count"] > 0
    assert payload["features"][0]["geometry"]["type"] == "LineString"


def test_the_default_area_is_used_when_none_is_given(client) -> None:
    assert client.get("/api/v1/mapdata/roads").status_code == 200


def test_a_malformed_bbox_names_the_field(client) -> None:
    response = client.get("/api/v1/mapdata/roads?bbox=nonsense")
    assert response.status_code == 400
    assert response.get_json()["field"] == "bbox"


def test_an_inverted_bbox_is_refused(client) -> None:
    assert client.get("/api/v1/mapdata/roads?bbox=2,0,1,1").status_code == 400


def test_the_graph_summary_reports_counts_not_contents(client) -> None:
    payload = client.get(f"/api/v1/mapdata/graph?bbox={AREA_QUERY}").get_json()
    assert payload["edges"] > 0
    assert payload["nodes"] > 0
    assert "features" not in payload


# --- Traffic ---------------------------------------------------------------


def test_traffic_is_empty_and_honest_when_no_source_covers_the_area(client) -> None:
    payload = client.get(f"/api/v1/traffic?bbox={AREA_QUERY}").get_json()
    assert payload["roads"] == []
    assert payload["simulated"] is False


def test_probes_become_traffic_visible_through_the_api(client) -> None:
    now = datetime.now(timezone.utc).isoformat()
    posted = client.post(
        "/api/v1/ingest/probes",
        json={
            "probes": [
                {"device_id": "d1", "lon": 106.705, "lat": 10.770, "speed_kph": 5.0, "observed_at": now}
            ]
        },
    ).get_json()
    assert posted["accepted"] == 1
    assert posted["roads_with_speed"] >= 1

    payload = client.get(f"/api/v1/traffic?bbox={AREA_QUERY}").get_json()
    assert payload["roads"]
    assert payload["roads"][0]["level"] in {"heavy", "standstill", "moderate"}


def test_a_malformed_probe_is_counted_and_explained(client) -> None:
    payload = client.post(
        "/api/v1/ingest/probes", json={"probes": [{"device_id": "d1"}]}
    ).get_json()
    assert payload["accepted"] == 0
    assert payload["rejected"] == 1
    assert payload["reasons"]


def test_the_level_table_is_served_rather_than_documented(client) -> None:
    levels = client.get("/api/v1/traffic/levels").get_json()["levels"]
    assert {row["slug"] for row in levels} >= {"free_flow", "heavy", "standstill"}
    assert all("color" in row for row in levels)


# --- Road state ------------------------------------------------------------


def test_conditions_are_independently_queryable(client) -> None:
    client.post(
        "/api/v1/ingest/reports",
        json={"reports": [{"id": "w1", "kind": "roadworks", "lon": 106.705, "lat": 10.770}]},
    )
    payload = client.get(f"/api/v1/roadstate?bbox={AREA_QUERY}").get_json()

    assert payload["total"] == 1
    assert payload["by_kind"]["construction"] == 1


def test_blocking_conditions_are_reported_separately(client) -> None:
    client.post(
        "/api/v1/ingest/reports",
        json={
            "reports": [
                {"id": "c1", "title": "Road closed", "lon": 106.705, "lat": 10.770},
                {"id": "w1", "kind": "roadworks", "lon": 106.705, "lat": 10.780},
            ]
        },
    )
    payload = client.get(f"/api/v1/roadstate?bbox={AREA_QUERY}").get_json()

    assert payload["total"] == 2
    assert len(payload["blocking"]) == 1


def test_one_condition_can_be_fetched_by_id(client) -> None:
    client.post(
        "/api/v1/ingest/reports",
        json={"reports": [{"id": "w1", "kind": "roadworks", "lon": 106.705, "lat": 10.770}]},
    )
    payload = client.get("/api/v1/roadstate/report:w1").get_json()
    assert payload["condition"]["id"] == "report:w1"


def test_a_missing_condition_is_a_404(client) -> None:
    assert client.get("/api/v1/roadstate/report:nope").status_code == 404


def test_a_condition_can_be_withdrawn(client) -> None:
    client.post(
        "/api/v1/ingest/reports",
        json={"reports": [{"id": "w1", "kind": "roadworks", "lon": 106.705, "lat": 10.770}]},
    )
    assert client.delete("/api/v1/roadstate/report:w1").status_code == 200
    assert client.delete("/api/v1/roadstate/report:w1").status_code == 404


# --- Errors and transport --------------------------------------------------


def test_an_unknown_endpoint_is_json_not_html(client) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"


def test_the_wrong_method_is_json_too(client) -> None:
    response = client.get("/api/v1/route")
    assert response.status_code == 405
    assert response.get_json()["code"] == "method_not_allowed"


def test_every_response_carries_a_request_id(client) -> None:
    assert client.get("/health").headers.get("X-Request-Id")


def test_a_client_supplied_request_id_is_echoed(client) -> None:
    response = client.get("/health", headers={"X-Request-Id": "trace-me"})
    assert response.headers["X-Request-Id"] == "trace-me"


def test_a_map_source_failure_is_a_503_not_a_500(client, app) -> None:
    """Upstream being down is not this server being broken."""
    app.extensions["services"].roads.fail_with = TimeoutError("overpass down")
    app.extensions["services"].graphs.invalidate()

    response = client.get(f"/api/v1/mapdata/roads?bbox={AREA_QUERY}")
    assert response.status_code == 503


def test_a_failure_message_never_reaches_the_client(client, app) -> None:
    """A 5xx body must say nothing about the internals. Logs are the place for that."""
    services = app.extensions["services"]
    services.roads.fail_with = RuntimeError("connection string postgres://secret@host")
    services.graphs.invalidate()

    response = client.post("/api/v1/route", json=route_body())

    assert response.status_code >= 500
    body = response.get_data(as_text=True)
    assert "secret" not in body
    assert "postgres" not in body


# --- Addresses ---------------------------------------------------------------


class FakeAddresses:
    def __init__(self):
        self.asked = []

    def reverse(self, point):
        from mapdata import parse_nominatim

        self.asked.append(point)
        return parse_nominatim(
            {"address": {"house_number": "2", "road": "Lê Lợi", "city": "Hồ Chí Minh"}}, point
        )


def _with_addresses(app, addresses):
    import dataclasses

    services = app.extensions["services"]
    app.extensions["services"] = dataclasses.replace(services, addresses=addresses)


def test_address_is_read_longitude_first(app):
    fake = FakeAddresses()
    _with_addresses(app, fake)
    payload = app.test_client().get("/api/v1/mapdata/address?point=106.698,10.772").get_json()
    assert payload["status"] == "ok"
    assert payload["label"] == "2 Lê Lợi, Hồ Chí Minh"
    assert payload["point"] == [106.698, 10.772]
    assert fake.asked == [(106.698, 10.772)]


def test_address_without_a_point_is_a_400(app):
    _with_addresses(app, FakeAddresses())
    response = app.test_client().get("/api/v1/mapdata/address")
    assert response.status_code == 400
    assert response.get_json()["field"] == "point"


def test_address_with_a_swapped_point_is_a_400(app):
    _with_addresses(app, FakeAddresses())
    response = app.test_client().get("/api/v1/mapdata/address?point=10.772,106.698")
    assert response.status_code == 400


def test_address_without_a_geocoder_is_a_503(app):
    response = app.test_client().get("/api/v1/mapdata/address?point=106.698,10.772")
    assert response.status_code == 503


def test_address_upstream_failure_is_a_503(app):
    from mapdata import SourceUnavailable

    class Down:
        def reverse(self, point):
            raise SourceUnavailable("nominatim unreachable")

    _with_addresses(app, Down())
    response = app.test_client().get("/api/v1/mapdata/address?point=106.698,10.772")
    assert response.status_code == 503
