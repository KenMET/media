# Service and configuration names

Cloud means the remote host running the website/MCP; local means the NAS. Compose service names distinguish the two roles.

| Role | Compose service | Entrypoint | Responsibility |
| --- | --- | --- | --- |
| NAS | `local-control` | `media-local-control` | Control API, accounts/sessions, SQLite, scanning and ingestion |
| NAS | `local-worker` | `media-local-worker` | Download scheduling, identification, organization and subtitles |
| Standalone | `local-mcp` | `media-local-mcp` | Personal LAN or explicit platform MCP; not started by `setup.sh local` |
| Cloud | `cloud-web` | `media-cloud-web` | Static assets, browser gateway, search and NAS forwarding |
| Cloud | `cloud-mcp` | `media-cloud-mcp` | User-authenticated MCP |

`qbittorrent` and `jackett` are named dependencies; `init-*` initializes only selected bundled dependencies. Nonempty URLs reuse existing services.

## Configuration aliases

New nonempty names take precedence, then legacy aliases. Existing `.env` files are never overwritten.

| Purpose | Current name | Legacy fallback | Default |
| --- | --- | --- | --- |
| Cloud web bind | `MEDIA_CLOUD_WEB_BIND` | `MEDIA_GATEWAY_BIND` | `0.0.0.0` |
| Cloud web port | `MEDIA_CLOUD_WEB_PORT` | `MEDIA_GATEWAY_PORT`, `MEDIA_WEB_PORT` | `18214` |
| Cloud MCP bind | `MEDIA_CLOUD_MCP_BIND` | `MEDIA_BIND_HOST` | Existing proxy mode |
| Cloud MCP port | `MEDIA_CLOUD_MCP_PORT` | `MEDIA_MCP_PORT` | `18210` |
| Cloud FRP port | `MEDIA_CLOUD_CONTROL_PORT` | `MEDIA_CONTROL_PORT` | Split default `28213` |
| Advanced control URL | `MEDIA_CLOUD_CONTROL_URL` | `MEDIA_CONTROL_URL` | Prefer loopback mapping port |
| Cloud state | `MEDIA_CLOUD_STATE_PATH` | Unchanged | `./state-cloud` |
| Cloud image | `MEDIA_CLOUD_IMAGE` | Unchanged | `media-mcp-cloud:local` |
| NAS control bind | `MEDIA_LOCAL_CONTROL_BIND` | `MEDIA_WEB_BIND_HOST` | Template `192.168.8.1`; old unspecified local configurations use loopback |
| NAS control port | `MEDIA_LOCAL_CONTROL_PORT` | `MEDIA_WEB_PORT` | `18213` |
| NAS host media root | `MEDIA_LOCAL_DATA_DIR` | `MEDIA_DATA_DIR` | Template `/data`; old unconfigured deployments retain `./data` |
| NAS SQLite state | `MEDIA_LOCAL_STATE_PATH` | `MEDIA_STATE_PATH` | `./state` |
| NAS image | `MEDIA_LOCAL_IMAGE` | `MEDIA_IMAGE` | `media-mcp:local` |
| Standalone MCP port | `MEDIA_LOCAL_MCP_PORT` | `MEDIA_MCP_PORT` | `18210` |
| Standalone MCP bind | `MEDIA_LOCAL_MCP_BIND` | Compose `MEDIA_LAN_BIND`, direct entrypoint `MEDIA_BIND_HOST` | LAN default `0.0.0.0` |

The template groups cloud web/MCP/FRP/search and NAS control/files/SQLite/downloader/model/subtitles/notifications. In-container `MEDIA_DB_PATH` and `MEDIA_STATE_DIR` differ from host mount settings. `MEDIA_DOWNLOAD_ROOT` and `MEDIA_LIBRARY_ROOT` remain NAS runtime roots.

Shared HTTP policy retains the semantics of `MEDIA_WEB_MODE`, `MEDIA_WEB_PUBLIC`, `MEDIA_ALLOWED_HOSTS` and `MEDIA_PROXY_IPS`. Names do not change accounts, credentials or task identities.

Legacy commands `media-web`, `media-gateway`, `media-worker`, `media-mcp` remain aliases. New deployments use role names above. MCP protocol identity remains `media-mcp`; HTTP status identities are `media-local-control` and `media-cloud-web`.

## Updating existing deployments

```sh
# On the NAS: update local-control and local-worker.
sh setup.sh local
# On cloud: update cloud-web and cloud-mcp.
sh setup.sh cloud
```

After building, the launcher identifies legacy `web`/`worker`/`mcp` application containers by Compose labels and working directory, removes those old app containers and starts the renamed services. It never uses `down -v`, removes volumes or handles containers from another working directory.

Compose project names remain `media-standalone` and `media-cloud` to preserve dependency ownership. NAS application names become, for example, `media-standalone-local-control-1` and `media-standalone-local-worker-1`. Renaming applications does not rebuild existing downloader/Jackett services.

Private variables need not be renamed immediately. Preserve values, especially media/state roots; never replace real `/data` with project-local `./data`. Restart alone does not apply Compose/environment changes. Continue using role-specific status/logs commands. Read the bootstrap token through NAS `local-control`; the filename, administrator and credentials remain unchanged.
