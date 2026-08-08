"""End-to-end pipeline: geocode -> OSRM route -> corridor match -> optimize.

Kept separate from the DRF view so the pipeline itself has no HTTP-specific
concerns (status codes, request/response objects, caching) mixed in — the
view's job is translating between this and the wire format.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from routing.models import FuelStation
from routing.services.corridor import CorridorStation, match_stations_to_corridor
from routing.services.geocode import geocode_place
from routing.services.optimizer import FuelStop, StationCandidate, plan_fuel_stops
from routing.services.osrm import get_route
from routing.spatial_index import SpatialIndex


@dataclass(frozen=True)
class RoutePlan:
    total_distance_miles: float
    total_fuel_cost: float
    fuel_stops: list[FuelStop]
    all_stops: list[FuelStop]
    route_geometry: list[tuple[float, float]]  # (lat, lng), in route order
    price_version: int


def plan_route(start_query: str, finish_query: str) -> RoutePlan:
    start_coords = geocode_place(start_query)
    finish_coords = geocode_place(finish_query)

    route_result = get_route(start_coords, finish_coords)

    if not SpatialIndex.is_loaded():
        SpatialIndex.load()
    price_version = SpatialIndex.price_version

    corridor_matches = match_stations_to_corridor(route_result.geometry)
    candidates = _build_candidates(corridor_matches)

    optimizer_result = plan_fuel_stops(
        route_result.distance_miles,
        candidates,
        tank_range_miles=settings.TANK_RANGE_MILES,
        mpg=settings.MPG,
        min_purchase_gallons=settings.MIN_PURCHASE_GALLONS,
        start_search_radius_miles=settings.START_SEARCH_RADIUS_MILES,
    )

    return RoutePlan(
        total_distance_miles=route_result.distance_miles,
        total_fuel_cost=optimizer_result.total_fuel_cost,
        fuel_stops=optimizer_result.fuel_stops,
        all_stops=optimizer_result.all_stops,
        route_geometry=route_result.geometry,
        price_version=price_version,
    )


def _build_candidates(corridor_matches: list[CorridorStation]) -> list[StationCandidate]:
    if not corridor_matches:
        return []

    station_ids = [match.station_id for match in corridor_matches]
    stations_by_id = {station.id: station for station in FuelStation.objects.filter(id__in=station_ids)}

    candidates = []
    for match in corridor_matches:
        station = stations_by_id.get(match.station_id)
        if station is None:
            continue
        candidates.append(
            StationCandidate(
                station_id=station.id,
                name=station.name,
                address=station.address,
                city=station.city,
                state=station.state,
                price=float(station.current_price),
                miles_from_start=match.miles_from_start,
                detour_miles=match.detour_miles,
                latitude=station.latitude,
                longitude=station.longitude,
            )
        )
    return candidates
