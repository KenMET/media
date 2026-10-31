# Independent Media 0.1 acceptance

Historical MySQL/OAuth profile, superseded by SQLite/bundled services/unauthenticated LAN. See [current index](../acceptance.md).

Date: 2026-10-23. Scope: extraction, install/image, MCP/OAuth/workflow, durable submission intent and ingestion/subtitles. Original production services/database were not adopted.

## Evidence

- Runtime resides under `media_mcp` without `apps.*`; source provenance is in `source-manifest.json` and old production code remained.
- Historical `./start.sh` started an independent OpenWrt Compose project, printed loopback MCP only after success, and used openssl/hexdump without requiring od.
- Built from clean `python:3.12-slim-bookworm`, not a Phantom base; context was Media only.
- Eleven tools and the workflow resource were discoverable. Real TCP Streamable HTTP covered owner browser login, PKCE, calls and revocation; unauthenticated requests returned 401.
- OAuth unit coverage included invalid PKCE, authorization-code reuse, persistent tokens after restart, refresh rotation/old-token rejection, revocation, redirect and CSRF.
- Acquisition covered read-only reconciliation after timeout, no duplicate submission, foreign torrent rejection, expiry/conflicts/idempotency/path/title/season/episode fences.
- Disposable MySQL 8.4.13 covered claim/renew/stale owners, generated video, canonical hardlinks, Chinese sidecars and durable completion. Downloader/classification replies were fixtures, not external release downloads.
- An existing Codex App Server completed a real authenticated read-only model probe without inherited MCP tools. The isolated worker passed startup gating, monitor/ingest/subtitle heartbeats and health. No new model login/runtime was created.
- Image contained ffmpeg, ffprobe, mkvmerge, mkvpropedit, tesseract, dotnet and PgsToSrt DLL. LikeC4 passed `likec4 validate docs/new`.

## Results

Serial low-priority tests: ingestion 32, subtitles 83, new MCP/OAuth/acquisition/path/startup/dependency tests 16; **131 total passed**. Skill quick validation and Python/shell syntax passed. TCP exposed eleven tools and rejected revoked tokens with 401; readiness changed only after the real model gate. The disposable MySQL/file chain completed with video link count 2 and one subtitle record/file.

Historical `tests/acceptance_mysql.py` and `tests/manual/acceptance_http.py` required `MEDIA_ACCEPTANCE=isolated-container`, `MEDIA_DB_NAME=media_acceptance_*`, `/state/.acceptance` and fresh acquisition tables. Never target production.

Temporary MCP was `127.0.0.1:18219/mcp`, database loopback 18316, Compose project `media-mcp-acceptance`. All mounts were disposable and the instance was removed afterward; this was not a public ChatGPT endpoint.

Eighty-one installed runtime Python files matched source, excluding tests/caches. See [receipt](runtime-receipt-0.1.json).

- Image: `sha256:315cd37f459f85bd3bbc27403a038ec63ed6b0f829c0c573d174f0f36bea1155`
- Runtime source SHA256: `ae23d84753b7226ed5364f0bd0115385afb5cd373705c73d926f7e96553ad50e`

These are historical build receipts, not proof of future source/image parity or external deployment.

## Unverified conditions

Real user sites/Jackett/TMDB quotas/downloader account and external downloads; actual ChatGPT installation/phone/HTTPS/tunnel; provider availability, long-film PGS OCR and optional ASR quality remained unverified. ASR was disabled. Follow-up tracking, forced versions, deletion, media-server refresh and Portal entrypoints were outside that release. Legacy database/NAS-Tools migration and writer cutover remained separate work.

Configure private settings and matching paths before protected access. Passing tests did not stop existing NAS-Tools or establish every dependency's availability.
