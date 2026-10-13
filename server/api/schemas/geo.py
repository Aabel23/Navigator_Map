"""Reading geography out of a request, and writing it back.

Every endpoint that names an area accepts it the same way, spells errors the
same way, and defaults the same way. That uniformity is the only reason this
file exists: four handlers each parsing a bbox is four chances for one of them
to accept ``south,west,north,east``.

Coordinates are longitude first, everywhere, in every direction. That is
GeoJSON order and the order every free source this project reads publishes in.
The routing block stores its points latitude-first because its contract says
so; the single conversion happens at the map-data graph boundary, and no other
module -- including this one -- may add a second.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from domain import BBox, GeoPoint

__all__ = ["parse_bbox", "parse_point", "parse_points", "bbox_payload", "ApiError"]


class ApiError(ValueError):
    """A request cannot be understood. Carries the status it should return.

    A validation problem and an internal failure must not look the same to a
    client: one is worth retrying with different input, the other is not.
    """

    def __init__(self, message: str, *, status: int = 400, field: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.field = field

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": str(self)}
        if self.field:
            payload["field"] = self.field
        return payload


def parse_bbox(raw: str | None, *, default: BBox | None = None, field: str = "bbox") -> BBox:
    """Read ``"west,south,east,north"``.

    Args:
        raw: The query value, or ``None``.
        default: Used when ``raw`` is absent. Without one, absence is an error
            -- an endpoint whose area is genuinely required must not quietly
            answer for somewhere else.
    """
    if raw is None or raw == "":
        if default is not None:
            return default
        raise ApiError(f"{field} is required, as west,south,east,north", field=field)
    try:
        return BBox.parse(raw)
    except ValueError as err:
        raise ApiError(f"{field}: {err}", field=field) from err


def parse_point(raw: Any, *, field: str) -> GeoPoint:
    """Read a point from ``"lon,lat"``, ``[lon, lat]`` or ``{"lon":…,"lat":…}``.

    Three spellings because three callers exist: a query string, a GeoJSON-ish
    body, and a hand-written one. All three are unambiguous, so accepting them
    costs nothing and refusing them would be pedantry.
    """
    try:
        if isinstance(raw, str):
            return GeoPoint.parse(raw)
        if isinstance(raw, Mapping):
            return GeoPoint(float(raw["lon"]), float(raw["lat"]))
        if isinstance(raw, Sequence) and len(raw) == 2:
            return GeoPoint(float(raw[0]), float(raw[1]))
    except (KeyError, TypeError, ValueError) as err:
        raise ApiError(f"{field}: {err}", field=field) from err
    raise ApiError(f"{field} must be lon,lat", field=field)


def parse_points(raw: Any, *, field: str) -> tuple[GeoPoint, ...]:
    """Read an optional list of points. ``None`` and ``[]`` both give ``()``."""
    if not raw:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ApiError(f"{field} must be a list of points", field=field)
    return tuple(
        parse_point(item, field=f"{field}[{index}]") for index, item in enumerate(raw)
    )


def bbox_payload(area: BBox) -> dict[str, Any]:
    """An area, as the API reports it.

    Both spellings are returned: the list is what a client passes back
    verbatim, and the named fields are what a human reads in a response
    without counting positions.
    """
    return {
        "bbox": list(area.as_tuple()),
        "west": area.west,
        "south": area.south,
        "east": area.east,
        "north": area.north,
    }
