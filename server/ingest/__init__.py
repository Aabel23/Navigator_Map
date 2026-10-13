"""Ingest -- the door every piece of outside data comes through.

    from ingest import TrafficCollector, parse_probe, normalize_report
    from ingest.external_sources.digitraffic import DigitrafficProvider

    collector = TrafficCollector([DigitrafficProvider()], fallback=simulated)
    collection = collector.collect(area)

Owns:
    receiving, validating, normalising, timestamping and attributing external
    data: provider feeds, GPS probes from clients, incident reports typed by
    an operator. Also owns surviving a source that is down, and saying which
    one it was.

Does not own:
    what any of it means. No traffic level, no congestion cost, no decision
    about whether a road is closed. Those are judgements, they belong to
    `traffic` and `roadstate`, and keeping them out of here is what lets a
    second provider be added without a second opinion arriving with it.

Records deliberately carry no traffic level, and reports deliberately carry no
condition kind. What leaves this block is what the source said -- a speed, a
free-flow reference, a title, a validity window -- and the interpretation
happens one block downstream, in one place, for every provider at once.

Layout:
    models.py           the record types, plus the Observations batch
    provider.py         the seam a source plugs into
    gps/                client position reports, validated at the door
    traffic/            fetching from traffic feeds, and surviving them
    incidents/          normalising incident reports from anywhere
    external_sources/   the feeds themselves: Digitraffic, and a model

This module is the block's entire public surface. Stdlib-only.
"""

from domain import BBox, Coord

from .errors import BadResponse, IngestError, OutsideCoverage, ProviderUnavailable
from .gps import (
    MAX_PLAUSIBLE_KPH,
    MAX_PROBE_AGE,
    MIN_MOVING_KPH,
    PROBE_CONFIDENCE,
    PROBE_SOURCE,
    GpsProbe,
    parse_probe,
    probes_to_observations,
)
from .http import HttpClient
from .incidents import REPORT_SOURCE, normalize_report, normalize_reports, report_of_incident
from .models import (
    SIMULATED_SOURCE,
    IncidentKind,
    Observations,
    Severity,
    TrafficIncident,
    TrafficObservation,
    TrafficSegment,
    coords_of,
)
from .provider import RoadLike, RoadNetwork, TrafficProvider
from .traffic import Collection, TrafficCollector

__all__ = [
    # Geography, re-exported so a consumer needs one import
    "BBox",
    "Coord",
    # Records
    "Observations",
    "TrafficObservation",
    "TrafficSegment",
    "TrafficIncident",
    "IncidentKind",
    "Severity",
    "coords_of",
    "SIMULATED_SOURCE",
    # The provider seam
    "TrafficProvider",
    "RoadNetwork",
    "RoadLike",
    # Collecting from feeds
    "TrafficCollector",
    "Collection",
    # GPS probes
    "GpsProbe",
    "parse_probe",
    "probes_to_observations",
    "PROBE_SOURCE",
    "PROBE_CONFIDENCE",
    "MAX_PLAUSIBLE_KPH",
    "MIN_MOVING_KPH",
    "MAX_PROBE_AGE",
    # Incident reports
    "normalize_report",
    "normalize_reports",
    "report_of_incident",
    "REPORT_SOURCE",
    # Transport, exposed so a test can inject a fake
    "HttpClient",
    # Errors
    "IngestError",
    "ProviderUnavailable",
    "OutsideCoverage",
    "BadResponse",
]
