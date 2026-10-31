# Background task and core workflow acceptance: 2026-10-29

## Original incident

After lockscreen timeout, read-only observation showed task `e9895708d1cd4ff199b4ca409c724864` still running on NAS: 221/816, healthy lease/heartbeat, later 393. Collapsed progress, polling termination after read errors, no foreground recovery and conflated read/submission timeout copy made work appear lost.

Before control deployment, the original task reached `completed_with_warnings`, 816/816 results: 60 identities saved, eight extras, 14 ready subtitles, 22 fully complete and 794 unresolved (380 unreliable matches, 38 unready subtitles, 12 direct rate limits, 364 retained after AI became unavailable). Traversal completion was not falsely reported as full success; original results were not rewritten.

## Changes

[Task experience](../task-experience.md) describes discovery, automatic release search/default season, single explicit download action, dedicated maintenance progress/background summaries and existing automatic subtitle processing. Advanced options remain collapsed; actual stages/counts are separate.

Lightweight status SQL excludes frozen snapshots and filesystem/lock work; details paginate every success/issue. Old worker substeps remain readable; terminal tasks no longer claim active research. Foreground/network/page restoration triggers reads, preserving stale observations with backoff. Lost receipts reconcile per-user original keys without mutation replay. Request ownership prevents concurrent initialization/poll/results from clearing completed details; session changes clear caches and permission checks remain.

## Disposable results

Python 213/frontend 12 passed, including reads while mutation lock held, no scanning, substep/lease evidence, >50 issue pagination, read-only idempotency lookup, owner isolation, old-worker reasons, redaction and control-only deployment. Real HTTP covered gateway/static task modules. Browser suites: task experience, automatic flow, collections, compact extras, advanced AI.

Core fixture task had 45 files: 44 identities, 30 new links, six extras, 38 ready subtitles and one unknown. All results paginated. Hidden/offline restoration, polling timeout, refresh/reopen and lost download/maintenance receipts did not duplicate submission. Stages/reasons/confidence, discovery→release search, single download/default season and search restoration passed. Bilingual 320–1440px had no overflow/JS errors.

Artifacts `/tmp/media-task-experience-acceptance/` across five flow directories, core `task_experience/`. Fictional providers/AI/subtitles used real HTTP/SQLite/queues/hardlinks and browser reconnect, not production downloader/subtitle quality or real iOS lockscreen. No new live AI tests or model-policy changes occurred.

## Deployment boundaries

`sh setup.sh local control` updated only NAS control after private backup; setup retained mode 100755. Worker ID/start time and dependencies were unchanged. Healthy services served task assets through HTTP. Original-task local read took about 0.015s excluding cloud networking; first page returned 25 issues with continuation. Observation did not change revision/queue count.

Final installed API/service/views/assets matched source; app SHA256 `4a8732c155c8621d9d99630a6bdb9ac0b7904e9d312801fe4bb573d9c46d4474`. Row/column backup comparison retained 807 mappings, 2879 inventory, 52 identities, 60 classifications and 215 `library_%` rows. No production acceptance/replay.

Evidence: `/tmp/media-task-full-tests.log`, `/tmp/media-task-node-final-tests.log`, `/tmp/media-task-browser-suite.log`, `/tmp/media-task-installed-final-observation.log`, `/tmp/media-task-data-integrity.log`.

Cloud access/automatic deployment were unavailable. Pull and `sh setup.sh cloud` remained necessary for public task/reconnect/UI changes. NAS workers still handled classification/linking/subtitles. Private state/config/backups/credentials and original standalone/manual line-ending changes were excluded.
