# Deleted history incorrectly consumed queue capacity

Read-only state found zero acquisitions and 17 maintenance tasks, all deleted. `Budget.admit_job` still counted them as pending while the UI hid them, triggering the account limit of ten despite empty visible lists. Deletion had omitted the admission terminal-state update.

Added `deleted` to terminal exclusions for acquisition and maintenance. Limits remain account ten/global 100; no history clearing, quota reset, unknown fencing removal or test downloads. Real queued/running/unknown-submission work still occupies capacity, with audit/idempotency retained.

Eight `tests/test_limits.py` tests passed serial nice 15 on temporary SQLite. Two new cases showed 200 deleted acquisition/maintenance rows occupy no slots, and 17 deleted rows permit nine real pending tasks while a tenth real unknown still blocks admission. Global bounds, cross-process throttling and unknown reconciliation remained covered.

Review checked both record kinds, account/global counts, unknown state and audit. Unfinished FIFO/preexisting docs/manual edits were excluded. Only NAS quota code needed deployment; cloud did not.

At idle, `sh setup.sh local` updated healthy control/workers, zero restarts and limits-module parity; other services unchanged. The 17 deleted tasks belonged to one account; actual pending and unfinished processing counts were zero. Formal `Budget.admit_job` query passed in an independent check that skipped only submission-rate spending, preserving user budget. No test acquisition/data reset occurred. Existing dirty file digests remained unchanged.
