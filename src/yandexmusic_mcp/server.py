"""FastMCP v3 server exposing the Yandex Music API.

Authentication uses a Yandex Music OAuth token taken from the
``YANDEX_MUSIC_TOKEN`` environment variable. See README.md for setup.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import formatters as fmt
from . import models as m
from .client import YandexClient
from .config import Settings
from .filters import TrackFilter
from .middleware import TimingMiddleware
from .rate_limiter import TokenBucketRateLimiter

_client: YandexClient | None = None


def get_client() -> YandexClient:
    global _client
    if _client is None:
        settings = Settings.from_env()
        _client = YandexClient(
            token=settings.token,
            user_id=str(settings.user_id),
            base_url=settings.base_url,
            rate_limiter=TokenBucketRateLimiter(
                delay_s=settings.rate_limit_delay,
                base_backoff_s=settings.retry_backoff,
                max_retries=settings.retry_attempts,
            ),
            timeout_s=settings.timeout,
        )
    return _client


@asynccontextmanager
async def lifespan(_server: FastMCP[None]) -> AsyncIterator[None]:
    """Own the shared HTTP client's lifecycle: close it on server shutdown."""
    global _client
    try:
        yield
    finally:
        if _client is not None:
            await _client.close()
            _client = None


mcp: FastMCP[None] = FastMCP(
    "Yandex Music",
    instructions=(
        "Tools for the Yandex Music API: search the catalog (tracks, albums, "
        "artists, playlists), fetch track/album/artist details and similar "
        "tracks, manage the authenticated user's playlists and likes, and "
        "download owned tracks as MP3. Playlists are addressed by the "
        "composite id 'owner_uid:kind' (as returned by my_playlists). "
        "Reference data (account status, playlists, likes, individual "
        "tracks/albums/playlists) is also exposed as `yandexmusic://` "
        "resources."
    ),
    lifespan=lifespan,
)

mcp.add_middleware(TimingMiddleware())

# Shared annotation presets. Catalog reads hit an external API (openWorldHint)
# and never mutate state (readOnlyHint); repeated reads are idempotent.
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)

SearchPage = Annotated[int, Field(ge=0, description="Page number (0-based)")]
Limit = Annotated[int, Field(ge=1, le=100, description="Results per page")]
PlaylistId = Annotated[
    str,
    Field(description="Playlist id: 'owner_uid:kind' (from my_playlists) or a bare kind"),
]
TrackIds = Annotated[list[str], Field(min_length=1, description="Yandex Music track ids")]


# ---------------------------------------------------------------------------
# Catalog: search
# ---------------------------------------------------------------------------


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def search_tracks(
    query: Annotated[str, Field(description="Free-text search, e.g. 'Kino Gruppa krovi'")],
    limit: Limit = 20,
    page: SearchPage = 0,
    genre_allow: Annotated[
        list[str] | None, Field(description="Keep only these genres (post-filter)")
    ] = None,
    genre_block: Annotated[
        list[str] | None, Field(description="Drop these genres (post-filter)")
    ] = None,
    min_duration_ms: Annotated[int | None, Field(ge=0, description="Minimum duration")] = None,
    max_duration_ms: Annotated[int | None, Field(ge=0, description="Maximum duration")] = None,
    exclude_title_patterns: Annotated[
        list[str] | None,
        Field(description="Drop tracks whose title matches any of these regexes"),
    ] = None,
) -> m.TrackPage:
    """Search tracks by free text (title, artist …), with optional post-filters.

    The YM search endpoint has no structured genre/duration filters, so the
    filter arguments are applied client-side to the returned page — a
    filtered page may contain fewer than `limit` tracks.
    """
    data = await get_client().search(query=query, type="track", limit=limit, page=page)
    total, raw_tracks = fmt.search_section(data, "tracks")
    tracks = [fmt.slim_track(t) for t in raw_tracks]
    track_filter = TrackFilter.from_params(
        genre_allow=genre_allow,
        genre_block=genre_block,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        exclude_patterns=exclude_title_patterns,
    )
    if not track_filter.is_noop():
        tracks = [
            t
            for t in tracks
            if track_filter.matches(
                {"genre": t.genre, "duration_ms": t.duration_ms, "title": t.title}
            )
        ]
    return m.TrackPage(total=total, page=page, results=tracks)


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def search_albums(
    query: Annotated[str, Field(description="Album title / free-text search")],
    limit: Limit = 20,
    page: SearchPage = 0,
) -> m.AlbumPage:
    """Search albums by free text."""
    data = await get_client().search(query=query, type="album", limit=limit, page=page)
    total, raw = fmt.search_section(data, "albums")
    return m.AlbumPage(total=total, page=page, results=[fmt.slim_album(a) for a in raw])


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def search_artists(
    query: Annotated[str, Field(description="Artist name to search for")],
    limit: Limit = 20,
    page: SearchPage = 0,
) -> m.ArtistPage:
    """Search artists by name."""
    data = await get_client().search(query=query, type="artist", limit=limit, page=page)
    total, raw = fmt.search_section(data, "artists")
    return m.ArtistPage(total=total, page=page, results=[fmt.slim_artist(a) for a in raw])


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def search_playlists(
    query: Annotated[str, Field(description="Playlist title / free-text search")],
    limit: Limit = 20,
    page: SearchPage = 0,
) -> m.PlaylistPage:
    """Search public playlists by free text."""
    data = await get_client().search(query=query, type="playlist", limit=limit, page=page)
    total, raw = fmt.search_section(data, "playlists")
    return m.PlaylistPage(total=total, page=page, results=[fmt.slim_playlist(p) for p in raw])


# ---------------------------------------------------------------------------
# Catalog: tracks, albums, artists
# ---------------------------------------------------------------------------


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def get_track(track_id: str) -> m.Track:
    """Get full details of a single track by its Yandex Music id."""
    tracks = await get_client().get_tracks([track_id])
    if not tracks:
        raise ValueError(f"track {track_id} not found")
    return fmt.slim_track(tracks[0])


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def get_tracks(track_ids: TrackIds) -> list[m.Track]:
    """Get details for a batch of tracks in one call (preserves input order)."""
    raw = await get_client().get_tracks([str(t) for t in track_ids])
    return [fmt.slim_track(t) for t in raw]


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def get_similar_tracks(track_id: str) -> list[m.Track]:
    """List tracks Yandex Music considers similar to a seed track."""
    return [fmt.slim_track(t) for t in await get_client().get_similar(track_id)]


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def get_album(
    album_id: str,
    with_tracks: Annotated[bool, Field(description="Include the full track list")] = False,
) -> m.Album:
    """Get details of an album, optionally with its full track list."""
    return fmt.slim_album(await get_client().get_album(album_id, with_tracks=with_tracks))


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def get_artist_tracks(
    artist_id: str,
    page: SearchPage = 0,
    limit: Limit = 50,
) -> m.TrackPage:
    """List an artist's tracks (popularity order, paginated)."""
    # The endpoint paginates by page, not offset — expose `page` directly so
    # callers can't request an offset that silently rounds down to a page.
    data = await get_client().get_artist_tracks(artist_id, offset=page * limit, limit=limit)
    raw = list(data.get("tracks") or [])
    pager = data.get("pager") or {}
    total = pager.get("total")
    return m.TrackPage(
        total=int(total) if total is not None else None,
        page=page,
        results=[fmt.slim_track(t) for t in raw],
    )


@mcp.tool(tags={"audio"}, annotations=READ_ONLY)
async def get_download_info(track_id: str) -> list[m.DownloadOption]:
    """List the available download variants (codec + bitrate) for a track."""
    return [fmt.slim_download_option(o) for o in await get_client().get_download_info(track_id)]


# ---------------------------------------------------------------------------
# Account, playlists & likes (require the authenticated user)
# ---------------------------------------------------------------------------


@mcp.tool(tags={"account"}, annotations=READ_ONLY)
async def account_status() -> dict[str, Any]:
    """Get the authenticated account's profile (also a good auth check)."""
    return await get_client().account_status()


@mcp.tool(tags={"playlists"}, annotations=READ_ONLY)
async def my_playlists() -> list[m.Playlist]:
    """List the authenticated user's playlists."""
    return [fmt.slim_playlist(p) for p in await get_client().list_playlists()]


@mcp.tool(tags={"playlists"}, annotations=READ_ONLY)
async def get_playlist(playlist_id: PlaylistId) -> m.Playlist:
    """Get a playlist with its tracks and current revision."""
    return fmt.slim_playlist(await get_client().get_playlist(playlist_id))


@mcp.tool(tags={"likes"}, annotations=READ_ONLY)
async def liked_tracks() -> m.LikedTracks:
    """List the ids of the user's liked tracks (resolve with get_tracks)."""
    ids = await get_client().get_liked_ids()
    return m.LikedTracks(count=len(ids), track_ids=ids)


@mcp.tool(tags={"likes"}, annotations=READ_ONLY)
async def disliked_tracks() -> m.LikedTracks:
    """List the ids of the user's disliked tracks."""
    ids = await get_client().get_disliked_ids()
    return m.LikedTracks(count=len(ids), track_ids=ids)


@mcp.tool(tags={"playlists", "write"}, annotations=WRITE)
async def create_playlist(
    title: Annotated[str, Field(min_length=1)],
    visibility: Annotated[str, Field(description="'private' or 'public'")] = "private",
) -> m.Playlist:
    """Create a new playlist in the user's Yandex Music account."""
    return fmt.slim_playlist(await get_client().create_playlist(title=title, visibility=visibility))


@mcp.tool(tags={"playlists", "write"}, annotations=WRITE)
async def rename_playlist(
    playlist_id: PlaylistId, title: Annotated[str, Field(min_length=1)]
) -> m.Playlist:
    """Rename one of the user's playlists."""
    return fmt.slim_playlist(await get_client().rename_playlist(playlist_id, title=title))


@mcp.tool(tags={"playlists", "write"}, annotations=WRITE)
async def set_playlist_description(playlist_id: PlaylistId, description: str) -> m.Playlist:
    """Set the description of one of the user's playlists."""
    return fmt.slim_playlist(
        await get_client().set_playlist_description(playlist_id, description=description)
    )


async def _resolve_revision(playlist_id: str, revision: int | None) -> int:
    """Return the given revision, or fetch the current one from YM.

    YM's change-relative endpoint requires the current revision for
    optimistic concurrency. Callers rarely carry it; auto-fetching hides
    that quirk at the tool boundary.
    """
    if revision is not None:
        return revision
    current = await get_client().get_playlist(playlist_id)
    return int(current.get("revision", 1))


@mcp.tool(tags={"playlists", "write"}, annotations=WRITE)
async def add_tracks_to_playlist(
    playlist_id: PlaylistId,
    track_ids: TrackIds,
    at: Annotated[int, Field(ge=0, description="Insert position (0 = top)")] = 0,
    revision: Annotated[
        int | None,
        Field(description="Playlist revision for optimistic concurrency; auto-fetched if omitted"),
    ] = None,
    ctx: Context | None = None,
) -> m.Playlist:
    """Add tracks to one of the user's playlists."""
    resolved = await _resolve_revision(playlist_id, revision)
    diff = [
        {
            "op": "insert",
            "at": at,
            "tracks": [{"id": str(t)} for t in track_ids],
        }
    ]
    result = await get_client().modify_playlist(playlist_id, diff=diff, revision=resolved)
    if ctx is not None:
        await ctx.info(f"Added {len(track_ids)} track(s) to playlist {playlist_id}")
    return fmt.slim_playlist(result)


@mcp.tool(tags={"playlists", "write"}, annotations=DESTRUCTIVE)
async def remove_tracks_from_playlist(
    playlist_id: PlaylistId,
    from_index: Annotated[int, Field(ge=0, description="First position to remove (0-based)")],
    to_index: Annotated[int, Field(ge=1, description="Position after the last one to remove")],
    revision: Annotated[
        int | None,
        Field(description="Playlist revision for optimistic concurrency; auto-fetched if omitted"),
    ] = None,
) -> m.Playlist:
    """Remove the tracks at positions [from_index, to_index) from a playlist."""
    resolved = await _resolve_revision(playlist_id, revision)
    diff = [{"op": "delete", "from": from_index, "to": to_index}]
    result = await get_client().modify_playlist(playlist_id, diff=diff, revision=resolved)
    return fmt.slim_playlist(result)


@mcp.tool(tags={"playlists", "write"}, annotations=DESTRUCTIVE)
async def delete_playlist(playlist_id: PlaylistId, ctx: Context | None = None) -> dict[str, Any]:
    """Permanently delete one of the user's playlists.

    If the client supports elicitation, asks for confirmation first, since
    the deletion cannot be undone.
    """
    if ctx is not None:
        try:
            answer = await ctx.elicit(
                f"Permanently delete Yandex Music playlist {playlist_id}? This cannot be undone.",
                response_type=None,
            )
        except Exception:
            answer = None  # client doesn't support elicitation — annotation already warns
        if isinstance(answer, DeclinedElicitation | CancelledElicitation):
            return {"cancelled": True, "playlist_id": playlist_id}
    result = await get_client().delete_playlist(playlist_id)
    return {"deleted": True, "playlist_id": playlist_id, "result": result}


@mcp.tool(tags={"likes", "write"}, annotations=WRITE)
async def like_tracks(track_ids: TrackIds) -> dict[str, Any]:
    """Add tracks to the user's likes."""
    return await get_client().add_likes([str(t) for t in track_ids])


@mcp.tool(tags={"likes", "write"}, annotations=DESTRUCTIVE)
async def unlike_tracks(track_ids: TrackIds) -> dict[str, Any]:
    """Remove tracks from the user's likes."""
    return await get_client().remove_likes([str(t) for t in track_ids])


# ---------------------------------------------------------------------------
# Audio download
# ---------------------------------------------------------------------------


@mcp.tool(tags={"audio", "write"}, annotations=WRITE)
async def download_track(
    track_id: str,
    filename: Annotated[
        str | None, Field(description="Target filename; defaults to '<track_id>.mp3'")
    ] = None,
    ctx: Context | None = None,
) -> m.DownloadedFile:
    """Download a track as MP3 (best available bitrate) to the server's download dir.

    Requires a Yandex Music subscription on the authenticated account; the
    file is written to YANDEX_MUSIC_DOWNLOAD_DIR on the machine running
    this server. Streams progress when the client supports it.
    """
    settings = Settings.from_env()
    download_dir = settings.download_dir.resolve()
    dest = (download_dir / (filename or f"{track_id}.mp3")).resolve()
    if not dest.is_relative_to(download_dir):
        raise ValueError(
            f"filename must resolve inside the download dir ({download_dir}); got {filename!r}"
        )

    async def on_progress(received: int, total: int | None) -> None:
        if ctx is not None:
            await ctx.report_progress(progress=received, total=total)

    path = await get_client().download_track(track_id, dest, on_progress=on_progress)
    size = path.stat().st_size
    if ctx is not None:
        await ctx.info(f"Downloaded track {track_id} to {path} ({size} bytes)")
    return m.DownloadedFile(track_id=track_id, path=str(path), size_bytes=size)


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


@mcp.tool(tags={"catalog"}, annotations=READ_ONLY)
async def yandex_api_get(
    path: Annotated[
        str,
        Field(
            description=(
                "Any GET path of the Yandex Music API, e.g. '/tracks/123' or "
                "'/landing3/new-releases'. The 'result' envelope is unwrapped."
            )
        ),
    ],
    params: Annotated[dict[str, Any] | None, Field(description="Extra query parameters")] = None,
) -> dict[str, Any]:
    """Call any read-only (GET) Yandex Music API endpoint — raw response.

    Non-object results (lists like /genres, scalars) are wrapped as
    {"result": …} so the tool always returns structured content.
    """
    result = await get_client().api_get(path, params)
    return result if isinstance(result, dict) else {"result": result}


# ---------------------------------------------------------------------------
# Resources — read-only reference data, addressable by URI
# ---------------------------------------------------------------------------


@mcp.resource(
    "yandexmusic://account",
    name="Yandex Music account",
    description="The authenticated Yandex Music account status.",
    mime_type="application/json",
    tags={"account"},
)
async def account_resource() -> dict[str, Any]:
    return await get_client().account_status()


@mcp.resource(
    "yandexmusic://playlists",
    name="Yandex Music playlists",
    description="The authenticated user's playlists.",
    mime_type="application/json",
    tags={"playlists"},
)
async def playlists_resource() -> list[dict[str, Any]]:
    return [
        fmt.slim_playlist(p).model_dump(mode="json") for p in await get_client().list_playlists()
    ]


@mcp.resource(
    "yandexmusic://likes",
    name="Yandex Music liked tracks",
    description="The ids of the user's liked tracks.",
    mime_type="application/json",
    tags={"likes"},
)
async def likes_resource() -> dict[str, Any]:
    ids = await get_client().get_liked_ids()
    return m.LikedTracks(count=len(ids), track_ids=ids).model_dump(mode="json")


@mcp.resource(
    "yandexmusic://track/{track_id}",
    name="Yandex Music track",
    description="A single track by id, as slimmed JSON.",
    mime_type="application/json",
    tags={"catalog"},
)
async def track_resource(track_id: str) -> dict[str, Any]:
    tracks = await get_client().get_tracks([track_id])
    if not tracks:
        raise ValueError(f"track {track_id} not found")
    return fmt.slim_track(tracks[0]).model_dump(mode="json")


@mcp.resource(
    "yandexmusic://album/{album_id}",
    name="Yandex Music album",
    description="A single album by id (with tracks), as slimmed JSON.",
    mime_type="application/json",
    tags={"catalog"},
)
async def album_resource(album_id: str) -> dict[str, Any]:
    album = fmt.slim_album(await get_client().get_album(album_id, with_tracks=True))
    return album.model_dump(mode="json")


@mcp.resource(
    "yandexmusic://playlist/{owner_uid}/{kind}",
    name="Yandex Music playlist",
    description="A playlist by owner uid + kind, with its tracks.",
    mime_type="application/json",
    tags={"playlists"},
)
async def playlist_resource(owner_uid: str, kind: str) -> dict[str, Any]:
    playlist = fmt.slim_playlist(await get_client().get_playlist(f"{owner_uid}:{kind}"))
    return playlist.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Prompts — reusable, parameterized instructions
# ---------------------------------------------------------------------------


@mcp.prompt(tags={"catalog"})
def crate_dig(
    vibe: Annotated[str, Field(description="Genre or vibe, e.g. 'melodic techno'")],
    count: Annotated[int, Field(ge=1, le=100, description="How many tracks")] = 20,
    min_duration_ms: Annotated[int, Field(ge=0, description="Minimum duration")] = 0,
) -> str:
    """Ask the model to dig a crate: build a track shortlist from Yandex Music."""
    duration_hint = (
        f" at least {min_duration_ms} ms long (pass min_duration_ms={min_duration_ms})"
        if min_duration_ms
        else ""
    )
    return (
        f"Using the Yandex Music tools, find {count} {vibe} tracks{duration_hint}. "
        f"Start with search_tracks (use genre_allow/exclude_title_patterns to keep "
        f"results clean), then expand the best finds with get_similar_tracks and "
        f"get_artist_tracks. Present the results as a numbered list of "
        f"'Artist - Title — duration, genre' with the music.yandex.ru URL for each, "
        f"and offer to save them to a new playlist with create_playlist + "
        f"add_tracks_to_playlist."
    )


@mcp.prompt(tags={"playlists"})
def analyze_playlist(
    playlist_id: Annotated[
        str, Field(description="Playlist id 'owner_uid:kind' (see my_playlists)")
    ],
) -> str:
    """Ask the model to analyze the genre/tempo profile of a playlist."""
    return (
        f"Fetch Yandex Music playlist {playlist_id} with get_playlist, then analyze "
        f"it as a DJ set: summarize the genre distribution, the duration profile, "
        f"the dominant artists, and suggest a play order plus any tracks that feel "
        f"like outliers. Use get_similar_tracks on the strongest tracks to suggest "
        f"additions that fit the set."
    )


# ---------------------------------------------------------------------------
# Custom HTTP route — liveness probe for the HTTP transport
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Liveness probe: 200 when the server process is up (no YM call)."""
    return JSONResponse({"status": "ok", "service": "yandexmusic-mcp"})


# ---------------------------------------------------------------------------
# Component visibility — optional read-only mode
# ---------------------------------------------------------------------------


def set_read_only(enabled: bool) -> None:
    """Hide (or restore) the mutating tools via tag visibility.

    In read-only mode the `write`-tagged tools (playlists, likes, downloads)
    are removed from the server, so a client can browse the catalog and the
    library but never modify the account or write files.
    """
    if enabled:
        mcp.disable(tags={"write"}, components={"tool"})
    else:
        mcp.enable(tags={"write"}, components={"tool"})


def main() -> None:
    """Console entry point: run over stdio by default, HTTP if configured."""
    settings = Settings.from_env()
    set_read_only(settings.read_only)
    transport = os.environ.get("YANDEX_MUSIC_MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.run(
            transport="http",
            host=os.environ.get("YANDEX_MUSIC_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("YANDEX_MUSIC_MCP_PORT", "8000")),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
