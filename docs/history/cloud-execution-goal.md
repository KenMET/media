# Cloud search, local execution

Objective: cloud alone initiates application connections to NAS, which needs no cloud address. Retain existing FRP, HTTPS proxy and media directories.

Historical configuration: cloud `MEDIA_CONTROL_PORT=28213` targets fixed loopback HTTP; cloud web `MEDIA_WEB_PORT=18214`, MCP 18210; NAS `MEDIA_WEB_PORT=18213`, no standard `MEDIA_CATALOG_URL`. Existing downloader/model connections remain required. Service authentication remains despite private ports.

## Implemented boundaries

Cloud web/MCP share `CloudCommands` for localized/original title search, discovery/details, Jackett and torrent retrieval. Cloud SQLite isolates releases by user. Authenticated, bounded evidence freezes identity, seasons/episodes and torrent/magnet materials for NAS.

NAS remains authoritative for accounts/permission/plans/revisions/idempotency/jobs, duplicate media, unknown submission, leases and mutation locks. It validates expiry, size and infohash and persists no cloud Jackett URL. Workers consume frozen evidence; execution-only rejects provider callbacks, including hidden processing paths. Explicit legacy URLs remain compatible without silently switching standalone tests.

## Acceptance: 2026-10-27

Disposable SQLite/download/library roots, serial low priority, final installed package:

- Image `media-mcp-cloud-execution-test:0.3.0` (`50f187550007`) passed **118 tests** offline with 0.5 CPU and nice 15. Four CLI/five static assets and both Compose templates were verified.
- Independent control 18613, cloud web 18614 and MCP 18610 used no role URLs. Real HTTP/MCP localized/original title search, TMDB details and SIMKL daily succeeded. Public Jackett `nyaasi` queried successfully twice; NAS searches explicitly rejected.
- Real SIMKL/TMDB movie/TV day/week lists produced eight fresh groups, without real media mounts.
- Initial pairing through 18613 produced private credentials and confirmation, then NAS closed pairing; hashes/sealed marker matched without printing secrets.
- Fresh `state/cloud-execution-final-20261027` state/media completed cloud preparation → real qBittorrent v5.1.4 acceptance/verification → ingestion → hardlink → sidecar → durable completed. NAS provider calls: zero. Source SHA256 unchanged, matching inode, link count 2, one subtitle.
- Web/MCP authority/revocation, forged/oversized evidence, duplicate submission and disconnected reconciliation were covered while NAS provider networking was prohibited.

Tools: `tests/manual/acceptance_cloud_tcp.py`, cloud branch of `tests/manual/acceptance_sqlite.py` (`MEDIA_ACCEPTANCE_CLOUD=true`), `tests/manual/verify_cloud_evidence.py`, `tests/test_cloud_execution.py`, `tests/test_split_ports.py` and security regressions.

The execution chain used controlled identity/model output and a locally generated complete torrent, not a new external-peer movie download. Real provider queries were separate. Test containers stopped with evidence retained; port-18414 main test stack, production media/downloader and old MySQL were untouched. Singapore host/proxy/certificates/FRP were outside local acceptance.

Status: implementation/local isolated acceptance completed. Legacy MySQL import remained separate migration work.
