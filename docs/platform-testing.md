# Same-host platform testing

The original test stage placed local/cloud on mainland host `192.168.8.1`, without Singapore, domains, FRP or TLS. Public deployment remained a later step. See [live acceptance](history/live-acceptance.md) for real discovery, localized/original public search, download and bilingual UI evidence. SIMKL day/week lists require no key; TMDB remains the search/detail provider. Web language is selected on the login page/top bar without new environment settings.

## Startup

`setup.sh` is the sole Docker entrypoint. Separate deployments use separate directories/private `.env`. An isolated same-directory test can explicitly set:

```dotenv
MEDIA_LOCAL_CONTROL_PORT=18213
MEDIA_CLOUD_WEB_PORT=18214
MEDIA_CLOUD_CONTROL_PORT=18213
MEDIA_WEB_PUBLIC=false
MEDIA_WEB_MODE=lan
MEDIA_WEB_BIND_HOST=0.0.0.0
MEDIA_SERVICE_PAIRING=false
MEDIA_LOCAL_DATA_DIR=./data-test
MEDIA_LOCAL_STATE_PATH=./state-test
MEDIA_CLOUD_STATE_PATH=./state-cloud-test
```

Both roles read the same private service credential file without initial pairing. Add downloader/model/TMDB configuration, then run:

```sh
sh setup.sh local
sh setup.sh cloud
```

| Role | Service | Default entry/state |
| --- | --- | --- |
| Local | `local-control`, `local-worker` | Control 18213; `state/media.sqlite3` |
| Local | Downloader | Existing URL or bundled 18211 |
| Cloud | `cloud-web` | `http://192.168.8.1:18214` |
| Cloud | `cloud-mcp` | `http://192.168.8.1:18210/mcp`, user token |
| Cloud | Jackett | Existing URL or bundled 18212 |
| Cloud | Catalog cache | `state-cloud/catalog.sqlite3` |

Unqualified setup starts the legacy standalone combination. Do not start it on ports occupied by the split test. Its default LAN MCP is unauthenticated while web still requires accounts.

Cloud owns search/torrent retrieval. Same-host control port 18213 bypasses FRP; real split mode uses the mapping port, default 28213. Legacy `MEDIA_CATALOG_URL`/`MEDIA_CONTROL_URL` remain compatible; advanced URL is `MEDIA_CLOUD_CONTROL_URL`. Changing NAS ports also requires updating the test cloud port or real FRPC target.

## Isolation

Use newly created disposable state and media mounts, never production media. All paths must be on the NAS's local Linux disk; editing through SMB does not make SMB appropriate for SQLite. Download/library share a filesystem and identical container paths.

Use a separate test downloader/category/directory for write acceptance. Do not stop/rebuild old `media-monitor`, Quant, Crawler or unrelated containers, or adopt their jobs.

Default `state/control-token` is generated privately when needed and mounted read-only by both roles. It is not a login password. Prepare a custom `MEDIA_CONTROL_TOKEN_FILE` beforehand; never expose it. Role state directories do not change its default location.

## Accounts and MCP

1. Local control creates `web-bootstrap-token` in local state, or uses explicit bootstrap token/file configuration.
2. Open cloud port 18214, privately enter the token, and create the initial administrator. There is no default password and initialization works once.
3. Create users, search, submit jobs and inspect separate download/ingestion/subtitle state.
4. Create a personal MCP token in account settings: shown once, valid 30 days. Configure it as bearer for cloud `/mcp`. Disable/password change/revocation invalidates access.
5. Explicit standalone `MEDIA_AUTH_MODE=platform` uses the same authority. Default owner LAN mode remains; historical unowned jobs are administrator-only.

Web/MCP share local job state, identity, idempotency and file safety. Browsers never receive private release URLs/API keys or call the downloader directly.

## Evidence and feature boundaries

- Discovery supports TMDB day/week trends, movie/TV and explicit missing-key status. SIMKL is independently attributed.
- Douban has a separate adapter/cache/backoff. Developer and NAS requests returned HTTP 418 on 2026-10-25; no successful live data integration was established. It was explicitly excluded from first-release acceptance. Never relabel TMDB data as Douban. `MEDIA_DOUBAN_ENDPOINT` can name an authorized compatible subjects JSON source.
- Administrators/users, enable/disable, passwords, tokens, per-task/media read/manage grants and audit are supported. Grants do not copy files or create per-user filesystems.
- Downloader completion is not library/subtitle completion. Speeds/ETAs have observation times; disconnection cannot present them as fresh. Compatible model readiness gates processing.
- NAS alone owns accounts/sessions/permissions/jobs; cloud has cache, not a database replica. Offline NAS prevents cloud login/commands; accepted work may continue when its dependencies remain reachable.
- At the original stage, playback, transcoding, deletion, registration, Douban watchlist sync and whole-downloader adoption were excluded. Later explicit deletion features are described in current collection/task guidance.

## Operations and verification

```sh
sh setup.sh local status
sh setup.sh cloud status
sh setup.sh local logs
sh setup.sh cloud logs
sh setup.sh cloud stop
sh setup.sh local stop
PYTHONPATH=src nice -n 15 .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Stop affects its role/selected bundled dependencies, not configured external services. Switching dependency modes does not retire old containers automatically.

`tests/manual/preview_platform.py` uses fictional providers and temporary SQLite without a real downloader. Collection mode adds a disposable maintenance worker. It is not a production entrypoint; fixture accounts are not production credentials. See [tests](../tests/README.md).

Before backups, stop both roles and preserve matching code, the entire local state including WAL/locks/recovery, private configuration and required media. New tables do not automatically grant historical jobs to ordinary users. Rollback requires consistent matching state, not one SQLite file.

For actual Singapore deployment, reuse protected FRP and HTTPS proxy with the [split template](split-deployment.md). Do not forward unauthenticated standalone MCP. Same-host tests use LAN HTTP explicitly; new cloud defaults to `MEDIA_CLOUD_WEB_BIND=0.0.0.0` behind authenticated HTTPS proxy. Explicit old `MEDIA_WEB_PUBLIC=false` retains LAN behavior.
