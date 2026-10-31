# Adopting existing videos and subtitles

Administrators use **Library → Scan and import → Scan existing resources**, review roots/status/skipped entries, then **Confirm index import**. SQLite retains the index across refresh. Ordinary users gain neither whole-library access nor arbitrary disk paths.

Scanning never moves, renames or writes media, and never calls the downloader, TMDB or model. Confirmation writes SQLite and registers unique verified source/library hardlink pairs in `media_link`. Unknown TMDB identity remains pending identification without subtitle controls. Import creates no acquisition jobs and adopts no old qBittorrent tasks.

## Mounts

Compose mounts the host `MEDIA_LOCAL_DATA_DIR` at `/data`. `./data` means the project's data directory, not host `/data`; use `MEDIA_LOCAL_DATA_DIR=/data` if that is the actual host root. Apply configuration through `sh setup.sh local`.

Local control scans container-visible roots:

```dotenv
MEDIA_DOWNLOAD_ROOT=/data/downloads
MEDIA_LIBRARY_ROOT=/data/media_hub
```

Both roots must exist, be readable and not contain each other. Mount one common parent for hardlinks. Keep SQLite on local state storage, not the media network share. Cloud does not scan its own filesystem.

The feature spans local control and cloud assets; update each with `sh setup.sh local` / `sh setup.sh cloud`. Before switching a test deployment to real paths/state, follow [production cutover](production-cutover-plan.md), retain backups and stop competing writers. The scan page does not change deployment configuration.

## Status meanings

| Status | Meaning |
| --- | --- |
| Verified hardlink | Unique source/library pair with matching device and inode |
| Existing mapping | Both actual file identities match the saved relation |
| Unorganized | Downloaded video has no library hardlink; save its index for later identification |
| Library-only | No download relation; retain file/index without fabricating a source |
| Missing source / target | One mapped endpoint is absent; preserve the other without automatic linking |
| Both missing | Historical relation retained; an index cannot restore bytes |
| Conflicting / ambiguous relation | Endpoints differ or candidates are nonunique; do not overwrite mapping |
| Outside configured roots | Do not read outside paths or mark their historical mappings missing |
| Mapping includes skipped files | Symlinks/unsupported types must not be mistaken for missing scanned files |
| Matched / unmatched subtitle | Associate by full same-directory video prefix, longest match first; infer no language/translation/quality |

`media_inventory` stores disk entries and `media_mcp_record` kind `inventory_scan` stores previews. Independent files/subtitles need no fabricated job or source-target relation. Indexed sidecars appear as discovered/unverified; existing subtitle processing records take precedence.

Hardlinks have no primary/secondary direction. Removing a source path leaves video bytes available through another remaining hardlink. Scans do not follow links outside configured roots.

## Confirmation and recovery

An empty scan reports zero entries and the host media directory, hides confirmation, and is rejected by the backend. It never replaces existing inventory with an empty result. Container paths alone cannot distinguish host `./data` from `/data`.

Nonempty import reports actual indexed/new mapping counts and saves a receipt. Resource lists use actual database totals/timestamps; administrators can see imported independent files even without mappings.

- Previews expire after 30 minutes. Rescan fingerprints, roots and mappings before import; changed evidence requires a new preview.
- One mutation lock and SQLite transaction fence import. Lost lock/write failure rolls back; repeated confirmation is idempotent.
- Maximum 20,000 directory entries and a 25-second scan loop. Limits/read errors never produce an importable partial result. Narrow roots and retry. A slow syscall can exceed loop timing; HTTP timeout never imports automatically.
- Skip symlinks, broken links and special files. Supported video/subtitle types are `VIDEO`/`SUBTITLE` in `storage/inventory.py`. Scans do not inspect embedded subtitles, hash entire videos or identify TMDB titles.
- The latest complete import is a snapshot, not a filesystem watcher. Retain earlier scans/index records; rescan after changes.
- This is not MySQL migration. Legacy metadata/subtitle history still needs the migration process.

## Disposable acceptance

`tests/test_inventory.py` uses temporary SQLite/download/library roots. The browser preview uses loopback 18293, fictional files/accounts/providers and no downloader or normal worker.

```sh
PYTHONPATH=src nice -n 15 python3 tests/manual/preview_platform.py
# In another terminal, using installed Playwright and Chromium:
PLAYWRIGHT_MODULE=/path/to/playwright-core CHROME_EXECUTABLE=/path/to/chrome \
  nice -n 15 node tests/manual/acceptance_inventory_browser.cjs
```

Artifacts default to `/tmp/media-ui-acceptance/`, overridable by `MEDIA_BROWSER_ARTIFACTS`. For empty scans set preview `MEDIA_PREVIEW_EMPTY=true` and browser `MEDIA_BROWSER_EMPTY=true`. For independent files without links, use `MEDIA_PREVIEW_NO_LINKS=true` / `MEDIA_BROWSER_NO_LINKS=true` and verify persistence after refresh. These switches are only for disposable previews.
