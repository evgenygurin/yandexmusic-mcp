"""Track filter tests (genre allow/block + duration + title patterns)."""

from yandexmusic_mcp.filters import TrackFilter


def test_no_filters_passes_everything() -> None:
    f = TrackFilter()
    track = {"id": "1", "title": "A", "genre": "techno"}
    assert f.matches(track) is True
    assert f.is_noop() is True


def test_genre_whitelist_passes() -> None:
    f = TrackFilter(genre_allow=frozenset({"techno", "house"}))
    assert f.matches({"id": "1", "genre": "techno"}) is True
    assert f.matches({"id": "2", "genre": "pop"}) is False
    assert f.is_noop() is False


def test_genre_blacklist_rejects() -> None:
    f = TrackFilter(genre_block=frozenset({"ambient"}))
    assert f.matches({"id": "1", "genre": "techno"}) is True
    assert f.matches({"id": "2", "genre": "ambient"}) is False


def test_duration_bounds() -> None:
    f = TrackFilter(min_duration_ms=120_000, max_duration_ms=600_000)
    assert f.matches({"id": "1", "duration_ms": 300_000}) is True
    assert f.matches({"id": "2", "duration_ms": 60_000}) is False
    assert f.matches({"id": "3", "duration_ms": 700_000}) is False


def test_title_exclude_patterns() -> None:
    f = TrackFilter(
        exclude_title_patterns=(r"(?i)\bremix\b", r"(?i)radio edit"),
    )
    assert f.matches({"id": "1", "title": "Untitled"}) is True
    assert f.matches({"id": "2", "title": "Untitled (Remix)"}) is False
    assert f.matches({"id": "3", "title": "Radio Edit"}) is False


def test_missing_fields_are_neutral() -> None:
    f = TrackFilter(min_duration_ms=120_000)
    assert f.matches({"id": "1"}) is True


def test_from_params_and_apply() -> None:
    f = TrackFilter.from_params(genre_block=["pop"], exclude_patterns=[r"(?i)karaoke"])
    tracks = [
        {"id": "1", "genre": "techno", "title": "Keep"},
        {"id": "2", "genre": "pop", "title": "Drop"},
        {"id": "3", "genre": "techno", "title": "Karaoke Version"},
    ]
    assert [t["id"] for t in f.apply(tracks)] == ["1"]
