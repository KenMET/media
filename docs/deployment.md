# Deployment, updates and operations

Follow the [README](../README.md) for initial setup. Commands on this page run in the server's `media/` directory, not on a Windows editing client.

For an existing reverse proxy and private FRP, use [split deployment](split-deployment.md) and the cloud/local groups in `.env.example`. Cloud web defaults to `0.0.0.0`, supports container proxies and retains account authentication. Internal credentials pair automatically. Cloud needs only `MEDIA_CLOUD_CONTROL_PORT`; the NAS needs no cloud address. Search and torrent retrieval run on cloud. The advanced standalone settings below, including explicit `MEDIA_WEB_PUBLIC=true` domain/TLS validation, are not mandatory fields in the minimal split template.

## Configuration

### Existing downloader and Jackett

A nonempty URL reuses an existing service; an empty or absent URL starts the bundled container on its owning host. Local owns the downloader, cloud owns Jackett; standalone supports mixed combinations.

```dotenv
QBITTORRENT_URL=http://actual-host:8080
QBITTORRENT_USERNAME=your-username
QBITTORRENT_PASSWORD=your-password
JACKETT_URL=http://actual-host:9117
MEDIA_JACKETT_CONFIG_DIR=/existing/jackett/config-root
```

Store credentials only in private `.env`. Omit downloader credentials only when its existing policy permits unauthenticated access. Jackett's key is read from the read-only configuration or explicit `JACKETT_API_KEY`; never embed credentials in URLs.

Run `sh setup.sh`. For example, setting only `QBITTORRENT_URL` reuses that downloader and starts bundled Jackett. An unreachable external service fails rather than falling back to another container. Logs/stop manage Media and selected bundled dependencies. Switching URLs does not retire old bundled containers automatically; handle retirement explicitly while retaining data. Use unquoted complete URLs without trailing comments. Host environment values take precedence over `.env`.

Legacy standalone Jackett requires a configuration root containing `Jackett/ServerConfig.json` and `Jackett/Indexers/`, mounted read-only. A remote URL/key alone cannot supply the configured-site list. See [local testing](platform-testing.md) for role-based deployments.

`MEDIA_LOCAL_DATA_DIR` is the host directory mounted at `/data`. Downloader paths must be visible unchanged to the worker. Defaults are `/data/downloads` and `/data/media_hub`; advanced overrides are `MEDIA_DOWNLOAD_ROOT` and `MEDIA_LIBRARY_ROOT`. There is no arbitrary path translation. Downloads and library must support hardlinks on one filesystem. Host networking makes localhost refer to the deployment server; other containers need reachable published ports or addresses.

The minimal template omits advanced settings, which can still be added without changing defaults. It never rewrites existing `.env`. Compose reads the file; do not `source .env`. The launcher uses simple `KEY=value` parsing for paths/ports: avoid quotes, variable references, trailing comments and spaces. Use actual absolute paths or `./relative-path`.

| Setting | Default / purpose |
| --- | --- |
| `QBITTORRENT_URL` | Empty starts bundled service; nonempty reuses existing service |
| `QBITTORRENT_USERNAME` / `QBITTORRENT_PASSWORD` | Empty; existing downloader authentication |
| `JACKETT_URL` | Empty starts bundled service; nonempty reuses existing service |
| `JACKETT_API_KEY` | Optional; defaults to mounted configuration |
| `MEDIA_JACKETT_CONFIG_DIR` | Standalone only, default `MEDIA_SERVICES_DIR/jackett`; cloud fixes `/root/container_cache/jackett/config` |
| `TMDB_API_KEY` | Required for title/year/season/episode metadata |
| `CODEX_APP_SERVER_URL` | `ws://127.0.0.1:8108`; existing compatible model service |
| `CODEX_TOKEN_FILE` | `./state/codex-token`; nonempty host credential file matching the endpoint |
| `MEDIA_LOCAL_STATE_PATH` | `./state`; local SQLite, WAL, SHM, locks and logs |
| `MEDIA_LOCAL_DATA_DIR` | `./data`; full data parent mounted at `/data` |
| `MEDIA_SERVICES_DIR` | `./services`; bundled dependency configuration |
| `MEDIA_LOCAL_MCP_BIND` | `0.0.0.0`; personal LAN MCP; keep local health probes reachable |
| `MEDIA_ADMIN_BIND` | `127.0.0.1`; separate downloader/Jackett admin binding; public mode requires loopback |
| `MEDIA_LAN_IP` | Optional display address only; changes neither binding nor firewall |
| `MEDIA_LAN_CIDRS` | Optional comma-separated actual MCP client networks; defaults private/loopback; retain `127.0.0.0/8,::1/128` for probes |
| `MEDIA_ALLOWED_HOSTS` | Exact DNS names such as `media.home`, without scheme/port/path/wildcards; LAN IPs and localhost need no entry |
| `MEDIA_LOCAL_MCP_PORT` | `18210`; HTTP MCP at `/mcp` |
| `MEDIA_QBITTORRENT_PORT` | `18211`; downloader admin/API |
| `MEDIA_JACKETT_PORT` | `18212`; Jackett admin/API |
| `MEDIA_TORRENT_PORT` | `48181` TCP/UDP; bundled downloader BT traffic only |
| `PUID` / `PGID` | `0` / `0`; bundled dependency ownership, not an MCP/worker non-root switch; external services unchanged |
| `TZ` | `Asia/Shanghai` |
| `OPENSUBTITLES_API_KEY`, `SUBDL_API_KEY`, `ASSRT_API_KEY` | Optional providers, subject to their quotas, authentication and availability |
| `BARK_URL` | Optional full device push endpoint; empty writes local records only |
| `SUBTITLE_SYNC_MODE` | `required`; failed synchronization is not success; `auto`/`disabled` weaken alignment guarantees |
| `SUBTITLE_ENABLE_AUDIO_ASR` | `false`; enabling does not install/download an ASR model |
| `INSTALL_OCR` | `true`; install PGS OCR tools at image build time; changes require rebuild |
| `MEDIA_AUTH_MODE` | Standalone `none`; explicit `bearer`/`oauth` owner mode or `platform` web-account tokens, still subject to LAN middleware; cloud uses user tokens |

Bearer mode additionally requires `MEDIA_MCP_TOKEN` of at least 32 characters. OAuth requires `MEDIA_PUBLIC_URL` and `MEDIA_OWNER_PASSWORD` of at least 24 characters. These are explicit alternatives, not quick-start requirements. They do not provide TLS, tunnels or network reachability. Never send secrets through chat.

Choose directories before the first download. Changing data paths, UID/GID or database location does not migrate existing jobs or permissions. The launcher does not initialize existing services. Inspect ownership before permission changes.

## Model readiness

This project provides no bundled model-runtime image. The default compatible endpoint remains `ws://127.0.0.1:8108`; provision it and matching credentials beforehand. Empty TMDB/provider keys do not start external platforms.

MCP/workers use host networking. If the model runs elsewhere, use its actual reachable endpoint. The required interface is the compatible WebSocket App Server protocol with bearer authentication, not an arbitrary chat website or REST API. Without it, web/MCP can start but workers cannot normally submit/process.

Inspect model authentication, hardlink probes and heartbeats in `sh setup.sh logs`. For `token_missing`, `token_unreadable` and `token_rejected`, check file content presence, permissions and endpoint matching without printing the token. A placeholder empty file only permits other services to start.

## Network boundaries

MCP/workers use host networking; dependency network policies remain their own. Loopback API URLs require ports reachable from the host. Change one network setting at a time while troubleshooting.

- Personal LAN mode trusts private-network clients without identity authentication. Consider guest Wi-Fi, VPN users and other containers.
- MCP checks socket peers without trusting forwarded headers. Host accepts LAN IPs, localhost or configured names; browser Origin must match Host.
- Custom hostnames/proxies require exact allowed hosts, preserved Host and protected client access. Adding a hostname does not authorize public exposure.
- Do not publicly forward admin ports `18210/18211/18212` or expose them through untrusted proxies. Restrict them to trusted devices/networks.
- `48181` is BT traffic, not an admin port. Its inbound policy does not configure indexers or justify opening other ports.
- A protected client-to-LAN path is required for remote use. Tunnels may make external traffic appear local; LAN checks do not replace authentication on that path.

Downloader and Jackett admin pages bypass MCP middleware. See [security](security-review.md).

## Evidence at each stage

| Check | What it establishes / limitations |
| --- | --- |
| `/healthz` ok | MCP HTTP process only, not all dependencies |
| `sh setup.sh status` | Container/health state, not individual job success |
| `media_status` | Heartbeat and configured credentials/sites, not effective external search |
| Jackett Test + Manual Search | Site connectivity and specific title search, not torrent speed |
| `media_get_job` | Actual stage state for the identified job |
| Subtitle `content_verifications` | Recorded content checks and dialogue coverage; labels/handled counts are insufficient |
| `notifications.jsonl` | Backend notification record, not phone delivery |

A successful request or job ID means submission only. Assess download, library hardlink and subtitle completion separately.

## Updates and stop

```sh
sh setup.sh status
sh setup.sh logs
sh setup.sh stop
sh setup.sh
```

The launcher builds Media, updates the selected role and initializes selected bundled dependencies. It retains persistent directories and does not stop parent Quant/Crawler services. Run builds/tests serially on constrained hosts.

External dependencies manage their own updates. Bundled image choices use `QBITTORRENT_IMAGE` / `JACKETT_IMAGE`; back up first and explicitly select/pull a fixed version or digest. `latest` is not reproducible, and rebuilding Media does not prove all third-party components are current or vulnerability-free.

Never use `docker compose down -v` or delete `state/` to repair jobs. Logs rotate; preserve original error codes/stages and redact before sharing.

## Backup and restore

Include actual configured paths when they differ from these defaults. Write archives outside the directories being archived, into an existing private directory with sufficient capacity.

```sh
sh setup.sh stop
umask 077
tar -cpf /your/private-backup/media-state.tar .env state services
# Back up videos, seeding sources and subtitles separately; full recovery also requires data.
```

Treat `.env`, tokens, cookies/passkeys, databases and archives as private. Metadata cannot restore missing videos. Stop all writers before copying the entire SQLite state directory, including WAL. Stop other services writing the same media too.

Restore into an empty destination with proper permissions, matching code/configuration and all persistent directories. Verify paths/model access before startup. Do not overwrite running state. Directory/UID/path changes require migration checks. Rollback needs the corresponding old image/code and consistent state, not one SQLite file.

## Identity, public mode and quotas

Web roles govern web and platform MCP. Default personal LAN MCP remains unauthenticated and can access unscoped owner jobs; restrict its reachability. Unified standalone identity explicitly requires `MEDIA_MULTI_USER=true` and `MEDIA_AUTH_MODE=platform`. `setup.sh local` starts control/workers without an additional unauthenticated MCP; cloud MCP requires revocable user tokens.

Bundled admin pages bind loopback by default; use an authenticated SSH tunnel or protected admin path. Existing external services are never reconfigured automatically.

For explicit public web mode, set `MEDIA_WEB_PUBLIC=true`, `MEDIA_WEB_PUBLIC_URL=https://media.example.com`, and `MEDIA_ALLOWED_HOSTS=media.example.com`. It validates HTTPS origin/hosts and sets Secure cookies; provision TLS/domain/proxy separately. Bind raw cloud web to loopback with `MEDIA_CLOUD_WEB_BIND=127.0.0.1` when appropriate; bind MCP to a restricted proxy-reachable address. LAN HTTP testing can remain HTTP without independently enabling Secure cookies.

Trusted HTTPS proxies can be listed as exact IP/CIDRs in `MEDIA_WEB_TRUSTED_PROXIES`, e.g. `127.0.0.1/32`. Preserve Host and overwrite `X-Real-IP` with the actual client, never trust arbitrary client headers or internet-wide CIDRs. Nginx examples: `proxy_set_header Host $http_host;` and `proxy_set_header X-Real-IP $remote_addr;`. This does not globally trust all Uvicorn forwarding or change LAN socket checks. Control accepts `x-media-client-ip` only from a service-authenticated gateway; external values are overwritten/rejected.

Server quotas apply to administrators too: search 30/minute with concurrency 2; plans 10/minute with concurrency 2; new download/subtitle tasks combined 10 per 10 minutes; at most 10 nonterminal jobs/account and 100 global new tasks; token creation 5/hour and 10 active tokens. Cloud catalog and local query quota pools are separate. HTTP 429 codes include `account_rate_limited`, `account_concurrency_limited`, `account_queue_full`, `account_token_limit`. Reconcile submitted requests with the original key without consuming a new admission; never change keys to evade limits. Unknown submissions and review jobs retain occupancy. Limits do not replace disk monitoring.

See [cloud execution acceptance](history/cloud-execution-goal.md) and [historical security review](history/security-review-20261026.md).

| Symptom | Action |
| --- | --- |
| Docker/Compose unavailable | Install/start them on the server; the launcher does not install Docker |
| Build/image/OCR download failure | Check repository access and architecture; preserve caches and job state |
| MCP up, worker unready | Check endpoint, token, hardlink permissions and heartbeat; do not claim normal downloads |
| `hardlink_cross_device` / probe failure | Use one filesystem and common `/data` mount |
| `untrusted_host` | Try actual LAN IP; explicitly allow custom DNS names |
| `cross_origin_request_denied` | Use the correct same-origin entrypoint or native MCP client; retain the check |
| No sites/results | Follow [Jackett configuration](jackett.md) and exact-title search |
| Downloaded but `needs_review` | Inspect job errors; do not force identity/path/scope conflicts |
| `submission_unknown` | Observe/reconcile original job/key; never duplicate submission |
| English subtitle labeled Chinese | Content checks reject it; reprocess the existing media ID without redownloading |
| `.rejected-language` backup | Retained rejected original; obtain valid content separately; backups are not automatically deleted |
| Missing/failed subtitles | Check provider quota, source material, model and sync tools; Chinese is not always available |
| No phone push | Check full BARK_URL, connectivity and records; a record is not delivery proof |

Use `media_retry_job` only after an explicit request and resolution of the cause, for allowed processing stages. A preparation failure proven to precede submission can be searched/planned anew; this cannot bypass unknown-submission fencing.

## Model usage policy

An administrator can choose Media processing models at the bottom of Settings. Defaults are `gpt-6.1-terra` and reasoning `low`; supported models and explicit `low`/`medium` choices come from the current model service. Shared NAS SQLite stores settings and audit history.

Changes apply to the next call without restart/rebuild, including already-created identification, subtitle and analysis clients. Each in-flight call keeps its initial snapshot across transport retries. Startup probes use the same defaults; failures never automatically upgrade the model/reasoning tier. Unavailable models are rejected while preserving outcome fencing, retries and startup gates.

Ordinary users cannot edit global model settings. Admin login, CSRF and conflict detection are required. Deploying the settings feature initially requires `sh setup.sh local` and, for separate cloud web, `sh setup.sh cloud`; subsequent settings changes require no deployment.
