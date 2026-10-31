# 0.2 LAN bundle acceptance receipt

Date: 2026-10-24. Counts/hashes describe that disposable instance, not the current image. See [security review](../security-review.md) and [superseded 0.1](acceptance-0.1.md).

## Completed scope

Historical `start.sh` built/initialized MCP, workers, qBittorrent and Jackett without MySQL/accounts. SQLite 3.40.1 used WAL, FULL synchronous, busy timeout and `BEGIN IMMEDIATE` claims with expired-lease takeover/stale-owner rejection. OS locks under shared state replaced advisory locks; crash release, replaced-lock rejection and stale post-I/O snapshots were verified. SQLite-native version journals covered upgrades, subtitle archives and rollback.

A real LAN client used unauthenticated TCP Streamable HTTP with eleven tools and completed-job lookup. Actual peers governed access; public peers could not forge forwarded headers. Uvicorn disabled proxy headers.

Bundled Jackett generated/retained its key and returned real caps XML HTTP 200 through the read-only config. qBittorrent accepted/verified a disposable torrent containing locally generated video without manual credentials. No external movie or production downloader was used.

The real SQLite/ffmpeg/hardlink/subtitle chain used fixture identity, reached completed, retained link count 2 and one subtitle record/file. Replacing the image retained completion; existing Codex authentication gated workers, all three heartbeats and four container health checks passed. Production Media/Portal/MySQL/Quant/Crawler/downloader were untouched.

## Results

Serial low-priority tests: ingestion 32, subtitles 83, SQLite/bootstrap/MCP/LAN/optional-auth/entrypoints 25; **140 passed**. Skill quick validation, `likec4 validate docs/new`, shell/Python syntax and parity for 83 runtime files passed. Focused multiprocessing exercised claims/locks inside an otherwise serial suite. Quant/Crawler suites were not run.

- Image: `sha256:dc228c1a8fcbd6612f547809126896ccaad81b480458449f004a14620348fb76`
- Runtime source SHA256: `bc525c40b4c852cf38bc0766674629cd2d2a5385333c673fd4c2c3169ec00091`
- [Full receipt](runtime-receipt-0.2.json); no PyMySQL in the image.

Isolation: project `media-lan-acceptance`, MCP 19210, qBittorrent 19211, Jackett 19212, torrent 49181, separate state/config/media. It was removed after acceptance. `tests/manual/acceptance_sqlite.py` requires `MEDIA_ACCEPTANCE=isolated-container`, `/state/media.sqlite3`, `/state/.acceptance`, fresh acquisition tables; `MEDIA_ACCEPTANCE_QBIT=real` means a dedicated acceptance downloader only.

## Remaining external work

New Jackett had `configured_sites=0`; configure authorized sites/logins. Real searches/transfers/provider quotas/long-film quality and ChatGPT account/network access remained unverified. LAN no-auth does not make the address reachable from cloud. Legacy records/tasks and writer retirement were not adopted.

The active private profile switched to the new bundle while preserving TMDB/subtitle/Codex/Bark; database passwords, MCP/owner credentials and manual Jackett keys were no longer default requirements. Old profiles were privately saved under ignored `state/env-backups/`.
