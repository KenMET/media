# Production cutover and legacy Media reuse

2026-10-26. Read-only preflight of `phantom_slayer/apps/media` and the actual old runtime; no production cutover, shutdown or media mutation occurred in this inspection.

Current configuration is in [split deployment](split-deployment.md): reuse the existing reverse proxy and private FRP, with automatic initial service pairing. The migration boundaries below remain valid even though the original network plan evolved.

## Observed state

- Old `media-monitor` and shared `phantom-mysql` were running. Old Media uses MySQL; this project uses local SQLite. No `.env` switch connects the new runtime directly to old MySQL.
- Read-only transactions found `media_link` 808 rows, `media_subtitle` 1242, `tmdb_cache` 210, with mappings marked linked. The actual old database lacked `media_processing_job` and `media_version_change`; newer repository schemas were not deployed evidence.
- Old container mounted `/data:/data`; `/data/downloads` and `/data/media_hub` existed. Only the first 32 linked pairs were sampled: all existed within expected roots with matching device/inode. This was not a full scan or full video read.
- Old downloader configuration targeted port 8100. Unauthenticated version access returned 403. Existing private credentials are required; no default-password attempt or authentication change occurred.
- Corresponding media/subtitle/TMDB models support conversion while retaining existing files/hardlinks.
- No completed MySQL→SQLite migration command was established. Dumps/data directories are not SQLite; export, conversion, validation and dry-run reporting must precede adoption.

## Topology

| Singapore/cloud | Mainland NAS |
| --- | --- |
| HTTPS web/gateway, Jackett/indexers, optional same-origin MCP, FRPS/VPN | Existing qBittorrent, control API, workers, production SQLite, downloads/library, model connection/credentials |

Cloud mounts neither videos nor production media database. Authenticated requests reach NAS, whose workers handle files. A nonempty existing downloader URL avoids a second downloader.

Suggested FRP: NAS explicit `192.168.8.1:18213`, same-host FRPC local target, cloud loopback mapping such as `28213`; set only cloud `MEDIA_CLOUD_CONTROL_PORT=28213`. Cloud handles search/torrents; initial pairing accepts only local self-connections. Never expose raw control/FRP ports publicly.

The original backend plan used loopback web/MCP 18214/18210 behind HTTPS with Host and actual client provenance. Current Docker proxy details are in split deployment. This plan did not verify a real domain, certificate or FRPS configuration. Existing VPN is another option, requiring reachable addresses, probes and host policy rather than blindly replacing loopback URLs.

## Paths

Prefer preserving in-container `/data/downloads` and `/data/media_hub` so old records and downloader content paths remain valid. Illustrative configuration, not approved production settings:

```dotenv
MEDIA_LOCAL_DATA_DIR=/data
MEDIA_LOCAL_STATE_PATH=/local-disk/media-production-state
MEDIA_DOWNLOAD_ROOT=/data/downloads
MEDIA_LIBRARY_ROOT=/data/media_hub
QBITTORRENT_URL=http://existing-downloader:port
MEDIA_LOCAL_CONTROL_BIND=192.168.8.1
MEDIA_LOCAL_CONTROL_PORT=18213
```

Keep authentication/model/service tokens private. SQLite state must be on NAS local storage, not a Windows SMB mount.

For alternate roots, document complete host/container mappings. Downloader paths must exist unchanged in workers. Use one common-parent mount to preserve hardlinks; separately mounting two paths can prevent `link` even on one host disk. Cross-filesystem operation does not silently fall back to copying.

Some legacy full-scan paths retain `/data/downloads`, and subtitle scans have `SUBTITLE_SCAN_ROOT`. Alternate container paths require auditing every entrypoint plus imported paths/hashes and regression. Two changed environment values do not establish complete scan compatibility. Avoid moving old files at initial cutover.

## Migration requirements

1. Privately export the three relevant tables and schemas while retaining existing whole-MySQL backups. Do not migrate unrelated Quant/Crawler/account tables or stop shared MySQL.
2. Initialize an isolated SQLite copy, validate columns/time/JSON types, duplicate hashes and conflicts. Convert media mappings, subtitle associations and TMDB cache with dry-run, idempotence and source-row manifests.
3. Verify all counts, existence, path bounds, device/inode and subtitle associations. Report missing/conflicting files without automatic rename/rebuild/deletion. The 32-row sample is insufficient.
4. Import library records, not fabricated acquisition jobs. Existing downloader/seeding tasks remain unchanged and untagged; they do not become new download history or queue ownership. Any historical view must explicitly retain its read-only provenance.
5. Initialize accounts/tokens/grants. Imported media is visible to administrators/media managers, not automatically all ordinary users. Do not guess historical ownership.
6. Inventory downloaded files without old mappings separately for read-only review; do not trigger whole-library reidentification at startup.

## Cutover sequence

Complete tooling and disposable rehearsal first. Prepare production settings with workers stopped; inspect an imported-state copy through the website. During the actual window, pause old `media-monitor` and all writers of the same directories, take a consistent final export/incremental check, then start the sole new worker. MySQL locks and SQLite filesystem locks do not coordinate concurrent old/new writers.

Retain old database, container configuration and consistent snapshots. For rollback, stop new writers and reconcile post-cutover records/files before restoring matching old state. Restarting old monitoring alone does not guarantee lossless rollback. Do not delete videos, restart/rebuild the existing downloader, or use the port-18414 test database as production.

Cloud directory, existing Jackett, HTTPS/SSH access and final host paths remained unresolved in this preflight. Actual execution remains `sh setup.sh local` / `sh setup.sh cloud` only after preparation; do not bypass migration by starting against legacy media.
