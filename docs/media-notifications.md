# Media processing notifications

A processing round emits one result summary for each confirmed TV work/season or movie. It combines library and subtitle results instead of pushing once per episode, phase or automatic retry. A season request that falls back to individual releases waits for planning and all child acquisitions to finish. A later subscription check or an explicit reviewed processing retry is a new round; it can emit a new summary for the newly processed scope.

Example:

```text
Media processing summary
Series Example S03
Library videos: 14/14. Subtitles ready: 14/14.
```

Counts refer to unique requested movies/episodes with a valid preferred hardlink and an indexed ready subtitle. Existing and embedded subtitles count as ready; extra versions do not inflate totals. Missing media/subtitles are reported as items needing attention. Standalone batch and subtitle entrypoints group confirmed media by work and season. Unidentified batch failures retain a generic attention summary rather than inventing an identity. Operational startup/authentication/quota alerts remain distinct from media result summaries.

The supervised workers disable low-level stage pushes. Retaining an existing hardlink is a no-op, so an ingestion retry does not queue completed subtitles again. Terminal acquisition/library rounds are reconciled into durable `media_notice` records by the existing supervisor. A policy activation watermark prevents completed historical tasks from being replayed as new notifications. Existing urgent library recovery notices keep their original fenced delivery path and are not duplicated by the media summary collector.

Each summary has a stable round/work/season key. The send claim is persisted before contacting the notifier. A successful acknowledgement becomes `delivered`; a timeout, negative/unknown acknowledgement or recovered interrupted claim becomes `delivery_unknown` and is not automatically replayed. Bark does not provide an exactly-once transaction with SQLite: conservative suppression avoids a duplicate push when the server may already have accepted it. Unknown notices remain available for operational review in persisted records; ingestion and subtitle work are not rerun to retry a notification.

The screenshot's repeated one-success/thirteen-failure season was caused by full-path episode parsing: the release directory contained S03E01-E14, so its first episode overrode individual S03E02 through S03E14 filenames. Filename evidence now takes precedence; existing single-episode parent fallback and actual source/destination mismatch rejection remain. The notification change does not weaken acquisition identity, lease ownership, mutation locks, source-byte preservation or version recovery.

Regression coverage: `tests/test_media_notifications.py` uses disposable SQLite/media, real hardlinks and injected senders. No test sends a live push. Deployment uses only `setup.sh` at a safe worker checkpoint and excludes unrelated unfinished delivery FIFO work.
