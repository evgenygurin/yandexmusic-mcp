"""Map raw Yandex Music API dicts to the slim typed models.

The YM API returns large payloads (cover URIs, availability matrices,
normalization data …); these formatters keep only what a music/DJ
assistant needs and normalize ids to strings (YM mixes int and str ids
across endpoints).
"""

from __future__ import annotations

from typing import Any

from . import models as m

WEB_BASE = "https://music.yandex.ru"


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def slim_artist_ref(raw: dict[str, Any]) -> m.ArtistRef:
    return m.ArtistRef(id=_opt_str(raw.get("id")), name=raw.get("name"))


def slim_album_ref(raw: dict[str, Any]) -> m.AlbumRef:
    return m.AlbumRef(
        id=_opt_str(raw.get("id")),
        title=raw.get("title"),
        year=_opt_int(raw.get("year")),
        genre=raw.get("genre"),
    )


def slim_track(raw: dict[str, Any]) -> m.Track:
    albums = [slim_album_ref(a) for a in raw.get("albums") or []]
    genre = next((a.genre for a in albums if a.genre), None)
    track_id = _opt_str(raw.get("id"))
    url = None
    if track_id and albums and albums[0].id:
        url = f"{WEB_BASE}/album/{albums[0].id}/track/{track_id}"
    return m.Track(
        id=track_id,
        title=raw.get("title"),
        artists=[slim_artist_ref(a) for a in raw.get("artists") or []],
        albums=albums,
        duration_ms=_opt_int(raw.get("durationMs")),
        genre=genre,
        available=raw.get("available"),
        explicit=raw.get("contentWarning") == "explicit" or None,
        url=url,
    )


def slim_album(raw: dict[str, Any]) -> m.Album:
    # /albums/{id}/with-tracks nests tracks in `volumes` (one list per disc).
    tracks = [slim_track(t) for volume in raw.get("volumes") or [] for t in volume]
    album_id = _opt_str(raw.get("id"))
    return m.Album(
        id=album_id,
        title=raw.get("title"),
        artists=[slim_artist_ref(a) for a in raw.get("artists") or []],
        genre=raw.get("genre"),
        year=_opt_int(raw.get("year")),
        track_count=_opt_int(raw.get("trackCount")),
        tracks=tracks,
        url=f"{WEB_BASE}/album/{album_id}" if album_id else None,
    )


def slim_artist(raw: dict[str, Any]) -> m.Artist:
    artist_id = _opt_str(raw.get("id"))
    return m.Artist(
        id=artist_id,
        name=raw.get("name"),
        genres=list(raw.get("genres") or []),
        url=f"{WEB_BASE}/artist/{artist_id}" if artist_id else None,
    )


def slim_playlist(raw: dict[str, Any]) -> m.Playlist:
    owner = raw.get("owner") or {}
    owner_uid = _opt_str(owner.get("uid") if isinstance(owner, dict) else None)
    if owner_uid is None:
        owner_uid = _opt_str(raw.get("uid"))
    kind = _opt_int(raw.get("kind"))
    playlist_id = f"{owner_uid}:{kind}" if owner_uid is not None and kind is not None else None

    # Playlist tracks arrive as wrappers: {"id": …, "track": {full track}}.
    # The `track` body is present on /users/{uid}/playlists/{kind} but absent
    # in list views — keep only the resolvable ones.
    tracks = [
        slim_track(entry["track"])
        for entry in raw.get("tracks") or []
        if isinstance(entry, dict) and isinstance(entry.get("track"), dict)
    ]

    login = owner.get("login") if isinstance(owner, dict) else None
    url = f"{WEB_BASE}/users/{login}/playlists/{kind}" if login and kind is not None else None
    return m.Playlist(
        playlist_id=playlist_id,
        kind=kind,
        owner_uid=owner_uid,
        title=raw.get("title"),
        description=raw.get("description") or None,
        revision=_opt_int(raw.get("revision")),
        track_count=_opt_int(raw.get("trackCount")),
        visibility=raw.get("visibility"),
        duration_ms=_opt_int(raw.get("durationMs")),
        tracks=tracks,
        url=url,
    )


def slim_download_option(raw: dict[str, Any]) -> m.DownloadOption:
    return m.DownloadOption(
        codec=raw.get("codec"),
        bitrate_kbps=_opt_int(raw.get("bitrateInKbps")),
        gain=raw.get("gain"),
        preview=raw.get("preview"),
    )


def search_section(data: dict[str, Any], key: str) -> tuple[int | None, list[dict[str, Any]]]:
    """Pull (total, results) for one entity section of a /search response."""
    section = data.get(key) or {}
    return _opt_int(section.get("total")), list(section.get("results") or [])
