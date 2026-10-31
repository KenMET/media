# Legacy standalone deployment

For a trusted personal LAN, with unauthenticated MCP by default. For cloud/NAS separation, use [split deployment](split-deployment.md).

## Prerequisites

- Linux or OpenWrt with Docker and Compose, and images matching the CPU architecture. Run deployment commands on the server; editing files on Windows does not deploy them.
- Local storage for downloading, seeding and subtitles. Downloads and the library must share a filesystem. Keep SQLite `state/` off SMB/NFS. Editing source over a share does not change the server's local runtime paths.
- A TMDB API key for title, year and episode metadata.
- An existing compatible **Codex App Server WebSocket endpoint and bearer token**, defaulting to `ws://127.0.0.1:8108`. This project does not install, authenticate or start the model service. Its token is neither an MCP login token nor a direct OpenAI API key.
- An MCP client that can reach the LAN host and supports HTTP MCP and the required write tools.

```sh
docker version
docker compose version
```

The launcher also supports legacy `docker-compose`. Configuration and networking details are in [operations](deployment.md).

## Quick start

### 1. Configure

On the server, enter this directory (`cd media` from the parent repository):

```sh
cp -n .env.example .env
chmod 600 .env
mkdir -p state
```

Preserve an existing `.env`. Set at least:

```dotenv
TMDB_API_KEY=your-tmdb-api-key
CODEX_APP_SERVER_URL=ws://127.0.0.1:8108
CODEX_TOKEN_FILE=./state/codex-token
```

Empty `QBITTORRENT_URL` and `JACKETT_URL` start bundled services on default ports 18211 and 18212; nonempty values reuse existing services. Mixed configurations work. Keep credentials in private `.env`. Reusing Jackett also requires its configuration directory mounted read-only; see the deployment guide.

Place the existing token matching the model endpoint in the host file named by `CODEX_TOKEN_FILE`. Copy it with a local editor or existing private file; never reveal it in chat, command arguments or logs.

```sh
chmod 600 state/codex-token
```

For another path, set permissions on that file. It must contain raw bearer token text, not JSON, a filename or a `Bearer ` header. MCP/workers receive it as a read-only mount.

Optional `BARK_URL` is a complete private push endpoint. Without it, notifications are logged locally. Optional subtitle provider keys enable their sources; existing/embedded subtitles and translation may still work without them, but Chinese subtitles are not guaranteed for every work.

### 2. Start

```sh
sh setup.sh
sh setup.sh status
```

Initial builds download images, dependencies and OCR tools. MCP availability does not prove worker readiness: workers wait for model authentication and hardlink probes before submission and processing.

| Entrypoint | Default address |
| --- | --- |
| Media MCP | `http://host-LAN-IP:18210/mcp` |
| qBittorrent web | `http://host-LAN-IP:18211` |
| Jackett web | `http://host-LAN-IP:18212` |

Replace `host-LAN-IP` with the actual server address, not the browser computer's localhost. `MEDIA_LOCAL_MCP_BIND=0.0.0.0` is a listening address, not a destination. Restrict access with the firewall.

### 3. Configure Jackett

Open port `18212`, choose **Add indexer**, and add authorized sources supporting the required media categories. Configure each account/cookie, save, run **Test**, then use **Manual Search** with an exact title and original title.

A Test returning recent releases does not prove title search works. Bundled Jackett initially has no sites. Existing Jackett requires its configuration mount; the key can be read from it or set in `.env`. See [Jackett](jackett.md) for proxy and challenge troubleshooting.

### 4. Connect and verify MCP

Add the `/mcp` HTTP address to the client, using no authentication by default. After initial connection or updates, ask:

> Call media_status to check readiness, then media_get_workflow to read the workflow.

Expected readiness includes `worker_ready=true`, `tmdb_configured=true`, `indexer_configured=true` and `configured_sites>0`. These do not prove external searches, subtitle processing or phone delivery.

Cloud clients cannot directly reach a private LAN IP. Provide a protected network path; this project does not create a tunnel. Never expose the unauthenticated port publicly. Add custom hostnames to `MEDIA_ALLOWED_HOSTS` as described in operations.

### 5. Use the service

Search without downloading:

> Find releases for Interstellar (2014), list the options, and do not download yet.

Acquire and process:

> Download Interstellar (2014), select an appropriate release, normalize its library name, create hardlinks, process Chinese subtitles and notify me.

Limit episode scope:

> Download season 2, episodes 1–3 of Example Show at 1080p and process Chinese subtitles.

Check progress:

> Check the latest job and report download, library and subtitle status separately.

Reprocess existing subtitles:

> Find Interstellar in the library, use its returned media_id with media_run_subtitles, and verify Chinese subtitles without downloading the movie again.

Do not reuse IDs from another installation. Existing-version conflicts, ambiguous identities and critical errors require review. Only explicit download requests authorize submission. A returned `job_id` means background work can continue after chat closes, not that it has completed.

## Persistent files

```text
media/
  .env                         Private deployment configuration
  state/media.sqlite3          Jobs, mappings, subtitles and recovery (with WAL/SHM)
  state/codex-token            Model credentials
  state/notifications.jsonl    Local notification records
  services/qbittorrent/        Downloader configuration and recovery state
  services/jackett/            Indexers, login state and internal API key
  data/downloads/              Original downloads and seeding files
  data/media_hub/              Canonical video hardlinks and subtitles
```

Unrelated downloader tasks are never adopted automatically. Hardlinks share video bytes; editing one in place changes the seeding source too. Subtitles are written separately.

Subtitle processing first reuses/extracts Chinese material, then searches online, synchronizes, and uses OCR/translation where appropriate. Dialogue coverage checks verify content; labels and filenames are insufficient. Missing source material, quota exhaustion or translation failure can require review. Historical completed jobs are not automatically rechecked. Reprocessing does not require downloading the video again.

## Updates and troubleshooting

```sh
sh setup.sh
sh setup.sh status
sh setup.sh logs
sh setup.sh stop
```

The launcher rebuilds Media, updates MCP/workers and starts bundled dependencies without configured URLs. It preserves state and does not initialize external dependencies. Restart alone does not load new code. Rebuilding Media does not guarantee third-party images were updated. Reread the workflow after updates.

Stopping pauses monitoring/processing and selected bundled dependencies; external downloads may continue. Persistent state is retained. Redact logs before sharing. Never change the request key to bypass `submission_unknown`.

- [Operations and backup](deployment.md) · [Jackett](jackett.md) · [Security](security-review.md)
- [Initial 0.3 acceptance](history/platform-acceptance.md) · [Live acceptance](history/live-acceptance.md)
- [Local functional acceptance](history/local-functional-acceptance-20261026.md)
- [Production cutover](production-cutover-plan.md) · [Workflow](../skills/media-acquire/SKILL.md)
- [Migration](migration.md) · [Historical acceptance](acceptance.md)
