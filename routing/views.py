import hashlib
import time

from django.conf import settings
from django.core.cache import cache
from django.views.generic import TemplateView
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import RouteRequestSerializer
from routing.services.dashboard_stats import compute_dashboard_stats
from routing.services.geocode import GeocodeNotFoundError, GeocodeServiceError
from routing.services.optimizer import NoReachableStationError
from routing.services.osrm import OSRMError
from routing.services.route_planner import RoutePlan, plan_route
from routing.spatial_index import SpatialIndex

DASHBOARD_STATS_CACHE_TTL_SECONDS = 300


class RoutePlannerPageView(TemplateView):
    template_name = "route_planner.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tank_range_miles"] = int(settings.TANK_RANGE_MILES)
        context["mpg"] = int(settings.MPG)
        context["tank_gallons"] = round(settings.TANK_RANGE_MILES / settings.MPG)
        context["active_tab"] = "routes"
        return context


class DashboardPageView(TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "dashboard"
        context["stats"] = self._get_stats()
        return context

    @staticmethod
    def _get_stats():
        if not SpatialIndex.is_loaded():
            SpatialIndex.load()
        cache_key = f"dashboard_stats:v{SpatialIndex.price_version}"
        stats = cache.get(cache_key)
        if stats is None:
            stats = compute_dashboard_stats()
            cache.set(cache_key, stats, timeout=DASHBOARD_STATS_CACHE_TTL_SECONDS)
        return stats


def _cache_key(start: str, finish: str, price_version: int) -> str:
    # Hashed rather than raw text: arbitrary user input (spaces, colons, unicode)
    # isn't a safe cache key for every backend (e.g. memcached rejects it).
    normalized = f"{start.strip().lower()}:{finish.strip().lower()}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"route:v{price_version}:{digest}"


def _route_to_geojson(route_geometry: list[tuple[float, float]]) -> dict:
    return {
        "type": "LineString",
        "coordinates": [[lng, lat] for lat, lng in route_geometry],
    }


def _serialize_plan(plan: RoutePlan) -> dict:
    payload = {
        "total_distance_miles": round(plan.total_distance_miles, 1),
        "total_fuel_cost": round(plan.total_fuel_cost, 2),
        "fuel_stops": [
            {
                "name": stop.name,
                "address": stop.address,
                "city": stop.city,
                "state": stop.state,
                "price_per_gallon": round(stop.price_per_gallon, 3),
                "gallons": round(stop.gallons, 2),
                "cost": round(stop.cost, 2),
                "miles_from_start": round(stop.miles_from_start, 1),
                "detour_miles": round(stop.detour_miles, 1),
                "latitude": round(stop.latitude, 5),
                "longitude": round(stop.longitude, 5),
            }
            for stop in plan.fuel_stops
        ],
        "route": _route_to_geojson(plan.route_geometry),
        "price_version": plan.price_version,
    }
    if plan.estimated_trip_cost is not None:
        payload["estimated_trip_cost"] = round(plan.estimated_trip_cost, 2)
    return payload


class RouteView(APIView):
    """POST /api/route/ — see CLAUDE.md for the full request/response contract."""

    def post(self, request):
        start_time = time.monotonic()

        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)

        start_query = serializer.validated_data["start"]
        finish_query = serializer.validated_data["finish"]

        if not SpatialIndex.is_loaded():
            SpatialIndex.load()
        cache_key = _cache_key(start_query, finish_query, SpatialIndex.price_version)

        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            payload = dict(cached_payload)
            payload["cached"] = True
            payload["compute_ms"] = round((time.monotonic() - start_time) * 1000, 2)
            return Response(payload, status=200)

        try:
            plan = plan_route(start_query, finish_query)
        except GeocodeNotFoundError as exc:
            return Response({"error": str(exc)}, status=404)
        except (GeocodeServiceError, OSRMError) as exc:
            return Response({"error": str(exc)}, status=502)
        except NoReachableStationError as exc:
            return Response({"error": str(exc)}, status=422)

        payload = _serialize_plan(plan)
        cache.set(cache_key, payload, timeout=settings.ROUTE_CACHE_TTL_SECONDS)

        payload = dict(payload)
        payload["cached"] = False
        payload["compute_ms"] = round((time.monotonic() - start_time) * 1000, 2)
        return Response(payload, status=200)
