from django.db import models


class FuelStation(models.Model):
    """A truck stop selling diesel, keyed on the OPIS Truckstop ID from the source CSV.

    Static identity + current price only — price history lives in PriceHistory so
    the current row can be updated in place without losing prior prices.
    """

    class GeocodeSource(models.TextChoices):
        CITY = "city", "City centroid"
        STATE_CENTROID = "state_centroid", "State/province centroid fallback"

    opis_id = models.PositiveIntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=8)
    rack_id = models.PositiveIntegerField()

    current_price = models.DecimalField(max_digits=6, decimal_places=3)

    latitude = models.FloatField()
    longitude = models.FloatField()
    geocode_source = models.CharField(max_length=32, choices=GeocodeSource.choices)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["state", "city"]),
        ]
        ordering = ["opis_id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state})"


class PriceHistory(models.Model):
    """Append-only log of price changes for a station, newest last."""

    station = models.ForeignKey(FuelStation, on_delete=models.CASCADE, related_name="price_history")
    price = models.DecimalField(max_digits=6, decimal_places=3)
    effective_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["station", "effective_at"]
        indexes = [
            models.Index(fields=["station", "effective_at"]),
        ]
        verbose_name_plural = "price histories"

    def __str__(self) -> str:
        return f"{self.station_id} @ {self.effective_at:%Y-%m-%d}: {self.price}"


class GeocodeCache(models.Model):
    """Permanent cache of Nominatim geocoding results for user-supplied place names.

    Keyed on the normalized query string so repeat lookups of the same place
    (e.g. "Dallas, TX") never hit the network twice.
    """

    query = models.CharField(max_length=255, unique=True, db_index=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    display_name = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.query
