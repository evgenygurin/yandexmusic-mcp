# CLAUDE.md

MCP server for the Yandex Music API (FastMCP v3). Extracted from
`dj-music-plugin`'s `app/providers/yandex/` into a standalone repo, structured
after `beatport-mcp`.

## Commands

```bash
uv sync             # install (creates .venv)
uv run pytest       # tests — httpx MockTransport + in-memory FastMCP Client
uv run ruff check . # lint (ruff format . to fix style)
uv run mypy         # strict typing over src/
uv run yandexmusic-mcp  # run the server (stdio; YANDEX_MUSIC_TOKEN required)
```

## Layout

- `src/yandexmusic_mcp/client.py` — async HTTP client; raw dicts out, YM's
  `{"result": …}` envelope unwrapped in `_request`. All auth/rate-limit/HTTP
  errors become typed `YandexError` subclasses with actionable messages.
- `src/yandexmusic_mcp/server.py` — the FastMCP server: tools + annotations,
  resources (`yandexmusic://…`), prompts, lifespan, `/health`, read-only mode.
- `src/yandexmusic_mcp/models.py` + `formatters.py` — slim Pydantic output
  models and the raw-dict → model mappers.
- `src/yandexmusic_mcp/rate_limiter.py` — token bucket + exponential backoff.
- `src/yandexmusic_mcp/filters.py` — client-side track post-filters used by
  `search_tracks` (YM search has no structured filters).

## Non-obvious gotchas

- **Playlist ids are composite** — YM addresses playlists as
  `(owner_uid, kind)`; every tool accepts `"owner:kind"` or a bare kind (own
  uid is substituted). `client._split_playlist_id` is the single place that
  parses this.
- **Playlist writes need a revision** — `change-relative` is optimistic
  concurrency. `server._resolve_revision` auto-fetches the current revision
  when the caller omits it; don't remove that or every `add_tracks` call from
  an LLM will 412.
- **uid is resolved lazily** — `client.user_id()` fetches `/account/status`
  once when `YANDEX_MUSIC_USER_ID` is unset. Tests that hit `/users/{uid}/…`
  must either pass `user_id=` to the client or route `GET /account/status`.
- **Rate limiter is load-bearing** — YM 429s aggressively on bursts. The
  default 1.5s inter-call delay is intentional; tests pass `delay_s=0.0`.
- **Download URL signing** — the MP3 URL is derived from an XML manifest via
  `md5(SALT + path[1:] + s)` (`client._build_signed_mp3_url`, salt is a
  community-known constant). If downloads 403, the salt or scheme changed.
- **ids are strings in models** — YM mixes int/str ids across endpoints;
  formatters normalize everything to `str`.
- **Search types are singular** — the API wants `type=track`; the client maps
  the plural aliases (`tracks` …) the tool surface uses.
- **`server._client` is the test seam** — `tests/test_server.py` monkeypatches
  it with `FakeYandexClient`; keep new tools going through `get_client()`.
