from django.apps import AppConfig
from django.db.utils import OperationalError, ProgrammingError


class RoutingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "routing"

    def ready(self) -> None:
        from routing.spatial_index import SpatialIndex

        try:
            SpatialIndex.load()
        except (OperationalError, ProgrammingError):
            # Table doesn't exist yet, e.g. before the first `migrate`. The
            # index stays empty until something explicitly reloads it.
            pass
