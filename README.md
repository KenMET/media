# Media

Search for media, compare releases and submit downloads through the website or MCP. Background workers verify files, normalize names, create library hardlinks and process subtitles. The project runs independently of the parent repository's `apps` package.

## Service responsibilities

| Cloud | NAS / local |
| --- | --- |
| Website, MCP, TMDB/SIMKL discovery and search, Jackett, torrent retrieval | Control API, downloader, workers, AI processing, media and task database |

Cloud connects to the NAS through an existing FRP mapping on the cloud host. The NAS needs no cloud address. Existing services continue to manage reverse proxies, certificates and FRP.

## Split deployment

Requirements: Linux, Docker and Compose, local storage, and a compatible model service with matching credential files.

1. **NAS:** copy [.env.example](.env.example) to `.env`, fill the local/NAS groups, check the control port, downloader, media directory, model endpoint and credential file, then run `sh setup.sh local`.
2. **FRP:** for example, forward NAS `192.168.8.1:18213` to cloud loopback `127.0.0.1:28213`. Match FRPC `localIP` to `MEDIA_LOCAL_CONTROL_BIND`; use host networking on the NAS.
3. **Cloud:** copy [.env.example](.env.example) to that host's `.env`, fill the cloud groups, check web/MCP/mapping ports, TMDB key and existing Jackett address, then run `sh setup.sh cloud`.
4. **Reverse proxy:** route the website to local port `18214` and optionally `/mcp` to `18210`. Create a web administrator account. Cloud MCP requires a revocable user token.

Preserve existing `.env` files. Initial internal credentials pair automatically; manual tokens and duplicate domain configuration are unnecessary. Defaults and Docker proxy conditions are in the [split deployment guide](docs/split-deployment.md). For testing both roles on one host, see [local testing](docs/platform-testing.md).

A nonempty qBittorrent/Jackett URL reuses that service; an empty URL starts its bundled container on the owning host. Cloud Jackett persists configuration and downloads at `/root/container_cache/jackett/config` and `downloads`.

Configure `TMDB_API_KEY` on cloud. Optional OpenSubtitles, SubDL and ASSRT keys belong on the NAS; empty keys skip those providers. The website does not edit deployment credentials.

## Data and safety

- `downloads` and `media_hub` under `MEDIA_LOCAL_DATA_DIR` contain source files and library hardlinks. Downloads and hardlinks must share a filesystem and identical container paths in the downloader and worker.
- NAS accounts, tasks and recovery records default to `./state`; cloud cache and search snapshots default to `./state-cloud`. Rebuilds preserve bind mounts. Retain the original state when moving the deployment directory.
- Never adopt unrelated downloader tasks. Reconcile `submission_unknown` against the original job and key; never resubmit under a new key. Retry parameters do not grant deletion capabilities.
- Administrators can preview and index existing videos, hardlinks and sidecar subtitles through Library → Scan and import. Unorganized media and missing state can be indexed without changing source files. See [existing media](docs/existing-media.md).
- Legacy MySQL migration and service cutover follow the [production cutover plan](docs/production-cutover-plan.md); startup does not import them automatically. Disposable acceptance state is not production state.
- Keep private `.env`, credentials and runtime directories out of Git. [Standalone mode](docs/standalone.md) remains available for trusted personal LAN use; do not expose its unauthenticated endpoint publicly.

See [service naming](docs/service-names.md): NAS uses `local-control` / `local-worker`; the website uses `cloud-web`.

The [collection library](docs/collection-library.md) groups posters by work, with seasons, episodes and versions in each detail page. Automatic organization identifies, saves, repairs links and checks subtitles; advanced controls retain manual maintenance. Rule checks, duration probes and AI fallback run on NAS `local-worker`; see [identification](docs/library-ai-identification.md).

Discovery, search, acquisition, automatic subtitles, progress and reconnect behavior are described in [task experience](docs/task-experience.md). Model session recovery, quota waiting and archival are covered by [session recovery](docs/session-recovery.md).

## Routine commands

```sh
sh setup.sh local status
sh setup.sh local logs
sh setup.sh local stop
sh setup.sh cloud status
sh setup.sh cloud logs
sh setup.sh cloud stop
```

After code updates, rerun the appropriate `sh setup.sh local` or `sh setup.sh cloud`. Restarting an old container does not load new code. `setup.sh` is the sole supported deployment entrypoint.

Local build files are `compose.local.yml` and `Dockerfile.local`; cloud uses `compose.cloud.yml` and `Dockerfile.cloud`. The unqualified legacy standalone entrypoint uses the local files.

## Layout and documentation

```text
src/media_mcp/     Runtime source and web assets
tests/            Automated regression tests
tests/manual/     Disposable manual acceptance tools
docs/             Current deployment, usage, migration and safety guidance
docs/history/     Historical reports and extracted records
skills/           MCP workflows
```

Project-authored documentation, code comments and non-web messages use English. The website supports English and Chinese. Media titles, subtitle content and multilingual parsing data retain their original language; see the [language policy](docs/language-policy.md).

- [Deployment and operations](docs/deployment.md) · [Jackett configuration](docs/jackett.md)
- [Tests](tests/README.md) · [Historical acceptance index](docs/acceptance.md)
- [Safety boundaries](docs/security-review.md) · [Migration boundaries](docs/migration.md)
- [AI workflow](skills/media-acquire/SKILL.md)
