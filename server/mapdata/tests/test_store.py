"""Road segments through the storage interface, and the fallback that matters.

The behaviour worth the most here is the least obvious: when Overpass is
unreachable, a server that has routed across this city before keeps routing
across it. Road geometry changes on the order of months, so a stale network is
a far smaller problem than no network -- and a test is the only thing that
keeps that true, because the failure path is never exercised by hand.
"""

from __future__ import annotations

import pytest

from domain import BBox
from mapdata import PersistingRoadNetwork, RoadSegment, RoadStore, StoredRoadNetwork
from storage import InMemoryStorage

AREA = BBox(106.690, 10.760, 106.720, 10.790)
ELSEWHERE = BBox(1.0, 1.0, 2.0, 2.0)


@pytest.fixture
def backend():
    made = InMemoryStorage()
    made.migrate()
    yield made
    made.close()


def road(rid="way/1", points=((106.70, 10.77), (106.71, 10.77)), **over):
    fields = dict(road_class="primary", free_flow_kph=50.0, name="Le Loi", oneway=False)
    fields.update(over)
    return RoadSegment(id=rid, geometry=tuple(points), **fields)


class Upstream:
    def __init__(self, segments=(), fail_with=None):
        self.segments = tuple(segments)
        self.fail_with = fail_with
        self.calls = 0

    def roads(self, bbox):
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        return self.segments


def test_a_segment_survives_the_round_trip_unchanged(backend) -> None:
    original = road(points=((106.70, 10.77), (106.705, 10.775), (106.71, 10.77)))
    RoadStore(backend.documents).save([original])

    found = RoadStore(backend.documents).roads(AREA)
    assert len(found) == 1
    assert found[0] == original


def test_saving_the_same_id_twice_replaces_rather_than_duplicates(backend) -> None:
    store = RoadStore(backend.documents)
    store.save([road(name="Old")])
    store.save([road(name="New")])

    found = store.roads(AREA)
    assert len(found) == 1
    assert found[0].name == "New"


def test_a_segment_outside_the_box_is_not_returned(backend) -> None:
    RoadStore(backend.documents).save([road()])
    assert RoadStore(backend.documents).roads(ELSEWHERE) == ()


def test_the_stored_network_answers_the_same_question_a_source_does(backend) -> None:
    RoadStore(backend.documents).save([road()])
    assert len(StoredRoadNetwork(backend.documents).roads(AREA)) == 1


def test_the_persisting_network_saves_what_it_fetched(backend) -> None:
    upstream = Upstream([road()])
    network = PersistingRoadNetwork(upstream, backend.documents)

    network.roads(AREA)

    assert RoadStore(backend.documents).count() == 1


def test_the_persisting_network_falls_back_when_upstream_fails(backend) -> None:
    RoadStore(backend.documents).save([road()])
    network = PersistingRoadNetwork(
        Upstream(fail_with=TimeoutError("overpass down")), backend.documents
    )

    found = network.roads(AREA)

    assert [segment.id for segment in found] == ["way/1"]


def test_the_fallback_is_empty_when_nothing_was_ever_imported(backend) -> None:
    network = PersistingRoadNetwork(
        Upstream(fail_with=TimeoutError("overpass down")), backend.documents
    )
    assert network.roads(AREA) == ()


def test_an_empty_upstream_answer_does_not_erase_what_is_stored(backend) -> None:
    """An Overpass timeout that returns nothing must not look like "no roads here"."""
    RoadStore(backend.documents).save([road()])
    network = PersistingRoadNetwork(Upstream([]), backend.documents)

    assert network.roads(AREA) == ()
    assert RoadStore(backend.documents).count() == 1


def test_forget_removes_one_segment(backend) -> None:
    store = RoadStore(backend.documents)
    store.save([road()])

    assert store.forget("way/1") is True
    assert store.count() == 0
