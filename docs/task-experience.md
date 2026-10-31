# Simple actions with complete task feedback

Search controls stay on the dedicated search page. The shared header contains navigation/account controls; mobile height is 64px. Derivable inputs use defaults, advanced tools remain collapsed, and backend state/results stay visible.

| Workflow | Default behavior | User action | Feedback |
| --- | --- | --- | --- |
| Discovery | Day/week trends and all-time TMDB top rated | Select a work; optionally switch type/source | Poster/title/year/rating/source/update time |
| Release search | Name-only input; mixed movie/TV relevance; automatic releases after title selection; first regular TV season by default | Confirm identity and optionally season | Release/site/size/seeders/resolution and partial-search warning |
| Acquisition | A release download action creates persistent processing without duplicate confirmation | Select release | Open job details with queue/download/speed/ingestion/subtitle stages |
| Organization | Pending identification, mapping problems and unready subtitles across all pages | Start once; leaving is safe | Dedicated task link, file/work progress, probe/research/save/link/subtitle substeps and results |
| Subtitles | Existing engine used automatically by acquisition/organization, preserving valid results | Advanced review only when needed | Ready/missing/failed/review counts and redacted reasons; discovery is not verification |

Do not pick an arbitrary first identity for ambiguous titles. Preserve unknown source files. Explain low confidence/conflicts/external failures per item without blocking independent work. Automation cannot guarantee external service success.

## Routes and reconnection

Tasks include downloads, organization and subtitles. Download history appears beneath active downloads; the library exposes organization history. Other pages show recent/active summaries linking to detail. Download routes use `#jobs/<id>` and maintenance uses `#tasks/<id>`; refresh/back/forward preserve identity, with restorable search/title routes.

Submission opens progress immediately. SQLite and independent workers persist work without a connected browser. Read failures retain last observations with explicit stale state and backoff; foreground/network/page restoration triggers immediate reads. A single timeout neither cancels the task nor ends monitoring.

Lockscreen/disconnect can separate submission from its receipt. Persist per-user request identity and reconcile through read-only queries instead of automatic resubmission. Explicit retries keep the original key. A new tab without session verification must log in before reopening the same task URL.

All file results paginate, with all/unprocessed filters rather than only the first 50 issues. Expand reasons, confidence, source/original target/current mapping/subtitle records. Distinguish historical snapshots from current records without implying a fresh filesystem check. Redact credentials and URL queries.

## Lightweight reads

Owner-scoped `library_tasks`, `library_task_status` and `library_task_details` do not scan files, probe videos or acquire mutation locks. SQL removes full file snapshots/results before transport; details paginate separately. Old worker tasks expose probe/research progress, leases and historical reasons without rewriting/migrating the task.

`library_auto_status` and `download_submission_status` reconcile the current user's original request without creating work. Reconnection retries reads only. Fingerprints, permissions, leases, unknown outcomes, hardlink recovery and subtitle publication remain fenced.

## Deployment

Cloud runs the website; NAS executes tasks. Update cloud through `sh setup.sh cloud`. For control-only API changes:

```sh
sh setup.sh local control
```

This rebuilds/recreates `local-control` while retaining workers/dependencies, avoiding interruption of active identification. Worker algorithm updates require `sh setup.sh local` after a safe checkpoint. `setup.sh` retains Git mode 100755.

## Disposable acceptance

```sh
PYTHONPATH=src MEDIA_PREVIEW_EMPTY=true MEDIA_PREVIEW_COLLECTIONS=true \
  MEDIA_PREVIEW_EXTRAS=true MEDIA_PREVIEW_ANALYSIS=true MEDIA_PREVIEW_MANY_MOVIES=30 \
  MEDIA_PREVIEW_ANALYSIS_DELAY_SECONDS=1.5 MEDIA_PREVIEW_MANIFEST=/tmp/media-task-preview.json \
  nice -n 15 python3 tests/manual/preview_platform.py
# Another terminal, targeting only the marked disposable preview:
MEDIA_PREVIEW_MANIFEST=/tmp/media-task-preview.json \
  PLAYWRIGHT_MODULE=/path/to/playwright-core CHROME_EXECUTABLE=/path/to/chrome \
  nice -n 15 node tests/manual/acceptance_task_experience_browser.cjs
```

Fictional media/providers/AI/subtitles exercise actual HTTP, SQLite, persistent queues, hardlinks and browser reconnect. This does not establish external source/subtitle quality or real iOS lockscreen acceptance.

## Deletion and capacity

Both task pages put headings before tabs. Server sorting places active downloads first before pagination; completed, failed and cancelled history remains below.

Explicit download deletion previews/confirms removal of precisely owned qBittorrent jobs while retaining files. Maintenance deletion cancels future work/revokes leases; late results cannot commit, and active writes must reach a mutation checkpoint. Deleted task records retain audit/idempotency and unknown-model evidence but leave lists/processing. Deletion cannot claim a remote model call stopped. After timeout, retain the window and reconcile/resume the same plan.

Admin storage reports total/used/free bytes for download/library filesystems. Do not add capacity twice when both roots share a device. An unavailable mount reports unavailable rather than another directory's space. Capacity data is administrator-only.

Deleted tasks retain audit but consume no pending admission. Account/global limits remain 10/100 actual pending tasks; unknown download submissions continue to occupy slots.
