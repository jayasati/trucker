"""Offline city-name autocomplete for the Start/Finish inputs. Zero network calls.

Reuses the same `zipcodes` package as geocoding.py, but for a different job:
this is an interactive prefix search over ~30k US city/state pairs, not an
exact-match lookup. Ranking is prefix match first, then a small hardcoded
boost for major metros -- otherwise alphabetical prefix order buries e.g.
"New York" behind dozens of small towns ("Nebo", "Needville", "Newkirk", ...)
that also start with "ne", since "New York" sorts near the very end of
"New "-prefixed names.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import zipcodes

MIN_QUERY_LENGTH = 2
DEFAULT_LIMIT = 8

# The ~130 largest US cities by population, used only to break ties in
# ranking (general knowledge, not sourced from any file/URL). Everything
# else still matches and sorts normally, just without this priority boost.
MAJOR_CITIES: set[tuple[str, str]] = {
    ("new york", "NY"), ("los angeles", "CA"), ("chicago", "IL"), ("houston", "TX"),
    ("phoenix", "AZ"), ("philadelphia", "PA"), ("san antonio", "TX"), ("san diego", "CA"),
    ("dallas", "TX"), ("san jose", "CA"), ("austin", "TX"), ("jacksonville", "FL"),
    ("fort worth", "TX"), ("columbus", "OH"), ("charlotte", "NC"), ("san francisco", "CA"),
    ("indianapolis", "IN"), ("seattle", "WA"), ("denver", "CO"), ("washington", "DC"),
    ("boston", "MA"), ("el paso", "TX"), ("nashville", "TN"), ("detroit", "MI"),
    ("oklahoma city", "OK"), ("portland", "OR"), ("las vegas", "NV"), ("memphis", "TN"),
    ("louisville", "KY"), ("baltimore", "MD"), ("milwaukee", "WI"), ("albuquerque", "NM"),
    ("tucson", "AZ"), ("fresno", "CA"), ("sacramento", "CA"), ("mesa", "AZ"),
    ("kansas city", "MO"), ("atlanta", "GA"), ("omaha", "NE"), ("colorado springs", "CO"),
    ("raleigh", "NC"), ("miami", "FL"), ("long beach", "CA"), ("virginia beach", "VA"),
    ("oakland", "CA"), ("minneapolis", "MN"), ("tulsa", "OK"), ("tampa", "FL"),
    ("arlington", "TX"), ("new orleans", "LA"), ("wichita", "KS"), ("cleveland", "OH"),
    ("bakersfield", "CA"), ("aurora", "CO"), ("anaheim", "CA"), ("honolulu", "HI"),
    ("santa ana", "CA"), ("riverside", "CA"), ("corpus christi", "TX"), ("lexington", "KY"),
    ("stockton", "CA"), ("henderson", "NV"), ("saint paul", "MN"), ("st. louis", "MO"),
    ("cincinnati", "OH"), ("pittsburgh", "PA"), ("greensboro", "NC"), ("anchorage", "AK"),
    ("plano", "TX"), ("lincoln", "NE"), ("orlando", "FL"), ("irvine", "CA"),
    ("newark", "NJ"), ("toledo", "OH"), ("durham", "NC"), ("chula vista", "CA"),
    ("fort wayne", "IN"), ("jersey city", "NJ"), ("st. petersburg", "FL"), ("laredo", "TX"),
    ("madison", "WI"), ("chandler", "AZ"), ("buffalo", "NY"), ("lubbock", "TX"),
    ("scottsdale", "AZ"), ("reno", "NV"), ("glendale", "AZ"), ("gilbert", "AZ"),
    ("winston-salem", "NC"), ("north las vegas", "NV"), ("norfolk", "VA"), ("chesapeake", "VA"),
    ("garland", "TX"), ("irving", "TX"), ("hialeah", "FL"), ("fremont", "CA"),
    ("boise", "ID"), ("richmond", "VA"), ("baton rouge", "LA"), ("spokane", "WA"),
    ("des moines", "IA"), ("tacoma", "WA"), ("san bernardino", "CA"), ("modesto", "CA"),
    ("fontana", "CA"), ("santa clarita", "CA"), ("birmingham", "AL"), ("rochester", "NY"),
    ("salt lake city", "UT"), ("grand rapids", "MI"), ("huntsville", "AL"), ("yonkers", "NY"),
    ("amarillo", "TX"), ("akron", "OH"), ("montgomery", "AL"), ("little rock", "AR"),
    ("columbus", "GA"), ("augusta", "GA"), ("shreveport", "LA"), ("mobile", "AL"),
    ("knoxville", "TN"), ("worcester", "MA"), ("providence", "RI"), ("chattanooga", "TN"),
    ("fort lauderdale", "FL"), ("cape coral", "FL"), ("sioux falls", "SD"), ("springfield", "MO"),
    ("eugene", "OR"), ("salem", "OR"), ("cary", "NC"), ("hollywood", "FL"),
    ("bridgeport", "CT"), ("hartford", "CT"), ("savannah", "GA"), ("rockford", "IL"),
    ("alexandria", "VA"), ("charleston", "SC"), ("killeen", "TX"), ("naperville", "IL"),
}


@dataclass(frozen=True)
class PlaceSuggestion:
    label: str
    latitude: float
    longitude: float


@lru_cache(maxsize=1)
def _build_place_index() -> list[tuple[str, str, PlaceSuggestion]]:
    """Return (city_lower, state, suggestion) tuples, one per unique city+state."""
    seen: set[tuple[str, str]] = set()
    index: list[tuple[str, str, PlaceSuggestion]] = []

    for record in zipcodes.list_all():
        lat, lng, state, city = record.get("lat"), record.get("long"), record.get("state"), record.get("city")
        if not lat or not lng or not state or not city:
            continue
        city = city.strip()
        key = (city.lower(), state)
        if key in seen:
            continue
        seen.add(key)
        index.append((key[0], state, PlaceSuggestion(f"{city}, {state}", float(lat), float(lng))))

    return index


def search_places(query: str, limit: int = DEFAULT_LIMIT) -> list[PlaceSuggestion]:
    """Prefix-search city names for autocomplete. Empty/short queries return no results."""
    query = query.strip().lower()
    if len(query) < MIN_QUERY_LENGTH:
        return []

    matches = [
        (city_lower, state, suggestion)
        for city_lower, state, suggestion in _build_place_index()
        if city_lower.startswith(query)
    ]
    matches.sort(
        key=lambda m: (
            0 if (m[0], m[1]) in MAJOR_CITIES else 1,
            len(m[2].label),
            m[2].label,
        )
    )
    return [suggestion for _, _, suggestion in matches[:limit]]
