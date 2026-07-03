# yandexmusic-mcp

MCP server for the Yandex Music API, built with [FastMCP v3](https://gofastmcp.com).
Authenticates with a Yandex Music OAuth token.

Search the Yandex Music catalog (tracks, albums, artists, playlists), get
recommendations, manage your playlists and likes, and download owned tracks from
Claude or any other MCP client.

Extracted from [dj-music-plugin](https://github.com/evgenygurin/dj-music-plugin)'s
Yandex Music provider into a standalone server, following the shape of
[beatport-mcp](https://github.com/evgenygurin/beatport-mcp).

## Tools

| Tool | Description |
| --- | --- |
| `search_tracks` | Free-text track search with optional post-filters (genre allow/block, duration bounds, title-regex excludes) |
| `search_albums` / `search_artists` / `search_playlists` | Search the other catalog entities |
| `get_track` / `get_tracks` | Track details by id (single / batch) |
| `get_similar_tracks` | Yandex Music's similar-tracks recommendations for a seed track |
| `get_album` | Album details, optionally with the full track list |
| `get_artist_tracks` | An artist's tracks, paginated |
| `account_status` | Authenticated account profile (auth check) |
| `my_playlists` / `get_playlist` | Your playlists and their tracks |
| `create_playlist` / `rename_playlist` / `set_playlist_description` | Playlist management |
| `add_tracks_to_playlist` / `remove_tracks_from_playlist` / `delete_playlist` | Playlist contents (revision auto-resolved) |
| `liked_tracks` / `disliked_tracks` / `like_tracks` / `unlike_tracks` | Likes management |
| `get_download_info` / `download_track` | Download variants + MP3 download at best bitrate (subscription required) |
| `yandex_api_get` | Escape hatch: any GET endpoint of the API, raw response |

Responses are typed: catalog tools return Pydantic models (`Track`, `Album`, `Artist`,
`Playlist`, paginated as `TrackPage` / `AlbumPage` / …), so FastMCP publishes a JSON
**output schema** per tool and returns validated **structured content** — clients get a
stable, declared shape with only the useful fields (id, title, artists, duration, genre,
music.yandex.ru URLs, …), never the API's dozens of raw cover/availability fields.
`account_status` and `yandex_api_get` return raw JSON.

Every tool carries MCP [annotations](https://modelcontextprotocol.io/) (`readOnlyHint`,
`destructiveHint`, …) and domain `tags` (`catalog` / `playlists` / `likes` / `account` /
`audio`) so clients can present the right safety UI and filter by capability.

Playlists are addressed by the composite id `owner_uid:kind` (as returned by
`my_playlists`); a bare `kind` also works for your own playlists. The playlist
`revision` required by Yandex's optimistic-concurrency API is fetched automatically
when omitted.

### Resources

Read-only reference data, addressable by URI (no tool call needed):

| URI | Content |
| --- | --- |
| `yandexmusic://account` | Authenticated account status |
| `yandexmusic://playlists` | Your playlists |
| `yandexmusic://likes` | Your liked track ids |
| `yandexmusic://track/{track_id}` | A single track |
| `yandexmusic://album/{album_id}` | An album with its tracks |
| `yandexmusic://playlist/{owner_uid}/{kind}` | A playlist with its tracks |

### Prompts

| Prompt | Purpose |
| --- | --- |
| `crate_dig` | Build a track shortlist from a vibe/genre, ready to save as a playlist |
| `analyze_playlist` | Analyze a playlist's genre/duration profile as a DJ set |

### Server capabilities

The server leans on the full FastMCP v3 feature set:

- **Typed structured output** — every catalog tool publishes a JSON output schema and
  returns validated structured content (see above).
- **Progress & logging** — `download_track` streams `Context` progress while the MP3
  downloads; playlist writes log via `ctx.info`.
- **Elicitation** — `delete_playlist` asks the client to confirm before the
  irreversible delete (when the client supports it).
- **Friendly errors** — auth/rate-limit failures surface as short, actionable messages
  (*"auth failed: 401 — check YANDEX_MUSIC_TOKEN"*), not raw status dumps.
- **Rate limiting** — a token-bucket limiter with exponential backoff on 429 protects
  against Yandex Music's aggressive rate limits (configurable delay).
- **Middleware** — a timing middleware logs each tool call's duration at debug level.
- **Lifespan** — the shared HTTP client is closed cleanly on shutdown.
- **Health probe** — over HTTP, `GET /health` returns `{"status": "ok"}`.
- **Read-only mode** — `YANDEX_MUSIC_READ_ONLY=1` hides the mutating tools via tag
  visibility for a safe browse-only deployment.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/evgenygurin/yandexmusic-mcp
cd yandexmusic-mcp
uv sync
```

Set your Yandex Music OAuth token (see
[how to obtain one](https://yandex-music.readthedocs.io/en/main/token.html)):

```bash
export YANDEX_MUSIC_TOKEN="y0_AgAAA..."
```

Your numeric user id is resolved automatically from the token on first use; set
`YANDEX_MUSIC_USER_ID` to override.

Run over stdio:

```bash
uv run yandexmusic-mcp
```

Or over HTTP:

```bash
YANDEX_MUSIC_MCP_TRANSPORT=http YANDEX_MUSIC_MCP_PORT=8000 uv run yandexmusic-mcp
```

### Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "yandexmusic": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/yandexmusic-mcp", "yandexmusic-mcp"],
      "env": {
        "YANDEX_MUSIC_TOKEN": "y0_AgAAA..."
      }
    }
  }
}
```

Claude Code: `claude mcp add yandexmusic -e YANDEX_MUSIC_TOKEN=... -- uv run --directory /path/to/yandexmusic-mcp yandexmusic-mcp`

## Configuration

All settings come from `YANDEX_MUSIC_*` environment variables (or a `.env` file),
validated by pydantic-settings. See [`.env.example`](.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `YANDEX_MUSIC_TOKEN` | — | OAuth token (required) |
| `YANDEX_MUSIC_USER_ID` | auto | Numeric uid; resolved from `/account/status` when unset |
| `YANDEX_MUSIC_BASE_URL` | `https://api.music.yandex.net` | API base URL |
| `YANDEX_MUSIC_TIMEOUT` | `30` | HTTP timeout (seconds) |
| `YANDEX_MUSIC_RATE_LIMIT_DELAY` | `1.5` | Min delay between API calls (seconds) |
| `YANDEX_MUSIC_RETRY_BACKOFF` | `2.0` | Backoff multiplier on 429 |
| `YANDEX_MUSIC_RETRY_ATTEMPTS` | `3` | Max retries on 429 |
| `YANDEX_MUSIC_DOWNLOAD_DIR` | `~/.yandexmusic-mcp/downloads` | Where `download_track` saves MP3s |
| `YANDEX_MUSIC_READ_ONLY` | `0` | Hide the mutating tools |
| `YANDEX_MUSIC_MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `YANDEX_MUSIC_MCP_HOST` / `YANDEX_MUSIC_MCP_PORT` | `127.0.0.1` / `8000` | HTTP bind address |

## How authentication works

Every request carries `Authorization: OAuth <token>`. The token is a standard Yandex
OAuth token with music scope — the same one the mobile apps use; the community
[yandex-music docs](https://yandex-music.readthedocs.io/en/main/token.html) describe
how to obtain it. There is no official public API: endpoints and shapes are
community-documented, and Yandex rate-limits aggressively — hence the built-in
token-bucket limiter with exponential backoff.

Track downloads (`download_track`) resolve a signed MP3 URL in three hops:
`/tracks/{id}/download-info` lists codec/bitrate variants; the variant's
`downloadInfoUrl` returns an XML manifest; the playable MP3 URL is derived from the
manifest via an MD5 signature. A Yandex Music subscription on the account is required.

Using the packaged async client directly is shown in
[`examples/use_client.py`](examples/use_client.py).

## Development

```bash
uv sync
uv run pytest       # tests (httpx MockTransport + in-memory FastMCP client)
uv run ruff check . # lint
uv run ruff format .
uv run mypy         # strict typing
```

Architecture notes and non-obvious gotchas for contributors live in
[CLAUDE.md](CLAUDE.md).

## Disclaimer

This is an unofficial client of an undocumented API. A Yandex Music account is
required (a paid subscription for downloads); use must comply with Yandex's terms of
service. The token is only ever sent to `api.music.yandex.net`.
