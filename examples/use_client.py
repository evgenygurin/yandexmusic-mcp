"""Use the packaged async client directly (without the MCP layer).

Run: YANDEX_MUSIC_TOKEN=... uv run python examples/use_client.py
"""

import asyncio

from yandexmusic_mcp.client import YandexClient
from yandexmusic_mcp.config import Settings


async def main() -> None:
    settings = Settings.from_env()
    client = YandexClient(
        token=settings.token,
        user_id=str(settings.user_id),
        base_url=settings.base_url,
        timeout_s=settings.timeout,
    )
    try:
        status = await client.account_status()
        account = status.get("account", {})
        print(f"Logged in as {account.get('login')} (uid {account.get('uid')})")

        data = await client.search(query="Kino Gruppa krovi", type="track", limit=3)
        for track in data.get("tracks", {}).get("results", []):
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            print(f"- {artists} — {track['title']} (id {track['id']})")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
