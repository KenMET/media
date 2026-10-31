# Model quota pause and two-hour checks

Explicit `rate_limited` does not consume short three-attempt transport retries: the durable job becomes retry with `next_attempt_at` +7200 seconds. Waiting uses scheduling rather than blocking sleeps and survives restart. Failed checks wait another two hours without model/effort upgrades; transport errors retain their prior retry limit.

Public `quota_wait` exposes next_check_at/checks/outcome_unknown. NAS UI showed waiting/deadline; public assets still needed cloud deployment access.

Proven failed/unsubmitted quota calls use a same-policy nonce probe when due, then resume progress on success. Unknown submissions first read original thread/turn. Only matching failed/interrupted research can release in-flight before probing. Running/unreadable/mismatched/completed-unaccepted originals never replay. Subtitle calls lacking observable identity remain fenced. New research uses persistent threads.

`schedule_existing_quota_task` is restricted to the owning media manager and stopped tasks with explicitly rate-limited child records. CAS reschedules the original task/queue without clearing unknowns or bypassing physical-file protection with another ID. Two hours promises a check, not restored quota; unobservable historical outcomes may require manual reconciliation.

## Historical deployment

NAS image `2f46bc8f675b` was healthy with installed/source parity; 37 local and 89 in-image focused tests, waiting/deadline/legacy-error/mobile browser and LikeC4 passed. Task `231fc692e11f464bad39bf412174230f`, original queue job 10, retained 121/746 and became waiting_quota. Initial deadline 2026-10-30 03:10:37 UTC (11:10:37 UTC+8), checks zero, survived rebuild. No real due check had yet been observed; old IDs remained. Crawler/Quant start times stayed unchanged.

Public assets remained old, and unobservable originals could not replay. A safe source archive excluded private configuration/state/media/credentials; see JSON evidence.

## Ten-check commit scope: 2026-10-30

Added independent recovery checks capped at ten to library/subtitle maintenance. Initial limit is not a check; unsuccessful checks 1–9 schedule +7200, check ten becomes failed/`quota_checks_exhausted`, retaining accepted results and unknown fencing. Unreadable outcomes count as unsuccessful recovery, never proof of quota exhaustion. UI exposes counts/ten, deadline and final reason.

The new cap/display had not been redeployed at this historical checkpoint. Earlier JSON with `quota_retry_limit=null` describes the older version, not this commit; public UI and real due-time observation remained pending.

Strict global delivery-root FIFO was excluded: identity/migration/non-library recovery/notifications were incomplete and remained local. Existing stage claiming stayed unchanged in this release. Ten-check termination notification delivery was also not established.

Before commit, an independent staged snapshot passed 239 + 25 Python tests serial low priority, twelve frontend tests, disposable SQLite browser checks for waiting, 3/10, deadlines, old errors and mobile layout, plus secret/path scanning. No production media/database or private files were staged.
