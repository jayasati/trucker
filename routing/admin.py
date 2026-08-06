from django.contrib import admin

from .models import FuelStation, GeocodeCache, PriceHistory


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("opis_id", "name", "city", "state", "current_price", "geocode_source")
    list_filter = ("state", "geocode_source")
    search_fields = ("name", "city", "opis_id")


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ("station", "price", "effective_at")
    list_filter = ("effective_at",)


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(admin.ModelAdmin):
    list_display = ("query", "latitude", "longitude", "created_at")
