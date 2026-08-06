"""Parsing, dedupe, and upsert logic for the fuel-price CSV feed.

Split out of the management command so dedupe/parsing can be unit tested as
plain functions, with no Django test database required.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.utils import timezone

from routing.models import FuelStation, PriceHistory
from routing.services.geocoding import geocode_city_state


@dataclass(frozen=True)
class StationRow:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    price: Decimal


@dataclass
class UpsertStats:
    unique_stations: int = 0
    created: int = 0
    price_updated: int = 0
    unchanged: int = 0
    geocoded_city: int = 0
    geocoded_state_centroid: int = 0


class RowParseError(ValueError):
    pass


def parse_csv_rows(path: str | Path) -> list[StationRow]:
    """Read the raw CSV into StationRow records, in file order. No dedup."""
    rows: list[StationRow] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for line_number, raw in enumerate(reader, start=2):
            try:
                rows.append(
                    StationRow(
                        opis_id=int(raw["OPIS Truckstop ID"]),
                        name=raw["Truckstop Name"].strip(),
                        address=raw["Address"].strip(),
                        city=raw["City"].strip(),
                        state=raw["State"].strip(),
                        rack_id=int(raw["Rack ID"]),
                        price=Decimal(raw["Retail Price"]).quantize(Decimal("0.001")),
                    )
                )
            except (KeyError, ValueError, InvalidOperation) as exc:
                raise RowParseError(f"Line {line_number}: {exc}") from exc
    return rows


def dedupe_rows(rows: list[StationRow]) -> list[StationRow]:
    """Keep one row per OPIS ID: the cheapest price, first-seen on ties.

    Source data has occasional duplicate OPIS IDs from re-listed stations
    (same truck stop under two names/rows) — cheapest price wins since that's
    the price a driver would actually be quoted.
    """
    best: dict[int, StationRow] = {}
    order: list[int] = []
    for row in rows:
        current = best.get(row.opis_id)
        if current is None:
            best[row.opis_id] = row
            order.append(row.opis_id)
        elif row.price < current.price:
            best[row.opis_id] = row
    return [best[opis_id] for opis_id in order]


def upsert_stations(rows: list[StationRow], *, now: datetime | None = None) -> UpsertStats:
    """Idempotent upsert keyed on opis_id: new station -> insert, existing -> update price.

    A PriceHistory row is appended only when the price actually changed (or
    the station is new), so re-running against unchanged data is a no-op
    beyond touching `updated_at`.
    """
    now = now or timezone.now()
    stats = UpsertStats(unique_stations=len(rows))

    existing = {s.opis_id: s for s in FuelStation.objects.all()}

    to_create: list[FuelStation] = []
    to_update: list[FuelStation] = []
    history_entries: list[PriceHistory] = []
    changed_opis_ids: set[int] = set()

    for row in rows:
        lat, lng, source = geocode_city_state(row.city, row.state)
        if source == "city":
            stats.geocoded_city += 1
        else:
            stats.geocoded_state_centroid += 1

        station = existing.get(row.opis_id)
        if station is None:
            station = FuelStation(
                opis_id=row.opis_id,
                name=row.name,
                address=row.address,
                city=row.city,
                state=row.state,
                rack_id=row.rack_id,
                current_price=row.price,
                latitude=lat,
                longitude=lng,
                geocode_source=source,
            )
            to_create.append(station)
            stats.created += 1
        else:
            price_changed = station.current_price != row.price
            station.name = row.name
            station.address = row.address
            station.city = row.city
            station.state = row.state
            station.rack_id = row.rack_id
            station.current_price = row.price
            station.latitude = lat
            station.longitude = lng
            station.geocode_source = source
            to_update.append(station)
            if price_changed:
                stats.price_updated += 1
                changed_opis_ids.add(station.opis_id)
            else:
                stats.unchanged += 1

    if to_create:
        FuelStation.objects.bulk_create(to_create, batch_size=500)
        history_entries.extend(
            PriceHistory(station=station, price=station.current_price, effective_at=now)
            for station in to_create
        )

    if to_update:
        FuelStation.objects.bulk_update(
            to_update,
            fields=[
                "name",
                "address",
                "city",
                "state",
                "rack_id",
                "current_price",
                "latitude",
                "longitude",
                "geocode_source",
            ],
            batch_size=500,
        )
        history_entries.extend(
            PriceHistory(station=station, price=station.current_price, effective_at=now)
            for station in to_update
            if station.opis_id in changed_opis_ids
        )

    if history_entries:
        PriceHistory.objects.bulk_create(history_entries, batch_size=500)

    return stats
