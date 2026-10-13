"""Configuration -- read once, at startup, in one place.

    from config import Settings

    settings = Settings.from_env()

Owns:
    what a deployment may change, and turning environment strings into usable
    values

Does not own:
    any decision those values feed. No module below this one reads the
    environment: a subsystem that did would be untestable without setting a
    variable and undiscoverable without grepping for one.
"""

from .settings import Settings, SettingsError

__all__ = ["Settings", "SettingsError"]
