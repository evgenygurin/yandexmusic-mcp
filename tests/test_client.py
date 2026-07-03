"""YandexClient tests — mocked httpx transport."""

from __future__ import annotations

import hashlib

import pytest

from tests.conftest import FakeYandexAPI
from yandexmusic_mcp.client import (
    APIError,
    AuthFailedError,
    RateLimitedError,
    YandexClient,
)
from yandexmusic_mcp.rate_limiter import TokenBucketRateLimiter


async def test_search_tracks(fake_api: FakeYandexAPI, client: YandexClient) -> None:
    fake_api.routes["GET /search"] = {
        "tracks": {"results": [{"id": "1", "title": "A"}], "total": 1}
    }
    result = await client.search(query="hello", type="tracks", limit=10)
    assert result["tracks"]["total"] == 1
    assert result["tracks"]["results"][0]["id"] == "1"
    # plural alias is translated to YM's singular entity name
    assert fake_api.requests[0].url.params["type"] == "track"


async def test_401_raises_auth_failed(fake_api: FakeYandexAPI, client: YandexClient) -> None:
    fake_api.status_overrides["GET /tracks"] = 401
    with pytest.raises(AuthFailedError, match="YANDEX_MUSIC_TOKEN"):
        await client.get_tracks(["1"])


async def test_429_raises_rate_limited(fake_api: FakeYandexAPI, client: YandexClient) -> None:
    fake_api.status_overrides["GET /tracks"] = 429
    with pytest.raises(RateLimitedError):
        await client.get_tracks(["1"])


async def test_500_raises_api_error(fake_api: FakeYandexAPI, client: YandexClient) -> None:
    fake_api.status_overrides["GET /tracks"] = 500
    with pytest.raises(APIError):
        await client.get_tracks(["1"])


async def test_get_tracks_stringifies_ids(fake_api: FakeYandexAPI, client: YandexClient) -> None:
    fake_api.routes["GET /tracks"] = [{"id": "1"}, {"id": "2"}]
    tracks = await client.get_tracks([1, "2"])  # type: ignore[list-item]
    assert [t["id"] for t in tracks] == ["1", "2"]
    assert fake_api.requests[0].url.params["trackIds"] == "1,2"


async def test_get_playlist_composite_id(fake_api: FakeYandexAPI, client: YandexClient) -> None:
    fake_api.routes["GET /users/42/playlists/3"] = {
        "kind": 3,
        "title": "P",
        "revision": 7,
        "trackCount": 0,
    }
    pl = await client.get_playlist("42:3")
    assert pl["kind"] == 3
    assert pl["revision"] == 7


async def test_get_playlist_bare_kind_uses_own_uid(
    fake_api: FakeYandexAPI, client: YandexClient
) -> None:
    fake_api.routes["GET /users/42/playlists/3"] = {"kind": 3, "revision": 1}
    pl = await client.get_playlist(3)
    assert pl["kind"] == 3


async def test_modify_playlist_diff(fake_api: FakeYandexAPI, client: YandexClient) -> None:
    fake_api.routes["POST /users/42/playlists/3/change-relative"] = {
        "revision": 8,
        "trackCount": 1,
    }
    diff = [{"op": "insert", "at": 0, "tracks": [{"id": "1", "albumId": "2"}]}]
    result = await client.modify_playlist("42:3", diff=diff, revision=7)
    assert result["revision"] == 8


async def test_uid_is_resolved_from_account_status(fake_api: FakeYandexAPI) -> None:
    """With no user_id configured, /account/status supplies the uid once."""
    fake_api.routes["GET /account/status"] = {"account": {"uid": 777, "login": "dj"}}
    fake_api.routes["GET /users/777/playlists/list"] = [{"kind": 3, "title": "P"}]
    client = YandexClient(
        token="t",
        rate_limiter=TokenBucketRateLimiter(delay_s=0.0),
        transport=fake_api.transport(),
    )
    playlists = await client.list_playlists()
    assert playlists[0]["kind"] == 3
    await client.list_playlists()  # uid is cached — no second status call
    status_calls = [r for r in fake_api.requests if r.url.path == "/account/status"]
    assert len(status_calls) == 1


async def test_uid_resolution_failure_is_actionable(fake_api: FakeYandexAPI) -> None:
    fake_api.routes["GET /account/status"] = {"account": {}}
    client = YandexClient(
        token="t",
        rate_limiter=TokenBucketRateLimiter(delay_s=0.0),
        transport=fake_api.transport(),
    )
    with pytest.raises(AuthFailedError, match="YANDEX_MUSIC_USER_ID"):
        await client.list_playlists()


def test_build_signed_mp3_url() -> None:
    xml = (
        "<download-info><host>h.example</host><path>/a/b.mp3</path>"
        "<s>SALT</s><ts>123</ts></download-info>"
    )
    url = YandexClient._build_signed_mp3_url(xml)
    expected_sign = hashlib.md5(b"XGRlBW9FXlekgbPrRHuSiAa/b.mp3SALT").hexdigest()
    assert url == f"https://h.example/get-mp3/{expected_sign}/123/a/b.mp3"


def test_build_signed_mp3_url_rejects_bad_manifest() -> None:
    with pytest.raises(APIError, match="bad download manifest"):
        YandexClient._build_signed_mp3_url("<download-info><host>h</host></download-info>")


async def test_api_get_allows_relative_paths(fake_api: FakeYandexAPI, client: YandexClient) -> None:
    fake_api.routes["GET /landing3/new-releases"] = {"ok": True}
    assert await client.api_get("/landing3/new-releases") == {"ok": True}


@pytest.mark.parametrize(
    "path",
    [
        "https://attacker.example/collect",
        "http://attacker.example/collect",
        "//attacker.example/collect",
        "https://api.music.yandex.net:8443/tracks",
    ],
)
async def test_api_get_rejects_offsite_urls(client: YandexClient, path: str) -> None:
    """The shared client carries the OAuth header — an absolute URL would
    exfiltrate the token to an arbitrary host through a read-only tool."""
    with pytest.raises(APIError, match="must be relative"):
        await client.api_get(path)


async def test_close_is_idempotent(client: YandexClient) -> None:
    await client.close()
    await client.close()  # must not raise
