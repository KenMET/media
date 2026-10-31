# Initial Media 0.3 local acceptance

Date: 2026-10-25. Both roles ran on NAS `192.168.8.1`; Singapore deployment and successful Douban integration were explicitly outside first-release acceptance. Later real discovery/public search/Sintel/model/subtitle/bilingual/recovery evidence is in [live acceptance](live-acceptance.md); this page retains the earlier fixture stage.

Implemented shared web/MCP search/plans/idempotent acquisition/progress/history/allowed retries/library/subtitles; administrator bootstrap/accounts/passwords/roles/grants/audit; one-time expiring/revocable personal tokens invalidated by account/password/role changes; unchanged default owner LAN mode; TMDB details/cache/backoff and honest Douban unavailability; NAS authority with authenticated cloud forwarding and no remote media/SQLite mounts; role setup and the historical `start.sh` alias with per-dependency URL selection.

## Results

- Installed NAS package: 71 tests passed serial nice 15, 0.5 CPU, offline container.
- Wheel 0.3.0: four CLIs/three assets.
- Actual TCP web/provider/MCP: one submission on repeated keys, 503 while disconnected, preserved root-object media_status protocol.
- Disposable SQLite/ffmpeg/canonical hardlink/sidecar/lease/completion passed.
- Actual setup local/cloud started separate copies with reachable qBittorrent/Jackett UI/API, login and MCP user tokens. No real download was submitted in that Compose stage.
- Browser covered login/discovery/release selection/confirmation/details/history/users/grants/accounts.
- Old media-monitor/Quant/Crawler stayed running without database/task adoption.

Fixed LAN HTTP lacking randomUUID by using getRandomValues, and OpenWrt lacking od by generating tokens with image Python, failing closed on empty/generation errors. Search/download/model fixtures and empty sites did not establish real credentials/transfers. SQLite used marked disposable mounts only.

Historical preview: `http://192.168.8.1:18314`, private account in ignored `state/preview-login.txt`; container `media-platform-preview-20261025` had fictional metadata/releases and temporary SQLite, no downloader/worker, queued tasks without downloads, and reset on restart. Its historical stop command was `docker stop media-platform-preview-20261025`. The role Compose acceptance copy under ignored `state/platform-compose-acceptance-20261025` was stopped; ordinary developer previews stopped too. The demo remained for inspection at that checkpoint.

Follow [same-host testing](../platform-testing.md) before actual credentials or network deployment. Production services were not cut over; real split HTTPS/tunnel/domain access needed separate acceptance.
