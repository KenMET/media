# Discovery, search, tasks, deletion and storage goal

## Delivered behavior

- Preserve day/week trends and add TMDB movie/TV all-time `top_rated`.
- Name-only official multi search mixes movie/TV relevance, excludes people and retains provider order. Explicit legacy type/year parameters remain compatible.
- Merge download history beneath active jobs, sorting active/terminal before pagination. Both task tabs follow headings; maintenance retains its own list.
- Download deletion verifies permission/CSRF/preview/confirmation and exact infohash/category/job tags, removing only the owned qBittorrent job with files retained. Retry gains no deletion parameter.
- Maintenance deletion cancels future work/revokes exact leases; stale callbacks cannot commit or revive deleted work. Retain unknown model IDs/evidence/audit without claiming remote turns stopped.
- Selected media deletion covers source/library/subtitle/attributable companion files and safe directories, cleaning related mappings/inventory/identity/classification/unreferenced display records. Independent inventory uses verified fingerprints. Shared directories/subtitles, unknown videos and new files remain.
- Non-overwriting same-directory quarantine hardlinks fence deletion; remove originals only after identity checks, clean records before releasing quarantine, resume the same interrupted plan, reject replacements/expired previews. Mount/conflict/unknown ownership/active processing fail explicitly.
- Admin capacity reports actual download/library total/free without double-counting devices.

## Previous delivery verified

Actual public `library.js` already contained ID-based artwork, removed global force, and pending single-work actions; CSS contained >=1200px three columns. This proved the user's previous rebuild, not deployment of these new features. Global all remained rejected and poster gaps caused no AI.

## Review and validation

Fixed deletion previews invalidated by live progress, mixed object-ID sorting, shared-subtitle ownership, post-quarantine classification recovery, deleted-job revival by old worker errors, category-root cleanup and inventory/download recovery scope. Queue cancellation uses a SQLite write transaction and existing mutation locks; cancel only exact associated work and never force active file writes.

No new dependency/downloader/table/migration/retry deletion capabilities. Required directories retained. Unfinished FIFO and existing documentation/manual edits remained excluded.

Before the user requested reduced verification, NAS disposable release passed 137 related tests and final 27 deletion tests, serial nice 15. Jackett tests initially inherited execution-only and were rerun with test-process fake provider settings without weakening deployment. HTTP fixtures verified exact hash and `deleteFiles=false`, retaining unrelated jobs/payload. Twelve frontend tests and disposable browser covered top rated, mixed search, heading/tab order, merged history, deletion preview/cancel/confirm, capacity, 3/2/1/1 columns and bilingual titles. Only marked disposable files were removed, never production media/qBittorrent. Later work was restricted to final review/deployment checks.

Official references: [TMDB top rated](https://developer.themoviedb.org/reference/movie-top-rated-list), [multi search](https://developer.themoviedb.org/reference/search-multi), [qBittorrent delete](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)#delete-torrents).

## Deployment

Commit `126f2a1` pushed and verified. At idle checkpoint, `sh setup.sh local` rebuilt healthy control/workers, zero restarts, installed hash parity, read-only downloader/version and initialization checks, actual capacity reads. Other container IDs/images/start times and preexisting dirty file digests stayed unchanged. Used committed `runtime/state.py`, then restored unfinished FIFO.

Cloud remained pending:

```sh
git pull --ff-only
sh setup.sh cloud
```

NAS needed no repeated rebuild. Production deletion acceptance was not run.
