"""Single-call OSRM route lookup. The one external call made for coordinate input."""

from __future__ import annotations

from dataclasses import dataclass

import polyline
import requests
from django.conf import settings

OSRM_TIMEOUT_SECONDS = 10


class OSRMError(Exception):
    """Raised for any failure to obtain a route: network error, timeout, or no route found."""


@dataclass(frozen=True)
class RouteResult:
    distance_miles: float
    duration_seconds: float
    geometry: list[tuple[float, float]]  # (lat, lng) points, in route order


def get_route(start: tuple[float, float], finish: tuple[float, float]) -> RouteResult:
    """Fetch the driving route between two (lat, lng) points from the public OSRM server.

    Exactly one HTTP call, per the request-path budget in CLAUDE.md.
    """
    start_lat, start_lng = start
    finish_lat, finish_lng = finish
    url = (
        f"{settings.OSRM_BASE_URL}/route/v1/driving/"
        f"{start_lng},{start_lat};{finish_lng},{finish_lat}"
    )
    # "simplified" (Douglas-Peucker) rather than "full": corridor matching already
    # downsamples to ~1 point/2mi internally, and the response geometry only needs
    # to be map-display quality, not every OSRM road-shape vertex.
    params = {"overview": "simplified", "geometries": "polyline"}

    try:
        response = requests.get(url, params=params, timeout=OSRM_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise OSRMError("OSRM request timed out.") from exc
    except requests.RequestException as exc:
        raise OSRMError(f"OSRM request failed: {exc}") from exc
    except ValueError as exc:
        raise OSRMError("OSRM returned an invalid (non-JSON) response.") from exc

    if payload.get("code") != "Ok":
        message = payload.get("message", payload.get("code", "unknown error"))
        raise OSRMError(f"OSRM could not compute a route: {message}")

    routes = payload.get("routes") or []
    if not routes:
        raise OSRMError("OSRM returned no routes.")

    route = routes[0]
    distance_miles = route["distance"] / 1609.344
    duration_seconds = route["duration"]
    geometry = polyline.decode(route["geometry"])

    return RouteResult(
        distance_miles=distance_miles,
        duration_seconds=duration_seconds,
        geometry=geometry,
    )
