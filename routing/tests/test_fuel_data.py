from decimal import Decimal

import pytest

from routing.models import FuelStation, PriceHistory
from routing.services.fuel_data import StationRow, dedupe_rows, upsert_stations


def _row(opis_id=1, price="3.500", city="Big Cabin", state="OK", name="STOP", rack_id=100):
    return StationRow(
        opis_id=opis_id,
        name=name,
        address="I-44, EXIT 283",
        city=city,
        state=state,
        rack_id=rack_id,
        price=Decimal(price),
    )


# --- dedupe_rows: pure function, no DB -------------------------------------


def test_dedupe_keeps_cheapest_price_for_duplicate_opis_id():
    rows = [
        _row(opis_id=20, price="3.899", name="PILOT TRAVEL CENTER #1243"),
        _row(opis_id=20, price="3.799", name="PILOT #1243"),
    ]

    result = dedupe_rows(rows)

    assert len(result) == 1
    assert result[0].price == Decimal("3.799")
    assert result[0].name == "PILOT #1243"


def test_dedupe_keeps_first_seen_on_exact_price_tie():
    rows = [
        _row(opis_id=20, price="3.899", name="FIRST"),
        _row(opis_id=20, price="3.899", name="SECOND"),
    ]

    result = dedupe_rows(rows)

    assert len(result) == 1
    assert result[0].name == "FIRST"


def test_dedupe_preserves_first_seen_order_and_keeps_distinct_ids():
    rows = [_row(opis_id=9), _row(opis_id=7), _row(opis_id=20)]

    result = dedupe_rows(rows)

    assert [r.opis_id for r in result] == [9, 7, 20]


def test_dedupe_empty_input():
    assert dedupe_rows([]) == []


# --- upsert_stations: idempotent upsert against the DB ----------------------


@pytest.mark.django_db
def test_upsert_creates_new_stations_with_initial_price_history():
    rows = [_row(opis_id=1, price="3.500"), _row(opis_id=2, price="4.000", city="Tomah", state="WI")]

    stats = upsert_stations(rows)

    assert stats.created == 2
    assert stats.price_updated == 0
    assert stats.unchanged == 0
    assert FuelStation.objects.count() == 2
    assert PriceHistory.objects.count() == 2

    station = FuelStation.objects.get(opis_id=1)
    assert station.current_price == Decimal("3.500")
    assert station.geocode_source in {"city", "state_centroid"}
    assert PriceHistory.objects.get(station=station).price == Decimal("3.500")


@pytest.mark.django_db
def test_upsert_is_idempotent_when_rerun_with_unchanged_data():
    rows = [_row(opis_id=1, price="3.500")]

    upsert_stations(rows)
    second_stats = upsert_stations(rows)

    assert second_stats.created == 0
    assert second_stats.price_updated == 0
    assert second_stats.unchanged == 1
    assert FuelStation.objects.count() == 1
    # No new PriceHistory row: only the initial one from the first run.
    assert PriceHistory.objects.count() == 1


@pytest.mark.django_db
def test_upsert_updates_price_and_appends_history_on_change():
    upsert_stations([_row(opis_id=1, price="3.500")])

    stats = upsert_stations([_row(opis_id=1, price="3.750")])

    assert stats.created == 0
    assert stats.price_updated == 1
    station = FuelStation.objects.get(opis_id=1)
    assert station.current_price == Decimal("3.750")
    assert PriceHistory.objects.filter(station=station).count() == 2
    latest = PriceHistory.objects.filter(station=station).order_by("-effective_at").first()
    assert latest.price == Decimal("3.750")


@pytest.mark.django_db
def test_upsert_updates_non_price_fields_without_new_history_row():
    upsert_stations([_row(opis_id=1, price="3.500", name="OLD NAME")])

    stats = upsert_stations([_row(opis_id=1, price="3.500", name="NEW NAME")])

    assert stats.price_updated == 0
    assert stats.unchanged == 1
    station = FuelStation.objects.get(opis_id=1)
    assert station.name == "NEW NAME"
    assert PriceHistory.objects.filter(station=station).count() == 1


@pytest.mark.django_db
def test_upsert_dedupe_then_upsert_end_to_end_matches_single_row():
    deduped = dedupe_rows(
        [
            _row(opis_id=20, price="3.899", name="PILOT TRAVEL CENTER #1243"),
            _row(opis_id=20, price="3.799", name="PILOT #1243"),
        ]
    )

    stats = upsert_stations(deduped)

    assert stats.created == 1
    station = FuelStation.objects.get(opis_id=20)
    assert station.current_price == Decimal("3.799")
    assert station.name == "PILOT #1243"
