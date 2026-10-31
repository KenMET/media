# Split deployment with an existing reverse proxy and FRP

Use the single [.env.example](../.env.example) on both hosts, filling only each host's cloud or local/NAS groups. This does not mean sharing private settings or credentials. The launcher preserves existing `.env` files.

## Minimal settings

Explicitly verify cloud web/MCP/FRP ports, TMDB key and Jackett URL; on NAS verify control port, downloader URL, media root, model endpoint and credential file. Defaults are shown to compare with existing infrastructure. Valid model credentials must already exist. Omit `JACKETT_URL` or `QBITTORRENT_URL` only when selecting the corresponding bundled service.

| Purpose | Default | Override only when needed |
| --- | --- | --- |
| Cloud web | `0.0.0.0:18214` | `MEDIA_CLOUD_WEB_BIND`, `MEDIA_CLOUD_WEB_PORT` |
| Cloud MCP | `127.0.0.1:18210` | `MEDIA_CLOUD_MCP_PORT` |
| Cloud local FRP mapping | `127.0.0.1:28213` | `MEDIA_CLOUD_CONTROL_PORT` |
| NAS control | Template `192.168.8.1:18213` | `MEDIA_LOCAL_CONTROL_BIND`, `MEDIA_LOCAL_CONTROL_PORT` |
| NAS model | `ws://127.0.0.1:8108` | `CODEX_APP_SERVER_URL` |
| Downloads/library | `downloads` / `media_hub` under `MEDIA_LOCAL_DATA_DIR` | Usually no in-container override |
| NAS/cloud state | `./state` / `./state-cloud` | Retain existing custom state paths |

Add actual downloader username/password when required. Omission means existing unauthenticated access, never a default-password attempt. Web access still requires accounts. Optional `MEDIA_PROXY_IPS` identifies actual proxy socket peers for client-IP rate limiting; otherwise non-loopback forwarded headers are ignored and socket IPs share rate buckets.

`TMDB_API_KEY` belongs on cloud. Optional `OPENSUBTITLES_API_KEY`, `SUBDL_API_KEY`, `ASSRT_API_KEY` belong on NAS; missing keys skip those sources without disabling local reuse/extraction, other providers or translation. OpenSubtitles may additionally need `OPENSUBTITLES_USERNAME` / `OPENSUBTITLES_PASSWORD`. Media does not create third-party keys or edit them through the website. Online subtitle retrieval still runs locally, separately from cloud TMDB/Jackett search.

Optional NAS `BARK_URL` is a full private device push endpoint. Without it, notifications are local records. Preserve existing custom ports, media roots and state settings; the minimal template neither moves databases nor changes running containers.

## NAS

Preserve existing `/data/downloads` and `/data/media_hub`. Configure the existing downloader/authentication and model. Expose control at `MEDIA_LOCAL_CONTROL_PORT=18213` to existing FRPC. The NAS needs no cloud domain, URL or provider address.

```sh
# For new installations only; merge into an existing .env instead of overwriting it.
cp .env.example .env
sh setup.sh local
```

Control binds the explicit `MEDIA_LOCAL_CONTROL_BIND`, template `192.168.8.1`. Internal credentials are generated automatically. New local configurations use execution-only mode: control/workers and optional downloader, without Jackett or search. Frozen cloud evidence drives local download/ingestion/subtitles with identity checks. Startup neither adopts old tasks nor imports MySQL; complete the [migration plan](production-cutover-plan.md) before production cutover.

## Cloud

Configure cloud ports, TMDB and existing Jackett (empty selects bundled). `MEDIA_CLOUD_WEB_PORT` and `MEDIA_LOCAL_CONTROL_PORT` avoid cross-role collisions. `MEDIA_CLOUD_CONTROL_PORT` targets fixed cloud loopback; ordinary split setup needs no duplicated domains, certificates, `MEDIA_WEB_PUBLIC_URL` or `MEDIA_ALLOWED_HOSTS`.

```sh
# For new installations only; preserve existing private settings.
cp .env.example .env
sh setup.sh cloud
```

Start local and establish FRP first: NAS `192.168.8.1:18213` → cloud loopback `127.0.0.1:28213`. Cloud pairs over this port and stores mode-0600 credentials; NAS then closes initial pairing. Existing credentials are reused without printing/overwriting, and API authentication remains enforced.

Accounts, passwords and sessions live on NAS. Its bootstrap token defaults to `state/web-bootstrap-token`, never cloud `state-cloud`. On NAS, privately read `docker compose -f compose.local.yml exec -T local-control cat /state/web-bootstrap-token` and enter it in the cloud initialization page. Do not send it through chat/logs or copy it to cloud. Initialization closes after an administrator exists; recreating the token cannot reset an account.

FRPC `localIP` must match the NAS bind, `localPort` the control port, and `remotePort` the cloud mapping port. FRPC and control must share host networking. Media does not modify other FRP mappings. Old local configurations without the new bind fall back to `MEDIA_WEB_BIND_HOST` or loopback.

Cloud performs localized/original-title search, discovery, details, Jackett queries and torrent retrieval. Per-user search snapshots freeze bounded torrent bytes/magnets, identity and episodes. NAS validates permission, expiry, infohash, existing media, plan revision and idempotency before creating jobs. Workers consume frozen evidence rather than cloud Jackett URLs. BT peers/trackers and subtitle/model services remain local external dependencies; execution-only does not mean offline.

### Pairing trust

The cloud mapping must be loopback-only, never public. Automatic cloud pairing rejects non-loopback HTTP URLs. Local pairing requires explicit enablement: loopback binds accept loopback peers; an explicit NAS private bind accepts only a host self-connection whose actual peer and local IP both equal the NAS address. Other LAN peers and forged headers are rejected. Wildcard/public binds cannot auto-pair, and the public gateway never forwards the pairing endpoint.

If cloud credentials are lost, run `sh setup.sh local pair` on NAS and restart cloud setup. Retain the production database. Existing private FRP authentication/encryption remains required; loopback mapping alone is not transport encryption. Media does not rewrite FRP configuration.

### Existing reverse proxy

Cloud web defaults to `0.0.0.0:18214`. A Docker bridge proxy must target a reachable host IP/port, not its own `127.0.0.1` or the FRP control port. The recorded example used web `10.3.0.7:8800`, not control `8802`. Preserve Host and overwrite/append actual client provenance. Login, CSRF, same-origin checks, MCP tokens and Secure cookies remain; existing proxy supplies HTTPS.

`MEDIA_CLOUD_WEB_BIND` alone controls this web bind and defaults to `0.0.0.0`; an old `MEDIA_WEB_BIND_HOST=127.0.0.1` no longer overrides it. Compose maps the internal legacy variable for image compatibility. Recreate through setup to apply environment changes; restart alone is insufficient.

For trusted loopback proxies, the application reads the last proxy-appended `X-Forwarded-For` value rather than the forgeable first value; standard forwarding needs no extra X-Real-IP. A proxy must not pass client headers unchanged. With no `MEDIA_PROXY_IPS`, login remains reachable and business requests require identity. Setting it additionally restricts peers to loopback/exact proxies and trusts their provenance. Enter the proxy's actual socket source, not the upstream host IP. Docker-proxied MCP requires an explicit proxy source and corresponding bind. Untrusted requests behind one proxy share the socket-IP rate bucket.

Only cloud initiates application connections to NAS. New local mode needs no `MEDIA_CATALOG_URL`. Manage FRPC/FRPS server configuration independently.

## Persistence

Cloud Jackett paths are fixed in `compose.cloud.yml`:

| Host path | Container path | Contents |
| --- | --- | --- |
| `/root/container_cache/jackett/config` | Jackett `/config` | `Jackett/ServerConfig.json`, Indexers, DataProtection, logs/cache |
| `/root/container_cache/jackett/downloads` | Jackett `/downloads` | Torrent/blackhole exports, not NAS video downloads |
| `/root/container_cache/jackett/config` | cloud-web/cloud-mcp `/services/jackett` read-only | Existing key and public site configuration |

Initialization creates defaults only when `ServerConfig.json` is absent, retaining sites/keys/DataProtection. A nonempty URL avoids starting/initializing another Jackett but still reads the fixed local mount. Cloud ignores `MEDIA_JACKETT_CONFIG_DIR`.

NAS mounts the entire `MEDIA_LOCAL_DATA_DIR` at `/data`: host `/mnt/media` produces `/mnt/media/downloads` and `/mnt/media/media_hub`, visible as `/data/downloads` and `/data/media_hub`. Advanced runtime roots need no standard-template entries.

Cloud `./state-cloud` persists catalog/search snapshots; NAS `./state` persists accounts, downloads, processing/recovery. Internal credentials default to host `./state/control-token`. Relative paths refer to each deployment directory. Rebuilds reuse bind mounts; moving directories requires preserving actual state. Cache TTLs still apply. Retain existing `MEDIA_LOCAL_STATE_PATH`; deleting it selects `./state` without migration. No cloud-to-NAS data copy or existing Jackett replacement occurs automatically. Standalone path options remain compatible.

## Compatibility

- Role-specific web/control ports take precedence over old `MEDIA_WEB_PORT`.
- `MEDIA_CLOUD_CONTROL_PORT` takes precedence over legacy control URLs, accepts 1–65535 and uses loopback HTTP. Old URLs remain supported without a port; new cloud defaults to 28213. Same-host isolated tests can use 18213.
- Existing local `MEDIA_CATALOG_URL` retains its compatibility mode. Removing it and restarting local selects `MEDIA_EXECUTION_ONLY=true`; editing the template does not edit private `.env`.
- Same-host LAN web tests can explicitly use `MEDIA_WEB_MODE=lan` and `MEDIA_WEB_BIND_HOST=0.0.0.0` with existing LAN checks; wildcard binding cannot auto-pair and is not recommended for public deployments.
- Explicit legacy `MEDIA_WEB_PUBLIC` retains old mode. Explicit `MEDIA_WEB_MODE=proxy` selects the existing-proxy profile; new cloud setup defaults to proxy when both are omitted.
- Dependency URLs retain reuse/bundled selection; bundled admin ports remain loopback by default.
- Service pairing, website passwords and model credentials have distinct purposes.

The original delivery changed entrypoints/templates and isolated validation, not existing private configuration, FRP/proxies or production data. See [cloud search acceptance](history/cloud-execution-goal.md); that report did not establish deployment on the actual Singapore host.

## Startup checks

Local startup reads qBittorrent's version only: no categories, downloads or task edits. Failures identify address/authentication checks. After control readiness, workers complete model, directory/hardlink and subprocess initialization. Setup checks every 5 seconds, up to 60 times, succeeds only after all probes pass, and exits nonzero on timeout. Inspect `sh setup.sh local logs`. Service names are described in [service naming](service-names.md).
