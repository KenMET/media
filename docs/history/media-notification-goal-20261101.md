# Media notification aggregation and season-pack recovery: 2026-11-01

Implementation and isolated validation completed; deployment evidence is added after runtime acceptance.

## Diagnosis

Live state showed one season pack with fourteen requested episodes. Only episode one was linked; thirteen records failed source/destination episode validation. Validation searched the complete source path and matched the pack directory's first episode before the actual filename. The ingestion job retried four/five times, each attempt pushing an ingestion message. Retaining episode one's existing hardlink was reported as a relink, which queued the already-completed subtitle phase again; that phase sent a second push.

## Change and self-review

Filename episode evidence now wins over directory coverage; genuine source/destination mismatch and single-episode-parent fallback remain checked. Retained preferred hardlinks return the existing/no-op outcome across restore and classification paths. Supervised ingest/subtitle workers disable low-level notifications. The existing supervisor reconciles completed acquisition/library rounds into stable per-work/season or movie summary records. Season child jobs share a parent/run barrier; explicit reviewed processing retries use a new notification round without changing download identity. Unique preferred media and indexed ready subtitles, including embedded tracks, determine counts.

The review reused SQLite Records, existing digest functions, locks, preferred publication and subtitle status metadata, without new dependencies or another processing scheduler. It removed obsolete stage-specific formatting and repeated metadata lookups. Existing urgent quota/authentication recovery alerts remain distinct. Send claims are durable; uncertain delivery is fenced rather than replayed. Historical completed tasks are not backfilled. Unrelated unfinished FIFO code/tests/documents and private connection files remain excluded.

## Validation

Serial nice-15 regression from exported staged source with the committed scheduler: 391 tests, OK with one skipped. The expanded focused suite passed fourteen tests, including actual worker deferral, fourteen-episode aggregation, season child barriers, historical suppression, movies/multiple seasons, embedded subtitle accounting, unknown-send/crash fencing, explicit processing retry rounds and retained-link/subtitle requeue behavior. All fixtures use disposable SQLite/media and injected senders; no test push was sent. Original fourteen video sources were SHA-256 fingerprinted before deployment, with existing linked mappings captured for preservation checks.

Current policy: [media notifications](../media-notifications.md). Containers and live recovery are not claimed complete until the deployment checks below are recorded.
