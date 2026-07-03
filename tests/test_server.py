"""End-to-end tests of the MCP tools via an in-memory FastMCP client."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from yandexmusic_mcp import server

RAW_TRACK = {
    "id": 100,
    "title": "Gruppa krovi",
    "durationMs": 285_000,
    "available": True,
    "artists": [{"id": 7, "name": "Kino"}],
    "albums": [{"id": 55, "title": "Gruppa krovi", "year": 1988, "genre": "rusrock"}],
}

RAW_TRACK_SHORT = {
    "id": 101,
    "title": "Intro (Radio Edit)",
    "durationMs": 45_000,
    "available": True,
    "artists": [{"id": 8, "name": "Someone"}],
    "albums": [{"id": 56, "title": "X", "genre": "pop"}],
}

RAW_PLAYLIST = {
    "kind": 3,
    "owner": {"uid": 42, "login": "dj"},
    "title": "Peak Time",
    "revision": 7,
    "trackCount": 1,
    "visibility": "private",
    "tracks": [{"id": 100, "track": RAW_TRACK}],
}


class FakeYandexClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    async def search(self, *, query: str, type: str, limit: int, page: int) -> dict[str, Any]:
        self._record("search", query=query, type=type, limit=limit, page=page)
        section = {
            "track": ("tracks", [RAW_TRACK, RAW_TRACK_SHORT]),
            "album": ("albums", [{"id": 55, "title": "Gruppa krovi", "genre": "rusrock"}]),
            "artist": ("artists", [{"id": 7, "name": "Kino", "genres": ["rusrock"]}]),
            "playlist": ("playlists", [RAW_PLAYLIST]),
        }[type]
        return {section[0]: {"total": len(section[1]), "results": section[1]}}

    async def get_tracks(self, track_ids: list[str]) -> list[dict[str, Any]]:
        self._record("get_tracks", track_ids)
        return [RAW_TRACK for _ in track_ids]

    async def get_similar(self, track_id: str) -> list[dict[str, Any]]:
        self._record("get_similar", track_id)
        return [RAW_TRACK_SHORT]

    async def get_album(self, album_id: str, *, with_tracks: bool = False) -> dict[str, Any]:
        self._record("get_album", album_id, with_tracks=with_tracks)
        album: dict[str, Any] = {
            "id": 55,
            "title": "Gruppa krovi",
            "genre": "rusrock",
            "year": 1988,
            "trackCount": 11,
            "artists": [{"id": 7, "name": "Kino"}],
        }
        if with_tracks:
            album["volumes"] = [[RAW_TRACK]]
        return album

    async def get_artist_tracks(
        self, artist_id: str, *, offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        self._record("get_artist_tracks", artist_id, offset=offset, limit=limit)
        return {"tracks": [RAW_TRACK], "pager": {"total": 1}}

    async def get_download_info(self, track_id: str) -> list[dict[str, Any]]:
        self._record("get_download_info", track_id)
        return [{"codec": "mp3", "bitrateInKbps": 320, "gain": False, "preview": False}]

    async def download_track(self, track_id: str, dest: Path, *, on_progress=None) -> Path:
        self._record("download_track", track_id, dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"ID3-fake-mp3")
        if on_progress is not None:
            await on_progress(12, 12)
        return dest

    async def account_status(self) -> dict[str, Any]:
        self._record("account_status")
        return {"account": {"uid": 42, "login": "dj"}, "plus": {"hasPlus": True}}

    async def list_playlists(self) -> list[dict[str, Any]]:
        self._record("list_playlists")
        return [RAW_PLAYLIST]

    async def get_playlist(self, playlist_id: str | int) -> dict[str, Any]:
        self._record("get_playlist", playlist_id)
        return RAW_PLAYLIST

    async def create_playlist(self, *, title: str, visibility: str) -> dict[str, Any]:
        self._record("create_playlist", title=title, visibility=visibility)
        return {"kind": 9, "owner": {"uid": 42}, "title": title, "revision": 1, "trackCount": 0}

    async def rename_playlist(self, playlist_id: str | int, *, title: str) -> dict[str, Any]:
        self._record("rename_playlist", playlist_id, title=title)
        return {**RAW_PLAYLIST, "title": title}

    async def set_playlist_description(
        self, playlist_id: str | int, *, description: str
    ) -> dict[str, Any]:
        self._record("set_playlist_description", playlist_id, description=description)
        return {**RAW_PLAYLIST, "description": description}

    async def modify_playlist(
        self, playlist_id: str | int, *, diff: list[dict[str, Any]], revision: int
    ) -> dict[str, Any]:
        self._record("modify_playlist", playlist_id, diff=diff, revision=revision)
        return {**RAW_PLAYLIST, "revision": revision + 1}

    async def delete_playlist(self, playlist_id: str | int) -> dict[str, Any]:
        self._record("delete_playlist", playlist_id)
        return {"deleted": True}

    async def get_liked_ids(self) -> list[str]:
        self._record("get_liked_ids")
        return ["100", "101"]

    async def get_disliked_ids(self) -> list[str]:
        self._record("get_disliked_ids")
        return ["666"]

    async def add_likes(self, track_ids: list[str]) -> dict[str, Any]:
        self._record("add_likes", track_ids)
        return {"revision": 12}

    async def remove_likes(self, track_ids: list[str]) -> dict[str, Any]:
        self._record("remove_likes", track_ids)
        return {"revision": 13}

    async def api_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._record("api_get", path, params=params)
        return {"path": path}

    async def close(self) -> None:  # lifespan closes the client on shutdown
        pass


@pytest.fixture
def fake_client(monkeypatch) -> FakeYandexClient:
    fake = FakeYandexClient()
    monkeypatch.setattr(server, "_client", fake)
    return fake


async def test_tools_are_registered():
    async with Client(server.mcp) as client:
        tools = {tool.name for tool in await client.list_tools()}
    assert {
        "search_tracks",
        "search_albums",
        "search_artists",
        "search_playlists",
        "get_track",
        "get_tracks",
        "get_similar_tracks",
        "get_album",
        "get_artist_tracks",
        "get_download_info",
        "account_status",
        "my_playlists",
        "get_playlist",
        "liked_tracks",
        "disliked_tracks",
        "create_playlist",
        "rename_playlist",
        "set_playlist_description",
        "add_tracks_to_playlist",
        "remove_tracks_from_playlist",
        "delete_playlist",
        "like_tracks",
        "unlike_tracks",
        "download_track",
        "yandex_api_get",
    } <= tools


async def test_annotations():
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert tools["search_tracks"].annotations.readOnlyHint is True
    assert tools["delete_playlist"].annotations.destructiveHint is True
    assert tools["unlike_tracks"].annotations.destructiveHint is True
    assert tools["create_playlist"].annotations.readOnlyHint is False


async def test_resources_and_prompts_are_registered():
    async with Client(server.mcp) as client:
        resources = {str(r.uri) for r in await client.list_resources()}
        templates = {t.uriTemplate for t in await client.list_resource_templates()}
        prompts = {p.name for p in await client.list_prompts()}
    assert {
        "yandexmusic://account",
        "yandexmusic://playlists",
        "yandexmusic://likes",
    } <= resources
    assert {
        "yandexmusic://track/{track_id}",
        "yandexmusic://album/{album_id}",
        "yandexmusic://playlist/{owner_uid}/{kind}",
    } <= templates
    assert {"crate_dig", "analyze_playlist"} <= prompts


async def test_search_tracks_returns_slim_results(fake_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_tracks", {"query": "kino"})

    page = result.data
    assert page.total == 2
    track = page.results[0]
    assert track.id == "100"
    assert track.artists[0].name == "Kino"
    assert track.genre == "rusrock"
    assert track.duration_ms == 285_000
    assert track.url == "https://music.yandex.ru/album/55/track/100"
    # only declared model fields are present — noisy YM fields are gone
    assert "coverUri" not in result.structured_content["results"][0]


async def test_search_tracks_applies_filters(fake_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "search_tracks",
            {
                "query": "kino",
                "min_duration_ms": 120_000,
                "exclude_title_patterns": [r"(?i)radio edit"],
            },
        )
    ids = [t.id for t in result.data.results]
    assert ids == ["100"]  # the 45s "Radio Edit" track is filtered out


async def test_output_schema_is_published():
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    schema = tools["search_tracks"].outputSchema
    assert schema is not None
    assert "results" in schema.get("properties", {})


async def test_get_album_with_tracks(fake_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_album", {"album_id": "55", "with_tracks": True})
    album = result.data
    assert album.id == "55"
    assert album.track_count == 11
    assert album.tracks[0].title == "Gruppa krovi"


async def test_get_playlist_slims_track_wrappers(fake_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_playlist", {"playlist_id": "42:3"})
    playlist = result.data
    assert playlist.playlist_id == "42:3"
    assert playlist.revision == 7
    assert playlist.tracks[0].id == "100"
    assert playlist.url == "https://music.yandex.ru/users/dj/playlists/3"


async def test_add_tracks_auto_resolves_revision(fake_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "add_tracks_to_playlist", {"playlist_id": "42:3", "track_ids": ["100", "101"]}
        )

    assert result.data.revision == 8  # fake returns revision + 1
    # revision was fetched via get_playlist because the caller omitted it
    names = [c[0] for c in fake_client.calls]
    assert names == ["get_playlist", "modify_playlist"]
    _, _, kwargs = fake_client.calls[1]
    assert kwargs["revision"] == 7
    assert kwargs["diff"][0]["tracks"] == [{"id": "100"}, {"id": "101"}]


async def test_add_tracks_with_explicit_revision_skips_fetch(fake_client):
    async with Client(server.mcp) as client:
        await client.call_tool(
            "add_tracks_to_playlist",
            {"playlist_id": "42:3", "track_ids": ["100"], "revision": 5},
        )
    names = [c[0] for c in fake_client.calls]
    assert names == ["modify_playlist"]
    assert fake_client.calls[0][2]["revision"] == 5


async def test_remove_tracks_builds_delete_diff(fake_client):
    async with Client(server.mcp) as client:
        await client.call_tool(
            "remove_tracks_from_playlist",
            {"playlist_id": "42:3", "from_index": 0, "to_index": 2, "revision": 7},
        )
    _, _, kwargs = fake_client.calls[0]
    assert kwargs["diff"] == [{"op": "delete", "from": 0, "to": 2}]


async def test_delete_playlist_confirmed_via_elicitation(fake_client):
    async def accept(message, response_type, params, context):
        return ElicitResult(action="accept", content=None)

    async with Client(server.mcp, elicitation_handler=accept) as client:
        result = await client.call_tool("delete_playlist", {"playlist_id": "42:3"})

    assert result.data == {"deleted": True}
    assert ("delete_playlist", ("42:3",), {}) in fake_client.calls


async def test_delete_playlist_declined_via_elicitation(fake_client):
    async def decline(message, response_type, params, context):
        return ElicitResult(action="decline")

    async with Client(server.mcp, elicitation_handler=decline) as client:
        result = await client.call_tool("delete_playlist", {"playlist_id": "42:3"})

    assert result.data == {"cancelled": True, "playlist_id": "42:3"}
    assert not any(c[0] == "delete_playlist" for c in fake_client.calls)  # nothing deleted


async def test_likes_roundtrip(fake_client):
    async with Client(server.mcp) as client:
        liked = await client.call_tool("liked_tracks", {})
        added = await client.call_tool("like_tracks", {"track_ids": ["100"]})

    assert liked.data.count == 2
    assert liked.data.track_ids == ["100", "101"]
    assert added.data == {"revision": 12}
    assert ("add_likes", (["100"],), {}) in fake_client.calls


async def test_download_track_writes_file_and_reports_progress(fake_client, tmp_path, monkeypatch):
    monkeypatch.setenv("YANDEX_MUSIC_DOWNLOAD_DIR", str(tmp_path))
    seen: list[tuple[float, float | None]] = []

    async def on_progress(progress, total, message):
        seen.append((progress, total))

    async with Client(server.mcp, progress_handler=on_progress) as client:
        result = await client.call_tool("download_track", {"track_id": "100"})

    data = result.data
    assert data.track_id == "100"
    assert data.path == str(tmp_path / "100.mp3")
    assert data.size_bytes == 12
    assert Path(data.path).read_bytes() == b"ID3-fake-mp3"
    assert seen[-1] == (12, 12)


@pytest.mark.parametrize("filename", ["../escape.mp3", "/tmp/abs.mp3", "a/../../b.mp3"])
async def test_download_track_rejects_traversal_filenames(
    fake_client, tmp_path, monkeypatch, filename
):
    monkeypatch.setenv("YANDEX_MUSIC_DOWNLOAD_DIR", str(tmp_path / "dl"))
    async with Client(server.mcp) as client:
        with pytest.raises(Exception, match="download dir"):
            await client.call_tool("download_track", {"track_id": "100", "filename": filename})
    assert not any(c[0] == "download_track" for c in fake_client.calls)  # nothing written


async def test_get_artist_tracks_paginates_by_page(fake_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_artist_tracks", {"artist_id": "7", "page": 2, "limit": 10}
        )
    assert result.data.page == 2
    assert ("get_artist_tracks", ("7",), {"offset": 20, "limit": 10}) in fake_client.calls


async def test_resources_read_via_fake_client(fake_client):
    async with Client(server.mcp) as client:
        likes = await client.read_resource("yandexmusic://likes")
        track = await client.read_resource("yandexmusic://track/100")
        playlist = await client.read_resource("yandexmusic://playlist/42/3")

    assert json.loads(likes[0].text)["count"] == 2
    assert json.loads(track[0].text)["id"] == "100"
    assert json.loads(playlist[0].text)["playlist_id"] == "42:3"


async def test_crate_dig_prompt_renders():
    async with Client(server.mcp) as client:
        result = await client.get_prompt(
            "crate_dig", {"vibe": "melodic techno", "count": 15, "min_duration_ms": 300000}
        )
    text = result.messages[0].content.text
    assert "melodic techno" in text
    assert "15" in text
    assert "300000" in text


async def test_yandex_api_get_escape_hatch(fake_client):
    async with Client(server.mcp) as client:
        result = await client.call_tool("yandex_api_get", {"path": "/landing3/new-releases"})
    assert result.data == {"path": "/landing3/new-releases"}


async def test_read_only_mode_hides_and_blocks_write_tools(fake_client):
    server.set_read_only(True)
    try:
        async with Client(server.mcp) as client:
            names = {t.name for t in await client.list_tools()}
            assert "search_tracks" in names  # reads stay
            assert {
                "create_playlist",
                "add_tracks_to_playlist",
                "delete_playlist",
                "like_tracks",
                "download_track",
            } & names == set()
            with pytest.raises(Exception, match=r"create_playlist|not found|Unknown"):
                await client.call_tool("create_playlist", {"title": "nope"})
    finally:
        server.set_read_only(False)  # restore for other tests

    async with Client(server.mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert "create_playlist" in names  # re-enabled


async def test_limit_is_validated():
    async with Client(server.mcp) as client:
        with pytest.raises(Exception, match=r"limit|validation"):
            await client.call_tool("search_tracks", {"query": "x", "limit": 9999})


async def test_health_route():
    async with Client(server.mcp) as client:
        await client.ping()  # server is reachable
    # exercise the route handler directly (HTTP transport only in production)
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/health", "headers": []}
    response = await server.health(Request(scope))
    assert response.status_code == 200
    assert json.loads(bytes(response.body))["status"] == "ok"
