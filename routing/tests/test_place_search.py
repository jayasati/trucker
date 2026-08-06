from routing.services.place_search import search_places


def test_query_shorter_than_minimum_returns_empty():
    assert search_places("n") == []
    assert search_places("") == []


def test_prefix_match_surfaces_new_york_for_ne():
    labels = [s.label for s in search_places("ne", limit=15)]
    assert "New York, NY" in labels


def test_major_city_ranked_above_minor_prefix_match():
    results = [s.label for s in search_places("ne", limit=30)]
    # "Nebo" (a small town) also matches the "ne" prefix; the major city
    # boost should place New York ahead of it regardless of alphabetical order.
    assert "New York, NY" in results
    if "Nebo, KY" in results:
        assert results.index("New York, NY") < results.index("Nebo, KY")


def test_case_insensitive():
    assert search_places("CHI", limit=10) == search_places("chi", limit=10)


def test_prefix_only_not_substring():
    # "ork" should not match "New York" -- this is a prefix search, not substring.
    labels = [s.label for s in search_places("ork", limit=10)]
    assert "New York, NY" not in labels


def test_known_major_city_lookup():
    labels = [s.label for s in search_places("chic", limit=5)]
    assert "Chicago, IL" in labels


def test_limit_is_respected():
    results = search_places("sa", limit=3)
    assert len(results) <= 3


def test_results_have_valid_coordinates():
    results = search_places("new york", limit=5)
    assert results
    for r in results:
        assert -90 <= r.latitude <= 90
        assert -180 <= r.longitude <= 180
