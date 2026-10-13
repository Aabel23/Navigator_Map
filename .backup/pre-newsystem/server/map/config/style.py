"""The map's visual language, as data rather than code.

Nothing in the renderer knows what a motorway looks like. Every colour, every
width, and every zoom a class starts mattering at lives in the three tables
below; the decoder turns an OpenMapTiles ``(layer, class)`` pair into a *style
index*, and that index rides along on each vertex as an attribute. The shader
looks the index up in a uniform block. That is the whole of the styling
system, and it is why adding a road class or restyling one costs a table row
instead of a render pass: every road in the resident map, whatever its class,
is still drawn by the same two ``drawElements`` calls.

Ordering matters in two places and nowhere else:

* ``FILL_STYLES`` and ``LINE_STYLES`` are ordered lists because their position
  *is* the style index the vertices carry. Append, do not insert.
* ``BUCKET_ORDER`` is the painter's-algorithm order the buckets are drawn in.
"""

from __future__ import annotations

__all__ = [
    "BACKGROUND",
    "ZOOM_STOPS",
    "BUCKET_ORDER",
    "FILL_STYLES",
    "LINE_STYLES",
    "RULES",
    "LABEL_NAME_FIELDS",
    "LABEL_STYLES",
    "LABEL_RULES",
    "style_payload",
]

#: Painted before anything else; the colour of bare land with nothing on it.
BACKGROUND = "#f4f2ed"

#: Line widths are interpolated linearly between these two camera zooms and
#: clamped outside them. A driver spends nearly all their time inside this
#: range, so two stops is honest; more would be false precision.
ZOOM_STOPS = (13.0, 18.0)

#: Draw order. `road` is drawn twice -- casings for the whole network, then
#: fills for the whole network -- which is what makes junctions look like
#: junctions instead of a pile of overlapping ribbons.
BUCKET_ORDER = ["land", "water", "waterway", "building", "road"]

# -- fill styles: index = position in this list ------------------------------

FILL_STYLES: list[tuple[str, str, float]] = [
    # name             colour     opacity
    ("water", "#a3cee6", 1.0),
    ("wood", "#c8e2bc", 1.0),
    ("grass", "#d8edcb", 1.0),
    ("park", "#d0eac3", 1.0),
    ("sand", "#f1e6c9", 1.0),
    ("farmland", "#e7edcb", 1.0),
    ("ice", "#e7f3f7", 1.0),
    ("residential", "#ebe7df", 1.0),
    ("commercial", "#f1eae1", 1.0),
    ("industrial", "#e9e6e0", 1.0),
    ("retail", "#f3e9e3", 1.0),
    ("institution", "#ebe9df", 1.0),
    ("cemetery", "#dfe6d5", 1.0),
    ("pitch", "#d0e7c0", 1.0),
    ("aerodrome", "#e8e8ed", 1.0),
    ("building", "#e3ded3", 1.0),
]

# -- line styles: index = position in this list -------------------------------
# `width` and `casing_width` are full widths in CSS pixels at ZOOM_STOPS[0] and
# ZOOM_STOPS[1]. A casing width of zero collapses the casing pass to nothing
# for that class, which is how a class opts out of having a casing at all.

LINE_STYLES: list[dict] = [
    {
        "name": "motorway",
        "color": "#f9b25c",
        "casing": "#e08c2e",
        "width": (5.0, 30.0),
        "casing_width": (7.5, 37.0),
    },
    {
        "name": "trunk",
        "color": "#fbc46a",
        "casing": "#e2a140",
        "width": (4.5, 26.0),
        "casing_width": (7.0, 32.0),
    },
    {
        "name": "primary",
        "color": "#fcd07a",
        "casing": "#e0b258",
        "width": (4.0, 22.0),
        "casing_width": (6.0, 27.0),
    },
    {
        "name": "secondary",
        "color": "#fde3a8",
        "casing": "#ddc78c",
        "width": (3.2, 18.0),
        "casing_width": (5.0, 22.5),
    },
    {
        "name": "tertiary",
        "color": "#ffffff",
        "casing": "#d2cbbe",
        "width": (2.6, 14.0),
        "casing_width": (4.4, 18.0),
    },
    {
        "name": "minor",
        "color": "#ffffff",
        "casing": "#d5cec2",
        "width": (2.0, 11.0),
        "casing_width": (3.4, 14.5),
    },
    {
        "name": "service",
        "color": "#ffffff",
        "casing": "#d9d2c6",
        "width": (1.4, 7.0),
        "casing_width": (2.6, 9.5),
    },
    {
        "name": "path",
        "color": "#d8cdbc",
        "casing": "#00000000",
        "width": (1.0, 3.0),
        "casing_width": (0.0, 0.0),
    },
    {
        "name": "rail",
        "color": "#c3bfb6",
        "casing": "#e0dcd4",
        "width": (1.2, 3.5),
        "casing_width": (2.4, 6.5),
    },
    {
        "name": "ferry",
        "color": "#8fb8d2",
        "casing": "#00000000",
        "width": (1.0, 2.5),
        "casing_width": (0.0, 0.0),
    },
    {
        "name": "waterway",
        "color": "#a3cee6",
        "casing": "#00000000",
        "width": (1.5, 9.0),
        "casing_width": (0.0, 0.0),
    },
    {
        "name": "building_outline",
        "color": "#d6d0c2",
        "casing": "#00000000",
        "width": (0.6, 1.0),
        "casing_width": (0.0, 0.0),
    },
]

# -- rules: which source layer and class becomes which bucket and style -------
# `min_zoom` on a rule gates the whole layer before it is even parsed; the one
# on a class entry gates just that class. Both are the LOD switch: geometry
# below its zoom is not decoded, not uploaded, and not drawn.
#
# `outline` on a fill rule additionally emits the polygon's rings as lines,
# which is how buildings read as separate blocks rather than one grey mass.

RULES: dict[str, dict] = {
    "water": {
        "bucket": "water",
        "kind": "fill",
        "min_zoom": 0,
        "classes": {"*": {"style": "water"}},
    },
    "waterway": {
        "bucket": "waterway",
        "kind": "line",
        "min_zoom": 12,
        "classes": {"*": {"style": "waterway"}},
    },
    "landcover": {
        "bucket": "land",
        "kind": "fill",
        "min_zoom": 7,
        "classes": {
            "wood": {"style": "wood"},
            "grass": {"style": "grass"},
            "farmland": {"style": "farmland"},
            "sand": {"style": "sand"},
            "ice": {"style": "ice"},
            "wetland": {"style": "grass"},
            "*": {"style": "grass"},
        },
    },
    "park": {
        "bucket": "land",
        "kind": "fill",
        "min_zoom": 9,
        "classes": {"*": {"style": "park"}},
    },
    "landuse": {
        "bucket": "land",
        "kind": "fill",
        "min_zoom": 11,
        "classes": {
            "residential": {"style": "residential", "min_zoom": 12},
            "suburb": {"style": "residential", "min_zoom": 12},
            "neighbourhood": {"style": "residential", "min_zoom": 13},
            "commercial": {"style": "commercial"},
            "industrial": {"style": "industrial"},
            "retail": {"style": "retail"},
            "school": {"style": "institution"},
            "hospital": {"style": "institution"},
            "university": {"style": "institution"},
            "kindergarten": {"style": "institution"},
            "cemetery": {"style": "cemetery"},
            "pitch": {"style": "pitch"},
            "stadium": {"style": "pitch"},
            "*": None,
        },
    },
    "aeroway": {
        "bucket": "land",
        "kind": "fill",
        "min_zoom": 11,
        "classes": {"aerodrome": {"style": "aerodrome"}, "*": None},
    },
    "building": {
        "bucket": "building",
        "kind": "fill",
        "min_zoom": 15,
        # Outlines are the single most expensive thing in the style: a
        # four-point footprint costs two fill triangles and eight outline
        # ones. They only earn that at the zoom where an individual building
        # is something the driver is actually looking at.
        "outline": {"bucket": "road", "style": "building_outline", "min_zoom": 17},
        "classes": {"*": {"style": "building"}},
    },
    "transportation": {
        "bucket": "road",
        "kind": "line",
        "min_zoom": 0,
        "classes": {
            "motorway": {"style": "motorway", "min_zoom": 5},
            "trunk": {"style": "trunk", "min_zoom": 6},
            "primary": {"style": "primary", "min_zoom": 8},
            "secondary": {"style": "secondary", "min_zoom": 10},
            "tertiary": {"style": "tertiary", "min_zoom": 11},
            "minor": {"style": "minor", "min_zoom": 13},
            "service": {"style": "service", "min_zoom": 15},
            "track": {"style": "service", "min_zoom": 15},
            "path": {"style": "path", "min_zoom": 15},
            "rail": {"style": "rail", "min_zoom": 12},
            "transit": {"style": "rail", "min_zoom": 13},
            "ferry": {"style": "ferry", "min_zoom": 10},
            # Anything unlisted -- construction classes, aerialways, busways --
            # is drawn as a minor road rather than silently disappearing.
            "*": {"style": "minor", "min_zoom": 14},
        },
    },
}


def _rgba(value: str) -> list[float]:
    """``#rrggbb`` or ``#rrggbbaa`` to four floats in 0..1."""
    text = value.lstrip("#")
    if len(text) not in (6, 8):
        raise ValueError(f"colour must be #rrggbb or #rrggbbaa, got {value!r}")
    channels = [int(text[i : i + 2], 16) / 255.0 for i in range(0, len(text), 2)]
    if len(channels) == 3:
        channels.append(1.0)
    return channels


def style_payload() -> dict:
    """The style tables, resolved to the indices the vertex attributes carry.

    Style names are for humans reading :data:`RULES`; the page and the worker
    only ever see integers. Resolving here means a typo in a rule is a
    start-up error in one place, not a silently unstyled road class.

    Returns:
        A JSON-ready dict with ``background``, ``zoom_stops``, ``buckets``,
        ``fill_styles``, ``line_styles`` and ``rules``.
    """
    fill_index = {name: i for i, (name, _, _) in enumerate(FILL_STYLES)}
    line_index = {entry["name"]: i for i, entry in enumerate(LINE_STYLES)}

    def resolve(rule: dict, entry: dict | None) -> dict | None:
        if entry is None:
            return None
        table = fill_index if rule["kind"] == "fill" else line_index
        name = entry["style"]
        if name not in table:
            raise KeyError(f"unknown {rule['kind']} style {name!r}")
        return {"style": table[name], "min_zoom": entry.get("min_zoom", rule["min_zoom"])}

    # A bucket holds one vertex layout, so its kind is whatever its rules say.
    # Deriving it here rather than listing it separately means a rule that
    # sends a line layer into a fill bucket is caught at start-up.
    bucket_kinds: dict[str, str] = {}

    def claim(bucket: str, kind: str) -> None:
        existing = bucket_kinds.setdefault(bucket, kind)
        if existing != kind:
            raise ValueError(f"bucket {bucket!r} is used as both {existing} and {kind}")

    rules = {}
    for layer, rule in RULES.items():
        claim(rule["bucket"], rule["kind"])
        if rule.get("outline") is not None:
            claim(rule["outline"]["bucket"], "line")
        resolved = {
            "bucket": rule["bucket"],
            "kind": rule["kind"],
            "min_zoom": rule["min_zoom"],
            "classes": {key: resolve(rule, entry) for key, entry in rule["classes"].items()},
        }
        outline = rule.get("outline")
        if outline is not None:
            resolved["outline"] = {
                "bucket": outline["bucket"],
                "style": line_index[outline["style"]],
                "min_zoom": outline.get("min_zoom", rule["min_zoom"]),
            }
        rules[layer] = resolved

    missing = [bucket for bucket in bucket_kinds if bucket not in BUCKET_ORDER]
    if missing:
        raise ValueError(f"rules target buckets missing from BUCKET_ORDER: {missing}")

    label_index = {entry["name"]: i for i, entry in enumerate(LABEL_STYLES)}
    label_priority = {entry["name"]: entry["priority"] for entry in LABEL_STYLES}

    def resolve_label(rule: dict, entry: dict | None) -> dict | None:
        if entry is None:
            return None
        name = entry["style"]
        if name not in label_index:
            raise KeyError(f"unknown label style {name!r}")
        return {
            "style": label_index[name],
            "min_zoom": entry.get("min_zoom", rule["min_zoom"]),
            "max_zoom": entry.get("max_zoom"),
            # Priority lives on the style, not on the rule, so every layer that
            # shares a style competes on equal terms.
            "priority": label_priority[name],
        }

    label_rules = {
        layer: {
            "placement": rule["placement"],
            "min_zoom": rule["min_zoom"],
            "icon": rule["icon"],
            "max_rank": rule["max_rank"],
            "classes": {key: resolve_label(rule, entry) for key, entry in rule["classes"].items()},
        }
        for layer, rule in LABEL_RULES.items()
    }

    return {
        "background": _rgba(BACKGROUND),
        "zoom_stops": list(ZOOM_STOPS),
        "buckets": list(BUCKET_ORDER),
        "bucket_kinds": {bucket: bucket_kinds.get(bucket, "fill") for bucket in BUCKET_ORDER},
        "fill_styles": [
            {"name": name, "color": _rgba(color)[:3] + [opacity]}
            for name, color, opacity in FILL_STYLES
        ],
        "line_styles": [
            {
                "name": entry["name"],
                "color": _rgba(entry["color"]),
                "casing": _rgba(entry["casing"]),
                "width": list(entry["width"]),
                "casing_width": list(entry["casing_width"]),
            }
            for entry in LINE_STYLES
        ],
        "rules": rules,
        "label_name_fields": list(LABEL_NAME_FIELDS),
        "label_rules": label_rules,
        "label_styles": [
            {
                "name": entry["name"],
                "size": entry["size"],
                "color": _rgba(entry["color"]),
                "halo": _rgba(entry["halo"]),
                "halo_width": entry["halo_width"],
                "icon_size": entry["icon_size"],
                "text_offset": entry["text_offset"],
            }
            for entry in LABEL_STYLES
        ],
    }


# -- labels -------------------------------------------------------------------
# Text is styled separately from geometry because it is placed separately: a
# road's colour is decided per vertex, but a road *name* competes for screen
# space against every other name and may simply not be drawn. `priority` is how
# hard a label fights for its place -- higher wins, and a feature's own rank is
# subtracted from it, so the most important park keeps its name when the
# smallest one loses it.

#: Which tag holds the name, in order of preference. In Vietnam the plain
#: `name` is already Vietnamese, so a transliteration is only a fallback.
LABEL_NAME_FIELDS: list[str] = ["name", "name:latin", "name:en"]

#: index = position in this list, exactly like the geometry style tables.
LABEL_STYLES: list[dict] = [
    {
        "name": "place_city",
        "size": 19.0,
        "color": "#2f353c",
        "halo": "#ffffff",
        "halo_width": 1.8,
        "priority": 1000,
        "icon_size": 0.0,
        "text_offset": 0.0,
    },
    {
        "name": "place_suburb",
        "size": 14.5,
        "color": "#3b424a",
        "halo": "#ffffff",
        "halo_width": 1.6,
        "priority": 800,
        "icon_size": 0.0,
        "text_offset": 0.0,
    },
    {
        "name": "place_neighbourhood",
        "size": 12.0,
        "color": "#6c737c",
        "halo": "#ffffff",
        "halo_width": 1.5,
        "priority": 250,
        "icon_size": 0.0,
        "text_offset": 0.0,
    },
    {
        "name": "road_major",
        "size": 13.0,
        "color": "#4f565e",
        "halo": "#ffffff",
        "halo_width": 1.8,
        "priority": 700,
        "icon_size": 0.0,
        "text_offset": 0.0,
    },
    {
        "name": "water",
        "size": 12.5,
        "color": "#5f9dc4",
        "halo": "#ffffff",
        "halo_width": 1.2,
        "priority": 450,
        "icon_size": 0.0,
        "text_offset": 0.0,
    },
    {
        "name": "road_minor",
        "size": 11.5,
        "color": "#5e656d",
        "halo": "#ffffff",
        "halo_width": 1.6,
        "priority": 500,
        "icon_size": 0.0,
        "text_offset": 0.0,
    },
    {
        # A point of interest is an icon with its name under it, so it is the
        # one style where the icon size and the text's drop below it matter.
        "name": "poi",
        "size": 11.0,
        "color": "#4c535b",
        "halo": "#ffffff",
        "halo_width": 1.4,
        "priority": 100,
        "icon_size": 15.0,
        "text_offset": 15.0,
    },
]

#: Which source layer becomes which label style. `placement` is "point" for a
#: name that sits on a spot and "line" for one that lies along a road.
#: `max_rank` drops everything the tile itself considers unimportant, before
#: any of it reaches the collision grid.
LABEL_RULES: dict[str, dict] = {
    "place": {
        "placement": "point",
        "min_zoom": 8,
        "icon": False,
        "max_rank": None,
        "classes": {
            "city": {"style": "place_city", "min_zoom": 8, "max_zoom": 14},
            "town": {"style": "place_suburb", "min_zoom": 10, "max_zoom": 15},
            "village": {"style": "place_neighbourhood", "min_zoom": 12, "max_zoom": 16},
            "suburb": {"style": "place_suburb", "min_zoom": 12, "max_zoom": 17},
            "quarter": {"style": "place_neighbourhood", "min_zoom": 13, "max_zoom": 17},
            "neighbourhood": {"style": "place_neighbourhood", "min_zoom": 14, "max_zoom": 16},
            "*": None,
        },
    },
    "transportation_name": {
        "placement": "line",
        "min_zoom": 12,
        "icon": False,
        "max_rank": None,
        "classes": {
            "motorway": {"style": "road_major", "min_zoom": 12},
            "trunk": {"style": "road_major", "min_zoom": 13},
            "primary": {"style": "road_major", "min_zoom": 13},
            "secondary": {"style": "road_major", "min_zoom": 14},
            "tertiary": {"style": "road_minor", "min_zoom": 15},
            "minor": {"style": "road_minor", "min_zoom": 16},
            "service": {"style": "road_minor", "min_zoom": 18},
            "*": None,
        },
    },
    "water_name": {
        "placement": "point",
        "min_zoom": 10,
        "icon": False,
        "max_rank": None,
        "classes": {"*": {"style": "water", "min_zoom": 10}},
    },
    "poi": {
        "placement": "point",
        "min_zoom": 16,
        "icon": True,
        "max_rank": 24,
        "classes": {"*": {"style": "poi", "min_zoom": 16}},
    },
}
