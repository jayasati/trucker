"""Name -> (lat, lng) resolution for user-supplied start/finish input.

Coordinate strings ("lat,lng") pass through with no DB or network access.
Place names ("City, ST") hit Nominatim at most once per distinct query,
ever — results are cached permanently in GeocodeCache (see CLAUDE.md's
request-path budget: max 2 Nominatim calls, one per endpoint).
"""

from __future__ import annotations

import re

import requests
from django.conf import settings

NOMINATIM_TIMEOUT_SECONDS = 10
NOMINATIM_USER_AGENT = "FuelRouteOptimizer/1.0 (assessment project; contact: digisevakpanservice@gmail.com)"

_COORD_RE = re.compile(
    r"^\s*(?P<lat>-?\d+(?:\.\d+)?)\s*,\s*(?P<lng>-?\d+(?:\.\d+)?)\s*$"
)


class GeocodeError(Exception):
    """Base class for geocoding failures."""


class GeocodeNotFoundError(GeocodeError):
    """No matching place was found. Maps to HTTP 404 at the API layer."""


class GeocodeServiceError(GeocodeError):
    """Nominatim was unreachable or returned an unusable response."""


def parse_coordinate_string(value: str) -> tuple[float, float] | None:
    """Return (lat, lng) if `value` is a bare "lat,lng" pair, else None."""
    match = _COORD_RE.match(value)
    if not match:
        return None
    lat, lng = float(match["lat"]), float(match["lng"])
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None
    return lat, lng


def geocode_place(query: str) -> tuple[float, float]:
    """Resolve `query` to (lat, lng): a coordinate pair passes through directly,
    otherwise it is looked up (cache first, then Nominatim) as a place name.
    """
    coords = parse_coordinate_string(query)
    if coords is not None:
        return coords

    from routing.models import GeocodeCache  # deferred: avoid app-registry import order issues

    normalized = query.strip().lower()
    if not normalized:
        raise GeocodeNotFoundError("Empty location query.")

    cached = GeocodeCache.objects.filter(query=normalized).first()
    if cached is not None:
        return cached.latitude, cached.longitude

    lat, lng, display_name = _lookup_nominatim(query)

    GeocodeCache.objects.update_or_create(
        query=normalized,
        defaults={"latitude": lat, "longitude": lng, "display_name": display_name},
    )
    return lat, lng


def _lookup_nominatim(query: str) -> tuple[float, float, str]:
    url = f"{settings.NOMINATIM_BASE_URL}/search"
    params = {"q": query, "format": "json", "limit": 1, "countrycodes": "us,ca"}
    headers = {"User-Agent": NOMINATIM_USER_AGENT}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=NOMINATIM_TIMEOUT_SECONDS)
        response.raise_for_status()
        results = response.json()
    except requests.Timeout as exc:
        raise GeocodeServiceError("Nominatim request timed out.") from exc
    except requests.RequestException as exc:
        raise GeocodeServiceError(f"Nominatim request failed: {exc}") from exc
    except ValueError as exc:
        raise GeocodeServiceError("Nominatim returned an invalid (non-JSON) response.") from exc

    if not results:
        raise GeocodeNotFoundError(f"Location not found: {query!r}")

    result = results[0]
    try:
        lat = float(result["lat"])
        lng = float(result["lon"])
    except (KeyError, ValueError) as exc:
        raise GeocodeServiceError("Nominatim returned an unusable result.") from exc

    return lat, lng, result.get("display_name", "")
