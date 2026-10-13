

# ============================================================
# REQUEST
# ============================================================
import json
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

SOUTH = 10.35
WEST = 106.35
NORTH = 11.17
EAST = 106.95

query = f"""
[out:json][timeout:900];

(
    nwr(
        {SOUTH},
        {WEST},
        {NORTH},
        {EAST}
    );
);

out geom meta;
"""

headers = {
    "User-Agent": "live-map-dev/0.1 (contact@example.com)",
    "Accept": "application/json",
}

print("Sending request to Overpass...")

response = requests.post(
    OVERPASS_URL,
    data={"data": query},
    headers=headers,
    timeout=1000,
)

print("HTTP:", response.status_code)

if response.status_code != 200:
    print(response.text[:5000])
    response.raise_for_status()

data = response.json()

with open("hcm_osm_raw.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Saved:", len(data["elements"]), "elements")

# ============================================================
# PARSE JSON
# ============================================================

try:
    data = response.json()
except ValueError:
    print("Overpass did not return valid JSON.")
    print(response.text[:2000])
    raise SystemExit(1)


# ============================================================
# SAVE RAW JSON
# ============================================================

with OUTPUT_FILE.open("w", encoding="utf-8") as f:
    json.dump(
        data,
        f,
        ensure_ascii=False,
        indent=2,
    )


# ============================================================
# PRINT GENERAL INFORMATION
# ============================================================

print("Request completed.")
print()

print("Top-level fields:")
for key, value in data.items():

    if key == "elements":
        print(f"  {key}: {len(value)} objects")

    else:
        print(f"  {key}: {value}")

print()
print(f"Saved to: {OUTPUT_FILE.resolve()}")
print()


# ============================================================
# COUNT OBJECT TYPES
# ============================================================

elements = data.get("elements", [])

type_count = {
    "node": 0,
    "way": 0,
    "relation": 0,
}

for element in elements:
    element_type = element.get("type")

    if element_type in type_count:
        type_count[element_type] += 1


print("Object counts:")
for element_type, count in type_count.items():
    print(f"  {element_type}: {count}")

print()


# ============================================================
# PRINT EVERY OBJECT
# ============================================================

if PRINT_ALL:

    for index, element in enumerate(elements, start=1):

        print("=" * 80)
        print(f"OBJECT #{index}")
        print("=" * 80)

        # In toàn bộ fields mà Overpass trả về
        #
        # Không tự lọc:
        # type
        # id
        # lat
        # lon
        # tags
        # nodes
        # geometry
        # timestamp
        # version
        # changeset
        # uid
        # user
        # v.v.
        #
        # JSON pretty-print giúp nhìn rõ cấu trúc.
        print(
            json.dumps(
                element,
                ensure_ascii=False,
                indent=2,
            )
        )

        print()