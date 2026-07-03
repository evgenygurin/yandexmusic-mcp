"""Typed output models for the Yandex Music MCP server.

Tools annotate their return type with these Pydantic models, so FastMCP
generates a JSON output schema and returns validated structured content —
clients get a stable, declared shape (only the useful fields, never the
YM API's dozens of raw cover/availability fields) instead of loose JSON.
"""

from __future__ import annotations

from pydantic import BaseModel


class ArtistRef(BaseModel):
    """A minimal id+name artist reference."""

    id: str | None = None
    name: str | None = None


class AlbumRef(BaseModel):
    """A minimal album reference as embedded in track payloads."""

    id: str | None = None
    title: str | None = None
    year: int | None = None
    genre: str | None = None


class Track(BaseModel):
    id: str | None = None
    title: str | None = None
    artists: list[ArtistRef] = []
    albums: list[AlbumRef] = []
    duration_ms: int | None = None
    genre: str | None = None
    available: bool | None = None
    explicit: bool | None = None
    url: str | None = None


class Album(BaseModel):
    id: str | None = None
    title: str | None = None
    artists: list[ArtistRef] = []
    genre: str | None = None
    year: int | None = None
    track_count: int | None = None
    tracks: list[Track] = []
    url: str | None = None


class Artist(BaseModel):
    id: str | None = None
    name: str | None = None
    genres: list[str] = []
    url: str | None = None


class Playlist(BaseModel):
    # Composite "owner:kind" — the id every playlist tool accepts.
    playlist_id: str | None = None
    kind: int | None = None
    owner_uid: str | None = None
    title: str | None = None
    description: str | None = None
    revision: int | None = None
    track_count: int | None = None
    visibility: str | None = None
    duration_ms: int | None = None
    tracks: list[Track] = []
    url: str | None = None


class TrackPage(BaseModel):
    total: int | None = None
    page: int = 0
    results: list[Track] = []


class AlbumPage(BaseModel):
    total: int | None = None
    page: int = 0
    results: list[Album] = []


class ArtistPage(BaseModel):
    total: int | None = None
    page: int = 0
    results: list[Artist] = []


class PlaylistPage(BaseModel):
    total: int | None = None
    page: int = 0
    results: list[Playlist] = []


class DownloadOption(BaseModel):
    codec: str | None = None
    bitrate_kbps: int | None = None
    gain: bool | None = None
    preview: bool | None = None


class DownloadedFile(BaseModel):
    track_id: str
    path: str
    size_bytes: int


class LikedTracks(BaseModel):
    count: int
    track_ids: list[str] = []
