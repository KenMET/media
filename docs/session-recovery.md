# Model session and quota recovery

`thread_not_loaded` describes session loading, not exhausted quota. Recovery loads the original thread without starting another turn or overwriting policy. Completed original results/research evidence are reused only after output, file, directory and permission checks.

Observe absent records every 60 seconds, at most three times. One replacement is allowed only for a read-only web-identification call with confirmed missing durable records and unchanged snapshots. Network errors, mismatched identity, missing request IDs and running calls never authorize replacement. Observe running calls up to 10 minutes, then require reconciliation. A second unknown cannot start an unlimited replacement chain.

## Archival and fencing

After output/file validation and a committed research checkpoint, atomically persist archival intent. Failed/interrupted calls require matching terminal evidence first. Only explicitly Media-owned threads are considered; recheck a unique turn against saved terminal evidence before archive. Archive failure retries independently without blocking tasks or sending push notifications. Unknown/running/user-continued threads are never automatically archived. Never permanently delete sessions or adopt unrelated/manual chats.

History retains original unknown state, thread/turn IDs, input digest, policy and replacement relation; new execution has a separate generation. Stale callbacks/plans cannot write back. Physical-file fencing spans tasks and cannot be bypassed with another task ID. Unknown subtitle calls remain fenced.

Existing-file organization fences individual files, allowing unaffected files in the work to continue. For markers from ended tasks, observe only the same account's original thread/turn. Clear active markers with terminal audit only when the thread contains exactly that turn and it is completed/failed/interrupted. Missing/running/mismatched threads or unknown history stay fenced without replacement submission.

Clear subtitle in-flight markers immediately after a normal return even if review remains; genuine unknown exceptions retain them. Historical terminal child records with `automatic_subtitle_review` prove the call returned and should not be blocked by leftover markers. Existing `embedded_extracted` Chinese sidecars are ready results only while files still exist within library bounds; reuse them without another subtitle call.

Long multilingual filenames use short same-directory temporary directories rather than UUID-expanded filenames exceeding filesystem limits. Extraction publishes atomically by hardlink without replacing existing targets. Translation replaces the destination directory entry while preserving source bytes shared through hardlinks.

TV identification still requires the correct TMDB season source. Missing title/season evidence remains a distinct review reason with model rationale/confidence, never relaxed acceptance. Checked counts include review; fully completed counts include only successful files. Identified/mapped/subtitle counts overlap and cannot be summed as successful files. Current-work subtitle checkpoints show inspected items while parent totals use committed group results.

Accepted research groups are never resubmitted. Persist complete input so cache enrichment cannot change recovery input. Freeze model policy before research and retain it on replacement. Historical unknown calls lacking snapshots stop if current policy changed and the original cannot be established.

## Quota waiting

Quota probes run every 7,200 seconds, at most ten times; the initial limit response is not a probe. Observe/accept original results before deciding whether a probe is necessary. A completed original result can pass even if new calls remain limited.

Session observation and quota budgets have separate counters/deadlines. Early observation does not move the quota deadline. Persist attempted count/next deadline before external calls; crashes cannot erase attempts. Failure checkpoints preserve original time so restart can restore parent waiting state.

Probe success does not establish original failure; only research recovery decides continuation. Legacy records retain the original budget while separating `legacy_observation_checks` and `actual_probe_checks`; never claim all historical observations proved quota exhaustion. A successful lightweight nonce probe alone does not reset the budget: renewed limits without new accepted work keep prior counts. Only completed work or newly accepted research groups begin another phase.

## Notifications

Only parents with explicit new termination events create notifications; child problems aggregate at parent termination. Deployment does not backfill old failed/review notifications. SQLite notification intents deduplicate by parent/reason; failed sending retries after 60 seconds, and only sender success records delivered. The external service lacks transactional deduplication, so a crash after send/before accounting may duplicate delivery. Semantics are at least once, never cross-service exactly once.

See [LikeC4 model](session-recovery.c4), [acceptance/deployment evidence](history/session-recovery-goal-20261030.md), and [existing-media follow-up](history/existing-media-recovery-20261031.md).

Whole-library automatic organization handles pending only, reusing unchanged confirmed identities/mappings/ready subtitles. Backend rejects global `all`; reidentification is work-scoped. Poster gaps are not pending processing: fetch display cache by confirmed TMDB ID without AI or identity writes, retaining placeholders when unavailable/unknown.
