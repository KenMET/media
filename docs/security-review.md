# Media security and availability review

For the 2026-10-26 multiuser/gateway review, login throttling reproduction and port checks, see [the later report](history/security-review-20261026.md). This page records the 2026-10-24 review.

Scope: independent Media configuration/startup, MCP, indexer downloads, files/subtitles, credentials and documentation. Evidence came from code review, disposable tests and existing runtime records, not LAN scanning, production attacks, service shutdown or rebuilding. It is neither a vulnerability-free guarantee nor a complete dependency CVE/SBOM audit.

## Fixes in that review

| Issue | Impact | Fix |
| --- | --- | --- |
| LAN peer checks lacked Host/Origin policy | Potential browser rebinding/cross-origin exposure, depending on other HTTP/MCP defenses | Explicit Host allowlist and same-origin checks for HTTP/WebSocket; IP/localhost defaults and explicit DNS names |
| Jackett read responses before a 4MiB check | Excess memory through abnormal provider responses | Stream and stop/close at the bound, retaining site-level failure isolation |
| Existing `.env` permissions could be broad | Other host accounts could read secrets | Tighten to 0600 at startup without printing contents |
| Root-created 0600 config mismatched non-root PUID/GID | New dependencies could not read/save configuration | Match new config/admin directory ownership without recursive edits of existing media/config |
| Startup always claimed no login | Misleading explicit bearer/OAuth deployments | Report actual authentication mode |

Default LAN MCP remained unauthenticated. Arbitrary DNS aliases may now require exact `MEDIA_ALLOWED_HOSTS`; actual LAN IPs remain usable.

## Existing fences

- Use actual socket peers rather than forwarded headers; private CIDRs are reachability, not identity.
- Releases/plans/revisions/idempotency define acquisition. Reconcile unknown outcomes and never adopt unowned downloader jobs.
- Jackett downloads use same-origin URLs, bounded same-origin redirects or valid v1 magnets, with pre-submission infohash checks; arbitrary external HTTP redirects remain blocked.
- Path checks reject escape/symlink aliases. SQLite leases, OS locks and version journals fence publication. Never edit hardlinked video bytes in place.
- ZIP/GZIP extraction is bounded; XML uses defusedxml. Chinese dialogue verification uses content rather than labels/styles/credits. The 30% heuristic does not prove translation accuracy or full-film completeness.
- Reprocessing retains rejected originals; retry grants no downloader/video deletion capability.
- Git/Docker ignore private credentials, state and services, but exact staged review remains necessary. Model tokens mount read-only; Media does not start the model service.

## Historical unresolved risks

### Dependency admin pages: trusted LAN only (high)

At this review, bundled qBittorrent bypassed login for LAN and Jackett initially lacked an admin password. Their pages bypass MCP Host/Origin checks. qBittorrent initialization used `WebUI\HostHeaderValidation=false`; MCP fixes did not establish complete bundle rebinding protection.

The review did not change live downloader authentication/proxy policy or blindly enable Host checks: external port 18211 mapped to internal 8080, and version-specific validation could break UI/API/workers. Validate allowed hosts/ports independently. See [qBittorrent source](https://github.com/qbittorrent/qBittorrent/blob/master/src/webui/webapplication.cpp); deployed images still require tests.

Restrict admin reachability and never publicly tunnel unauthenticated administration. Untrusted/multiuser administration needs protected identity, a considered bypass policy, Jackett password and compatible backend credentials. A firewall alone is not a full browser-rebinding defense. Later loopback-binding work is documented in newer reports.

### Privilege and external content (medium)

Default PUID/PGID and MCP/workers were root with host networking. Containers are not strong malicious-media sandboxes; ffmpeg/OCR/downloader/providers/model inputs are attack surfaces. Mount only necessary data, never sensitive host roots or Docker sockets. Dependency PUID changes do not lower every service. Full privilege/egress/tool isolation had not received runtime acceptance.

### Supply chain (medium)

Default dependency images used `latest`; builds downloaded tools/system packages. Pin versions/digests, retain old images and update one service at a time for reproducibility. No complete online vulnerability/signature/hash audit occurred.

### Capacity and notification delivery (medium/low)

History, rejected subtitle backups and media lacked automatic total-capacity reclamation. Monitor disk/CPU/provider budgets; do not expose trusted interfaces to untrusted callers. Bark can fail. Local records do not establish end-to-end delivery or guarantee every failure receives a phone alert.

## Validation evidence

Serial low-priority disposable tests covered Host/Origin/headers/WebSocket, bounded responses, bootstrap ownership/non-overwrite, startup/permissions and acquisition/subtitles. Thirty-five tests passed across `test_lan_boundary`, `test_bootstrap`, `test_start`, `test_release_search`, `test_jackett_download`, `test_acquire`, `test_subtitle_content`. That isolated environment used Python 3.10; supported deployment remained 3.11+, image 3.12. No new full Docker/MCP integration acceptance was claimed.

Shell files were normalized to LF with `.gitattributes`; `.env.example` remained LF and value parsing tolerated trailing CR. Syntax, internal links, configuration consistency and LikeC4 were checked. [Historical acceptance](acceptance.md) remains old receipts rather than proof of the current image.
