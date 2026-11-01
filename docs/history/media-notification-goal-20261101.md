# Media notification aggregation and season-pack recovery: 2026-11-01

Implementation, isolated regression and NAS runtime acceptance completed. Runtime code: `166b7a1`. Documentation updates do not require another image rebuild.

## Diagnosis

Live state showed one season pack with fourteen requested episodes. Only episode one was linked; thirteen records failed source/destination episode validation. Validation searched the complete source path and matched the pack directory's first episode before the actual filename. The ingestion job retried four/five times, each attempt pushing an ingestion message. Retaining episode one's existing hardlink was reported as a relink, which queued the already-completed subtitle phase again; that phase sent a second push.

## Change and self-review

Filename episode evidence now wins over directory coverage; genuine source/destination mismatch and single-episode-parent fallback remain checked. Retained preferred hardlinks return the existing/no-op outcome across restore and classification paths. Supervised ingest/subtitle workers disable low-level notifications. The existing supervisor reconciles completed acquisition/library rounds into stable per-work/season or movie summary records. Season child jobs share a parent/run barrier; explicit reviewed processing retries use a new notification round without changing download identity. Unique preferred media and indexed ready subtitles, including embedded tracks, determine counts.

The review reused SQLite Records, existing digest functions, locks, preferred publication and subtitle status metadata, without new dependencies or another processing scheduler. It removed obsolete stage-specific formatting and repeated metadata lookups. Existing urgent quota/authentication recovery alerts remain distinct. Send claims are durable; uncertain delivery is fenced rather than replayed. Historical completed tasks are not backfilled. Unrelated unfinished FIFO code/tests/documents and private connection files remain excluded.

## Validation

Serial nice-15 regression from exported staged source with the committed scheduler: 391 tests, OK with one skipped. The expanded focused suite passed fourteen tests, including actual worker deferral, fourteen-episode aggregation, season child barriers, historical suppression, movies/multiple seasons, embedded subtitle accounting, unknown-send/crash fencing, explicit processing retry rounds and retained-link/subtitle requeue behavior. All fixtures use disposable SQLite/media and injected senders; no test push was sent. Original fourteen video sources were SHA-256 fingerprinted before deployment, with existing linked mappings captured for preservation checks.

## NAS deployment and live recovery

Deployed only through `sh setup.sh local up`, using an exported committed build context that excludes unfinished FIFO work and private files. Rebuilt `media-standalone-local-control-1` and `media-standalone-local-worker-1`; both are healthy on image `sha256:b94ce2679d5eb4192f9a169aea70a74fe04b71fcfc8224b84a549d23857498d6`. Build-source and installed-package hashes match the reviewed runtime, including the committed scheduler. The NAS `.env` checksum is unchanged. This notification/worker change does not require a cloud rebuild.

At a zero-running-stage checkpoint, the existing known ingestion retry was released once by advancing its next-attempt deadline under the existing mutation lock. The guard checked its unchanged delivery/source path, original processing acquisition and fourteen-episode scope, retry state, absent lease owner, known filename-validation error and absence of unknown/quota/session recovery markers. No new job or download was created, no attempt counter was reset, and downloader ownership was unchanged.

The same ingestion job then finished with thirteen new mappings, one existing mapping, zero relinks and zero failures. Its original subtitle job finished successfully, and the acquisition reached `completed`. Runtime verification found:

- Fourteen unique preferred hardlinks for the fourteen requested episodes.
- Fourteen indexed ready subtitles.
- Exactly one `media_notice`, acknowledged `delivered` by the configured external notifier.
- Zero low-level ingestion/subtitle pushes and exactly one media-summary push after policy activation.
- All fourteen complete original-source SHA-256 hashes and file identities unchanged.
- All 808 previously linked mapping records unchanged.

This was the real already-authorized acquisition completing after the fix, not a synthetic test push. Operational startup notices retain their existing separate policy. Runtime evidence is retained in the ignored NAS state directory; no private endpoint or credential values are included in the repository. No manual rebuild or media cleanup remains for this scope.

Current policy: [media notifications](../media-notifications.md).
