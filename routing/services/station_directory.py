"""Query-building for the Fuel station directory: search, filter, sort.

Split out of the view so the filtering logic is testable against a plain
QuerySet without going through request/response plumbing.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db.models import Q, QuerySet

SORT_OPTIONS = {
    "price_asc": "current_price",
    "price_desc": "-current_price",
    "name": "name",
    "state": "state",
}
DEFAULT_SORT = "price_asc"


def _parse_price(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def filter_stations(
    queryset: QuerySet,
    *,
    query: str = "",
    state: str = "",
    min_price: str | None = None,
    max_price: str | None = None,
    sort: str = DEFAULT_SORT,
) -> QuerySet:
    """Apply search text, state, and price-range filters, then sort.

    Invalid price inputs (non-numeric) are silently ignored rather than
    raising, since this reads directly from unvalidated GET params.
    """
    query = query.strip()
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(city__icontains=query))

    state = state.strip().upper()
    if state:
        queryset = queryset.filter(state=state)

    min_price_decimal = _parse_price(min_price)
    if min_price_decimal is not None:
        queryset = queryset.filter(current_price__gte=min_price_decimal)

    max_price_decimal = _parse_price(max_price)
    if max_price_decimal is not None:
        queryset = queryset.filter(current_price__lte=max_price_decimal)

    order_by = SORT_OPTIONS.get(sort, SORT_OPTIONS[DEFAULT_SORT])
    return queryset.order_by(order_by, "id")
