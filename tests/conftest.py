"""Shared fixtures: an httpx.MockTransport-backed fake Yandex Music API."""

import json
from typing import Any

import httpx
import pytest

from yandexmusic_mcp.client import YandexClient
from yandexmusic_mcp.rate_limiter import TokenBucketRateLimiter


class FakeYandexAPI:
    """In-memory Yandex Music API backed by httpx.MockTransport.

    Routes are keyed by "METHOD /path"; values are the JSON body that is
    wrapped into the API's ``{"result": …}`` envelope.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, Any] = {}
        self.status_overrides: dict[str, int] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path}"
        status = self.status_overrides.get(key)
        if status is not None:
            return httpx.Response(status, json={"error": "forced"})
        if key not in self.routes:
            return httpx.Response(404, json={"error": f"no route {key}"})
        return httpx.Response(200, content=json.dumps({"result": self.routes[key]}))


@pytest.fixture
def fake_api() -> FakeYandexAPI:
    return FakeYandexAPI()


@pytest.fixture
def client(fake_api: FakeYandexAPI) -> YandexClient:
    return YandexClient(
        token="test-token",
        user_id="42",
        base_url="https://api.music.yandex.net",
        rate_limiter=TokenBucketRateLimiter(delay_s=0.0),
        transport=fake_api.transport(),
    )
