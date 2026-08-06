from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from routing.services.fuel_data import RowParseError, dedupe_rows, parse_csv_rows, upsert_stations
from routing.spatial_index import SpatialIndex


class Command(BaseCommand):
    help = "Load/refresh FuelStation rows from the fuel-prices CSV feed (idempotent upsert)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            dest="file_path",
            default=settings.FUEL_DATA_CSV_PATH,
            help="Path to the fuel-prices CSV (default: settings.FUEL_DATA_CSV_PATH).",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]

        try:
            rows = parse_csv_rows(file_path)
        except FileNotFoundError as exc:
            raise CommandError(f"CSV file not found: {file_path}") from exc
        except RowParseError as exc:
            raise CommandError(str(exc)) from exc

        deduped = dedupe_rows(rows)
        duplicates_dropped = len(rows) - len(deduped)

        with transaction.atomic():
            stats = upsert_stations(deduped)

        try:
            SpatialIndex.load()
        except Exception:  # noqa: BLE001 - refresh is best-effort, DB write already committed
            pass

        self.stdout.write(self.style.SUCCESS("Fuel data load complete."))
        self.stdout.write(f"  Input rows (raw CSV):     {len(rows)}")
        self.stdout.write(f"  Duplicate rows dropped:   {duplicates_dropped}")
        self.stdout.write(f"  Unique stations (by ID):  {stats.unique_stations}")
        self.stdout.write(f"  Created:                  {stats.created}")
        self.stdout.write(f"  Price updated:            {stats.price_updated}")
        self.stdout.write(f"  Unchanged:                {stats.unchanged}")
        self.stdout.write(f"  Geocoded at city level:   {stats.geocoded_city}")
        self.stdout.write(f"  Geocoded at state centroid fallback: {stats.geocoded_state_centroid}")
