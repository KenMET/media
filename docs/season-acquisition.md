# Season acquisition and preferred library versions

Search a TV season without specifying episodes to prefer available season packs, then partial packs and individual episodes. A zero-seeder release is sorted last and is not selected automatically. Coverage labels are source claims, not verified file identities. Selecting specific episodes prefers individual releases; the requested scope still fences publication after download.

On the title page, **Download aired season** creates one finite request using the currently aired episode snapshot. It does not subscribe. **Subscribe to season** explicitly enables future checks. Both actions default to 1080p; select another resolution in the search options before submitting. Subscription management is under Tasks → Subscriptions, with pause, resume and cancel. Only the owner can change consent. Pausing or cancelling prevents future submissions; it does not cancel downloads already submitted or remove media.

Active subscriptions check every six hours. The cloud polls due requests from NAS once per minute; NAS owns consent, permission checks, the persisted deadline and run identity. The deadline is saved before network work, so restarting does not replay a check immediately. An interrupted or failed check waits until its next scheduled check; paused subscriptions resume with a new run identity. Episodes without confirmed air dates are excluded from automatic downloads and reported separately; known aired episodes can still download. Invalid air dates are excluded. Subscriptions remain active until paused or cancelled, including after a season finishes, to allow quality upgrades.

Every selected payload uses the existing acquisition plan, downloader identity checks, submission-unknown reconciliation and processing workers. Retries reuse the season request and torrent infohash. An existing payload cannot silently expand its original episode scope; that case requires review. A season counts as one account queue request while every physical delivery still counts toward the global 100-delivery limit. Existing per-account operation limits remain in effect. This does not change processing order or introduce a second processing scheduler.

## Library publication

The shared publisher used by ingestion and mapping repair maintains one preferred library video per confirmed movie or TV season/episode. New episodes fill gaps. A replacement needs measurable evidence of better quality within the original resolution ceiling. Equal, uncertain or incomparable versions keep the existing video. The comparator uses measured video dimensions, compatible duration, source rank and proper/repack claims; codec, container and file size alone cannot prove improvement. Different cuts and combined multi-episode videos require review.

Overlapping selected packs receive disjoint episode scopes. Other confirmed same-work episodes and extras remain in the download directory without another library link. Wrong-work and wrong-season identities fail review. Missing episodes are reported; the system does not fabricate a complete season. When all twelve episodes have been acquired and verified, the season has twelve preferred video links. An incomplete source or pending review may leave fewer, with the outstanding work reported.

Original downloaded files and seeding are retained. Existing Chinese-first work, season, extra and filename conventions are unchanged. Publication and replacement use existing mutation locks and durable version journals, including subtitle archival and recovery.

## Existing duplicates

Library → Duplicate versions lists confirmed duplicate mappings without modifying media. A manager selects the version to keep, previews exact redundant library targets and explicitly confirms the plan. Plans expire after fifteen minutes. Apply rechecks source/target inode evidence, the complete group, shared ownership and active work. Missing sources, uncertain identities and conflicting/shared targets require review.

Only redundant library hardlinks and their exclusive library subtitles are retired. Original videos remain at their download paths. Exclusive displaced subtitles are archived under the original source directory; shared keeper subtitles remain. Cleanup uses the same recovery journal and an idempotent receipt. No downloader deletion is requested. Files not represented by confirmed library mappings must first be inspected through the existing read-only inventory/import workflow.

## Deployment and validation

Update both roles through the supported entrypoints, preserving existing environment files:

```sh
sh setup.sh local
sh setup.sh cloud
```

Wait for a safe worker checkpoint before restarting NAS services. A Git push does not rebuild remote images. Automated coverage is in `tests/test_season_acquisition.py`, `tests/test_season_http.py`, `tests/test_preferred_versions.py` and `tests/test_duplicate_cleanup.py`; all use disposable SQLite/media. `tests/manual/acceptance_season_workflows.cjs` checks browser interaction and responsive localization with mocked APIs; it does not prove production downloads or live scheduling.
