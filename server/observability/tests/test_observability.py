"""Logging shape and the two health questions.

The health tests are about one distinction: a check that fails is not the same
as a server that should be restarted. Getting that wrong takes a working
process out of rotation because a volunteer traffic API is slow.
"""

from __future__ import annotations

import json
import logging

from observability import HealthRegistry, JsonFormatter, configure, get_logger


def record(message="hi", **extra):
    made = logging.LogRecord("server.test", logging.INFO, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(made, key, value)
    return made


# --- Logging ---------------------------------------------------------------


def test_a_json_line_carries_the_standard_fields() -> None:
    payload = json.loads(JsonFormatter().format(record("routed")))
    assert payload["message"] == "routed"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "server.test"


def test_extra_fields_are_merged_so_a_query_can_find_them() -> None:
    payload = json.loads(JsonFormatter().format(record("routed", distance_m=4408)))
    assert payload["distance_m"] == 4408


def test_configuring_twice_does_not_duplicate_handlers() -> None:
    configure(level="INFO")
    configure(level="INFO")
    assert len(logging.getLogger("server").handlers) == 1


def test_the_server_logger_does_not_propagate_to_the_root() -> None:
    configure(level="INFO")
    assert logging.getLogger("server").propagate is False


def test_a_named_logger_is_a_child_of_the_server_logger() -> None:
    assert get_logger("api").name == "server.api"


# --- Health ----------------------------------------------------------------


def test_a_registry_with_no_checks_is_ready() -> None:
    ok, report = HealthRegistry().ready()
    assert ok is True
    assert report["checks"] == []


def test_a_failing_critical_check_makes_the_server_not_ready() -> None:
    registry = HealthRegistry()
    registry.register("storage", lambda: (False, "disk gone"))
    ok, report = registry.ready()

    assert ok is False
    assert report["checks"][0]["detail"] == "disk gone"


def test_a_failing_non_critical_check_degrades_rather_than_failing() -> None:
    """A missing traffic feed must not take a serving process out of rotation."""
    registry = HealthRegistry()
    registry.register("traffic", lambda: (False, "feed down"), critical=False)
    ok, report = registry.ready()

    assert ok is True
    assert report["degraded"] == ["traffic"]


def test_a_check_that_raises_is_reported_as_failed_not_propagated() -> None:
    """A health endpoint that can itself fail is worse than useless in an incident."""
    registry = HealthRegistry()
    registry.register("boom", lambda: 1 / 0)
    ok, report = registry.ready()

    assert ok is False
    assert "ZeroDivisionError" in report["checks"][0]["detail"]


def test_every_check_is_timed() -> None:
    registry = HealthRegistry()
    registry.register("fast", lambda: (True, None))
    assert registry.ready()[1]["checks"][0]["duration_ms"] >= 0
