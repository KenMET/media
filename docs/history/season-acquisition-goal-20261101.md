# Season acquisition implementation: 2026-11-01

Status: implementation and isolated acceptance completed. Deployment remains pending; no production download or live six-hour scheduling result is claimed.

## Approved behavior delivered

- Season search ranks available full packs before partial packs and individual episodes. Explicit episode searches prefer matching singles. Automatic selection assigns disjoint scopes to overlapping packs and reports missing episodes.
- Download aired episodes once freezes a finite snapshot and creates no subscription. Explicit subscriptions check every six hours, with persisted NAS-owned deadlines, owner-only pause/resume/cancel and fresh permission checks. Future episodes without announced air dates do not block confirmed aired episodes and are reported separately.
- Logical season requests share one account queue slot and submission charge while physical deliveries retain the global queue limit. Existing acquisition, unknown-submission and processing fences remain authoritative.
- Ingestion and mapping repair reuse one preferred publisher. Missing episodes fill gaps; measured improvements within the requested resolution may replace old library targets. Equal/incomparable versions retain the existing target. Original source bytes and seeding remain unchanged. Different cuts, multi-episode videos and uncertain identities require review.
- Legacy duplicates have a manager-only read-only listing, frozen preview, explicit confirmation and idempotent receipt. Cleanup removes only redundant library links, archives exclusive old subtitles and preserves shared keeper subtitles and all source videos.
- Chinese-first work/season/extra directories and filenames are unchanged. Only website UI is localized; new code, operational messages and documentation are English. Existing ports, environment files and deployment topology are unchanged.

## Final review findings and fixes

The review removed a second mapping-publication implementation in favor of the existing publisher and reused SQLite records, file locks, version recovery, provider clients and quality probing. No dependency was added. Initial hardlink publication now journals its database transition; failures roll back new links while preserving pre-existing untracked links. Cleanup journals explicitly preserve the selected keeper from their first durable write, preventing rollback or crash recovery from removing it. Source reclassification cannot orphan an old target, and legacy duplicate groups require explicit cleanup.

Additional fixes cover twelve-episode account budgeting, identical-request concurrency, frozen run consent, overlapping packs, unpublished future dates, shared subtitles and subscription/manager page access for non-administrator users. The browser uses backend ordering instead of duplicating release-ranking rules. Existing unrelated FIFO changes in `runtime/state.py`, FIFO documents/progress and `tests/test_delivery_serial.py` were excluded from this release.

## Validation and operational limits

Full serial low-priority regression ran from an exported staged-source snapshot with committed `runtime/state.py`, disposable SQLite state and disposable media. Final regression: 378 tests run successfully, with one environment-dependent test skipped (112.5 seconds). The final browser permission adjustment was then verified against the refreshed staged static assets. Focused tests cover real hardlink identities and source preservation, version replacement, initial publication failure, duplicate cleanup failure/retry, shared subtitles, one-time/subscription consent, aired coverage, twelve-episode fallback, permissions and the authenticated cloud-to-NAS HTTP bridge with CSRF checks.

`tests/manual/acceptance_season_workflows.cjs` checks season ordering, one-shot versus subscription, pause/cancel and cleanup preview/confirmation in Chromium, including English/Chinese and widths 320, 390, 768 and 1440. APIs are mocked in this browser check; HTTP, SQLite and filesystem behavior are separately exercised by automated tests. No real library or downloader was modified.

No Docker executable is available in the editing environment, so no containers were rebuilt. After pulling the reviewed commit, wait for a safe worker checkpoint and run `sh setup.sh local` on NAS and `sh setup.sh cloud` on cloud. A push does not prove remote image parity. Live provider availability, a completed production download and the next scheduled subscription check still need verification after deployment. Operational behavior and exception boundaries are documented in [season acquisition](../season-acquisition.md).
