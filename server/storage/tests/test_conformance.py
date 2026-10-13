"""One suite, every backend. This is what "replaceable" means here.

Each test is written against `storage.StorageBackend` and never names an
engine. The `backend` fixture is parameterised, so adding PostgreSQL later
means adding one entry to `BACKENDS` and nothing else -- and if the new
backend disagrees with the old one about ordering, upsert, validity windows or
cache expiry, this suite says so before anything above storage does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from storage import Collection, InMemoryStorage, SqliteStorage, StoredDocument
from storage.sqlite.backend import MEMORY

T0 = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


BACKENDS = {
    "memory": lambda tmp_path: InMemoryStorage(),
    "sqlite-file": lambda tmp_path: SqliteStorage(tmp_path / "server.db"),
    "sqlite-memory": lambda tmp_path: SqliteStorage(MEMORY),
}


@pytest.fixture(params=sorted(BACKENDS))
def backend(request, tmp_path):
    made = BACKENDS[request.param](tmp_path)
    made.migrate()
    yield made
    made.close()


def doc(key: str, **over) -> StoredDocument:
    fields = dict(
        collection=Collection.ROADS,
        key=key,
        west=106.6,
        south=10.7,
        east=106.8,
        north=10.9,
        payload={"name": key},
        recorded_at=T0,
    )
    fields.update(over)
    return StoredDocument(**fields)


# --- documents -------------------------------------------------------------


def test_put_then_get_round_trips_every_field(backend):
    original = doc(
        "a",
        payload={"name": "Nguyen Hue", "lanes": 4, "shape": [[1.0, 2.0], [3.0, 4.0]]},
        valid_from=T0,
        valid_to=T0 + timedelta(hours=2),
    )
    backend.documents.put([original])

    found = backend.documents.get(Collection.ROADS, "a")
    assert found is not None
    assert found.key == original.key
    assert found.payload == original.payload
    assert found.as_area() == original.as_area()
    assert found.recorded_at == original.recorded_at
    assert found.valid_from == original.valid_from
    assert found.valid_to == original.valid_to


def test_get_missing_is_none_not_an_error(backend):
    assert backend.documents.get(Collection.ROADS, "nope") is None


def test_put_is_idempotent_on_key(backend):
    backend.documents.put([doc("a", payload={"v": 1})])
    backend.documents.put([doc("a", payload={"v": 2})])

    assert backend.documents.count(Collection.ROADS) == 1
    assert backend.documents.get(Collection.ROADS, "a").payload == {"v": 2}


def test_collections_do_not_leak_into_each_other(backend):
    backend.documents.put([doc("a")])
    backend.documents.put([doc("a", collection=Collection.OBSERVATIONS)])

    assert backend.documents.count(Collection.ROADS) == 1
    assert backend.documents.count(Collection.OBSERVATIONS) == 1
    assert backend.documents.find(Collection.ROADS)[0].collection == Collection.ROADS


def test_put_of_nothing_writes_nothing(backend):
    assert backend.documents.put([]) == 0


def test_find_by_area_keeps_overlaps_and_drops_the_rest(backend):
    backend.documents.put([doc("here")])
    backend.documents.put([doc("far", west=0.0, south=0.0, east=1.0, north=1.0)])

    keys = {d.key for d in backend.documents.find(Collection.ROADS, bbox=(106.7, 10.75, 106.75, 10.8))}
    assert keys == {"here"}


def test_find_by_area_includes_a_touching_edge(backend):
    backend.documents.put([doc("a")])
    # Shares exactly the eastern edge: touching is intersecting.
    assert backend.documents.find(Collection.ROADS, bbox=(106.8, 10.7, 107.0, 10.9))


def test_find_at_respects_the_validity_window(backend):
    backend.documents.put(
        [
            doc("open", valid_from=None, valid_to=None),
            doc("past", valid_from=T0 - timedelta(hours=3), valid_to=T0 - timedelta(hours=1)),
            doc("future", valid_from=T0 + timedelta(hours=1), valid_to=None),
            doc("now", valid_from=T0 - timedelta(hours=1), valid_to=T0 + timedelta(hours=1)),
        ]
    )

    keys = {d.key for d in backend.documents.find(Collection.ROADS, at=T0)}
    assert keys == {"open", "now"}


def test_find_since_keeps_only_newer_records(backend):
    backend.documents.put([doc("old", recorded_at=T0 - timedelta(hours=2))])
    backend.documents.put([doc("new", recorded_at=T0)])

    keys = {d.key for d in backend.documents.find(Collection.ROADS, since=T0 - timedelta(hours=1))}
    assert keys == {"new"}


def test_find_orders_newest_first_then_by_key(backend):
    backend.documents.put(
        [
            doc("b", recorded_at=T0),
            doc("a", recorded_at=T0),
            doc("c", recorded_at=T0 + timedelta(minutes=1)),
        ]
    )

    assert [d.key for d in backend.documents.find(Collection.ROADS)] == ["c", "a", "b"]


def test_find_limit_applies_after_ordering(backend):
    backend.documents.put(
        [doc("a", recorded_at=T0), doc("z", recorded_at=T0 + timedelta(minutes=1))]
    )
    assert [d.key for d in backend.documents.find(Collection.ROADS, limit=1)] == ["z"]


def test_find_combines_every_filter(backend):
    backend.documents.put(
        [
            doc("keep", valid_to=T0 + timedelta(hours=1)),
            doc("wrong-area", west=0.0, south=0.0, east=1.0, north=1.0),
            doc("expired", valid_to=T0 - timedelta(hours=1)),
            doc("too-old", recorded_at=T0 - timedelta(days=2)),
        ]
    )

    found = backend.documents.find(
        Collection.ROADS,
        bbox=(106.7, 10.75, 106.75, 10.8),
        at=T0,
        since=T0 - timedelta(hours=1),
    )
    assert [d.key for d in found] == ["keep"]


def test_delete_reports_whether_anything_went(backend):
    backend.documents.put([doc("a")])

    assert backend.documents.delete(Collection.ROADS, "a") is True
    assert backend.documents.delete(Collection.ROADS, "a") is False
    assert backend.documents.count(Collection.ROADS) == 0


def test_prune_drops_only_what_is_older(backend):
    backend.documents.put(
        [doc("old", recorded_at=T0 - timedelta(days=2)), doc("new", recorded_at=T0)]
    )

    assert backend.documents.prune(Collection.ROADS, recorded_before=T0 - timedelta(days=1)) == 1
    assert [d.key for d in backend.documents.find(Collection.ROADS)] == ["new"]


def test_prune_is_scoped_to_its_collection(backend):
    backend.documents.put([doc("x", recorded_at=T0 - timedelta(days=2))])
    backend.documents.put(
        [doc("x", collection=Collection.OBSERVATIONS, recorded_at=T0 - timedelta(days=2))]
    )

    backend.documents.prune(Collection.ROADS, recorded_before=T0)
    assert backend.documents.count(Collection.OBSERVATIONS) == 1


def test_count_of_an_unused_collection_is_zero(backend):
    assert backend.documents.count("never-written") == 0


# --- cache -----------------------------------------------------------------


def test_cache_round_trips_a_payload(backend):
    backend.cache.put("k", {"roads": [1, 2, 3]})
    assert backend.cache.get("k") == {"roads": [1, 2, 3]}


def test_cache_miss_is_none(backend):
    assert backend.cache.get("absent") is None


def test_cache_put_replaces(backend):
    backend.cache.put("k", 1)
    backend.cache.put("k", 2)
    assert backend.cache.get("k") == 2


def test_cache_forget_is_silent_when_absent(backend):
    backend.cache.forget("absent")


def test_cache_clear_reports_how_many_went(backend):
    backend.cache.put("a", 1)
    backend.cache.put("b", 2)
    assert backend.cache.clear() == 2
    assert backend.cache.get("a") is None


def test_cache_never_raises_on_an_unserialisable_payload(backend):
    backend.cache.put("bad", object())
    assert backend.cache.get("bad") is None


# --- lifecycle -------------------------------------------------------------


def test_migrate_is_safe_to_repeat(backend):
    backend.documents.put([doc("a")])
    backend.migrate()
    assert backend.documents.count(Collection.ROADS) == 1


def test_close_is_safe_to_repeat(backend):
    backend.close()
    backend.close()


def test_healthy_answers_true_while_open(backend):
    assert backend.healthy() is True


# --- record validation -----------------------------------------------------


def test_a_naive_timestamp_is_refused():
    with pytest.raises(ValueError, match="naive"):
        StoredDocument(
            collection="c",
            key="k",
            west=0,
            south=0,
            east=1,
            north=1,
            recorded_at=datetime(2026, 1, 1),
        )


def test_an_inverted_box_is_refused():
    with pytest.raises(ValueError, match="inverted"):
        StoredDocument(collection="c", key="k", west=2, south=0, east=1, north=1)


def test_a_document_needs_a_collection_and_a_key():
    with pytest.raises(ValueError):
        StoredDocument(collection="", key="k", west=0, south=0, east=1, north=1)
    with pytest.raises(ValueError):
        StoredDocument(collection="c", key="", west=0, south=0, east=1, north=1)
