"""Congestion levels: the one place a speed becomes a colour and a word.

A traffic level is not a measurement -- it is a judgement about one, and the
thresholds behind that judgement are a product decision, not a fact about the
road. That is exactly why it lives in `traffic` and not in `ingest`: what
leaves ingest is what the source said, a speed and a free-flow reference, and
what that ratio *means* is decided here, in one place, for every provider at
once. The routing cost model, the API and any future HUD all classify the same
ratio the same way, and moving where "heavy" starts is a one-line edit rather
than a hunt.

The ratio is measured speed over free-flow speed. Free flow is the speed the
road runs at when nothing is in the way -- from the sensor operator where they
publish one, from the posted limit otherwise -- never a legal limit dressed up
as a measurement.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = [
    "TrafficLevel",
    "LEVEL_THRESHOLDS",
    "LEVEL_COLORS",
    "level_for_ratio",
    "level_for_speed",
    "level_payload",
]


class TrafficLevel(IntEnum):
    """How badly a stretch of road is moving relative to its free flow.

    Ordered, so ``level >= TrafficLevel.HEAVY`` is a meaningful test.
    :attr:`UNKNOWN` is negative on purpose: it must never compare as worse
    than free flow, because "no reading" is not congestion.
    """

    UNKNOWN = -1
    FREE_FLOW = 0
    LIGHT = 1
    MODERATE = 2
    HEAVY = 3
    STANDSTILL = 4

    @property
    def slug(self) -> str:
        return self.name.lower()


#: Lower bound of speed/free-flow for each level, best first. The first row
#: whose bound the ratio meets wins.
LEVEL_THRESHOLDS: tuple[tuple[float, TrafficLevel], ...] = (
    (0.85, TrafficLevel.FREE_FLOW),
    (0.65, TrafficLevel.LIGHT),
    (0.45, TrafficLevel.MODERATE),
    (0.25, TrafficLevel.HEAVY),
    (0.00, TrafficLevel.STANDSTILL),
)

#: One colour per level, as CSS hex. Chosen to stay separable on the map
#: block's light basemap and to keep the green-to-red reading a driver already
#: knows, with grey -- not green -- for "no data".
LEVEL_COLORS: dict[TrafficLevel, str] = {
    TrafficLevel.UNKNOWN: "#9aa3ad",
    TrafficLevel.FREE_FLOW: "#2fa84f",
    TrafficLevel.LIGHT: "#9ec93a",
    TrafficLevel.MODERATE: "#f2b826",
    TrafficLevel.HEAVY: "#e8632c",
    TrafficLevel.STANDSTILL: "#c0243c",
}

#: The order a legend reads in: best to worst, then the no-data row.
LEVEL_ORDER: tuple[TrafficLevel, ...] = (
    TrafficLevel.FREE_FLOW,
    TrafficLevel.LIGHT,
    TrafficLevel.MODERATE,
    TrafficLevel.HEAVY,
    TrafficLevel.STANDSTILL,
    TrafficLevel.UNKNOWN,
)


def level_for_ratio(ratio: float | None) -> TrafficLevel:
    """Classify a speed/free-flow ratio.

    Returns :attr:`TrafficLevel.UNKNOWN` for ``None`` or a non-positive ratio,
    which is what a sensor that reported nothing looks like.
    """
    if ratio is None:
        return TrafficLevel.UNKNOWN
    if ratio <= 0:
        return TrafficLevel.UNKNOWN
    for bound, level in LEVEL_THRESHOLDS:
        if ratio >= bound:
            return level
    return TrafficLevel.STANDSTILL


def level_for_speed(speed_kph: float | None, free_flow_kph: float | None) -> TrafficLevel:
    """Classify a measured speed against its free-flow reference."""
    if speed_kph is None or free_flow_kph is None:
        return TrafficLevel.UNKNOWN
    if free_flow_kph <= 0:
        return TrafficLevel.UNKNOWN
    return level_for_ratio(speed_kph / free_flow_kph)


def level_payload() -> dict[str, object]:
    """The level table as plain data, for a client that must not hard-code it.

    The legend, the colours and the thresholds are served rather than
    published in a document, so a renderer ships no opinion of its own about
    what "heavy" looks like and cannot drift from the server that decides it.
    """
    return {
        "levels": [
            {
                "value": int(level),
                "slug": level.slug,
                "label": level.name.replace("_", " ").title(),
                "color": LEVEL_COLORS[level],
                "min_ratio": _min_ratio(level),
            }
            for level in LEVEL_ORDER
        ]
    }


def _min_ratio(level: TrafficLevel) -> float | None:
    for bound, candidate in LEVEL_THRESHOLDS:
        if candidate is level:
            return bound
    return None
