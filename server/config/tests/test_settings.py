"""Configuration: defaults that work, and mistakes that fail at startup.

The property worth the most is the last one: a value the server cannot use has
to be refused when the process starts, not when the first request arrives.
A server that silently ran on the default port because MAP_PORT was "eight
thousand" would be found out much later, by someone else.
"""

from __future__ import annotations

import pytest

from config import Settings, SettingsError


def test_a_fresh_checkout_with_no_environment_starts() -> None:
    settings = Settings.from_env({})
    assert settings.storage_backend == "sqlite"
    assert settings.area().west < settings.area().east


def test_a_string_setting_is_read() -> None:
    assert Settings.from_env({"MAP_HOST": "0.0.0.0"}).host == "0.0.0.0"


def test_an_integer_setting_is_coerced() -> None:
    assert Settings.from_env({"MAP_PORT": "9000"}).port == 9000


def test_a_float_setting_is_coerced() -> None:
    assert Settings.from_env({"MAP_TRAFFIC_MAX_AGE_S": "120.5"}).traffic_max_age_s == 120.5


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_spellings_are_accepted(raw) -> None:
    assert Settings.from_env({"MAP_TRAFFIC_ENABLED": raw}).traffic_enabled is True


@pytest.mark.parametrize("raw", ["0", "false", "No", "off"])
def test_falsy_spellings_are_accepted(raw) -> None:
    assert Settings.from_env({"MAP_TRAFFIC_ENABLED": raw}).traffic_enabled is False


def test_an_unreadable_boolean_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(SettingsError, match="MAP_TRAFFIC_ENABLED"):
        Settings.from_env({"MAP_TRAFFIC_ENABLED": "maybe"})


def test_an_unreadable_integer_is_refused() -> None:
    with pytest.raises(SettingsError, match="MAP_PORT"):
        Settings.from_env({"MAP_PORT": "eight thousand"})


def test_an_unimplemented_backend_fails_at_startup_not_at_the_first_query() -> None:
    with pytest.raises(SettingsError, match="MIGRATION.md"):
        Settings.from_env({"MAP_STORAGE_BACKEND": "postgres"})


def test_an_out_of_range_port_is_refused() -> None:
    with pytest.raises(SettingsError, match="port"):
        Settings.from_env({"MAP_PORT": "70000"})


def test_an_unusable_default_area_is_refused() -> None:
    with pytest.raises(SettingsError, match="default_area"):
        Settings.from_env({"MAP_DEFAULT_AREA": "not,a,box"})


def test_a_negative_snap_radius_is_refused() -> None:
    with pytest.raises(SettingsError, match="snap_radius"):
        Settings.from_env({"MAP_ROUTE_SNAP_RADIUS_M": "0"})


def test_describe_reports_the_backend_and_the_feature_switches() -> None:
    described = Settings.from_env({"MAP_STORAGE_BACKEND": "memory"}).describe()
    assert described["storage_backend"] == "memory"
    assert described["database_path"] is None
