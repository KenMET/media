# Goal: recover unreadable model sessions and resume safely

This report retains chronological checkpoints. Initial status was implementation/acceptance; the final internal-logic section supersedes earlier pending items. Public asset delivery and independent strict FIFO remained separate.

## Incident and requirements

Read-only NAS snapshot around 2026-10-30 12:55–13:00 UTC: task `231fc692e11f464bad39bf412174230f` retained 121/746 results, normal queue, 7200-second interval/ten checks, five checks attempted. App Server connected but original read returned `thread not loaded`. This proved neither exhausted quota nor original failure/loss/running state. The old flow conflated unreadability with quota and skipped probes after original-read failure. These were design-time observations requiring refresh before action.

Recover original output before bounded replacement of genuinely unrecoverable read-only research. Preserve accepted work, unknown fencing, physical identity and publication safety.

Required rules:

1. Distinguish quota, transport, unloaded thread, running, unknown and completed-unaccepted using controlled errors without raw RPC/secrets/addresses.
2. Read original thread/turn first. Verify supported same-thread loading; resume may load only the same ID without turn/start, policy overrides or new research.
3. Completed output requires identity/completeness/snapshot validation; accepted groups never repeat. Failed/interrupted may retry under frozen policy. Running requests receive bounded observation without parallel replacement.
4. Persist at most three observations, 60 seconds apart, independent of quota checks. A confirmed running call has a ten-minute observation bound; expiry means review/notification, not failure or replay authority.
5. Only missing durable history in read-only identification may receive one transactional replacement. Preserve original unknown/superseded relation and increment generation tied to same files/task/input/policy. Only current generation/lease may accept/publish; late output is audit only. It may spend one extra research call and must be recorded honestly. Prove no tool writes and fence every acceptance path, otherwise retain review.
6. One replacement per logical group; another unknown stops/notifies without chains. Subtitle/side-effecting calls retain unknown fences and require separate proof before any future extension.
7. Resume durable unfinished groups rather than hardcoding item 122, repeating the accepted 121, rebuilding the whole library, adding downloads or adopting tasks.

## Quota semantics

Only explicit rate limits enter waiting. Initial limit is not a check. Due checks run every 7200 seconds, maximum ten, recording available/limited/transport outcomes honestly. Transport errors still consume bounded waiting attempts but never claim confirmed quota exhaustion. At ten, preserve results and notify with actual reason. Available quota permits recovery, not proof of old failure.

Session load/read counters stay separate. Same-policy nonce probes do not automatically clear unknowns. Preserve historical observations/counters/deadlines and remaining budget without fabricating old quota results or silently resetting ten attempts. Original design mentioned five; actual migration later found six.

## Acceptance gates

Refresh production state/identity/policy/leases/parity, back up SQLite and sample preserved bytes. Verify protocol/loading/error classes; persist generation/input/fingerprint fences and audit every result path. Separate quota/session migration. Add honest UI and durable deduplicated notification intent. Serial disposable tests cover completed results while probes fail, running/missing calls, two-worker competition, lost leases, restarts, late generations, changed files, accepted groups, replacement bound, 9/10 and historical budgets/notification failure. Validate docs/model/browser and deploy only affected Media via setup at safe checkpoints, excluding unfinished FIFO and unrelated services. Observe original progress past checkpoint through final state and report actual outcome; health/probe/new threads/queueing alone cannot complete the goal.

## Protocol and first deployment

Actual NAS Codex-generated ThreadResumeParams/ThreadReadParams supported threadId-only loading. Original resume returned RPC -32600 containing `no rollout` without a new turn. Added controlled not-loaded/missing-rollout classification and recover_thread that resumes only after not-loaded, rereads and verifies IDs. Six transport tests passed: no new turn/override, missing history, connection and mismatched identity. This first local stage was not yet production integration or fence release.

Initial setup deployment rebuilt Media control/workers only, preserving Codex/Quant/Crawler/Portal IDs/start times and excluding/restoring FIFO. Hash parity and 104 focused tests passed. A separate installed run failed imports due to missing tests namespace and was explicitly not counted as passing.

Formal `library_session_recover` migrated six historical observations, retaining budget/identity/history without inventing quota failures. A real nonce passed. Missing rollout received three observations then one controlled replacement, original unknown audited. At 13:23:42 UTC original task reached 129/746 with valid lease/subtitle stage. Original 121 results, 746 source stats and sampled hashes matched. This was progress, not final completion.

## Notification incident

Initial compensation incorrectly interpreted old failed/review child records as new events, sending 104 historical attention notifications. After feedback, suppressed 164 historical terminal records/cancelled sixteen queued notices; delivered stopped increasing. Sent notices were not recalled. This was an implementation defect, not new user-task failure.

Permanent repair accepts only new parent `terminal_notice_event`, excludes child notification intents and aggregates at parent termination. Added historical/child/no-backfill/crash-dedupe regressions. At that checkpoint the fix still awaited tests/safe deployment, without interrupting in-flight subtitles. Suppression alone was not proof of deployed repair.

Public app.js then contained model_settings but tasks.js lacked waiting_session, superseding the earlier claim Settings was absent while leaving new recovery display undeployed. Summary: `session-recovery-20261030.json`; private evidence under ignored `state/session-recovery-20261030`.

## Phone session lifecycle

Persistent research threads accumulated without post-acceptance archival. Database request identity/input/accepted keys plus actual unique terminal turn proved fifteen completed Media threads, which were archived. Active list 30→15, unrelated count unchanged, one Media thread pending recovery. Archive was not deletion or unknown clearing.

Automatic lifecycle persisted checkpoint/terminal evidence with archival intent atomically; a separate retrying background consumer skips unknown/running/manually extended threads. No push and no task failure on archival errors. Fifteen real archives established protocol behavior; subsequent production enqueue/drain still needed observation then.

## Intermediate installed acceptance

Permanent notifications, lifecycle and independent transport/session/quota counters deployed through setup, Media-only/parity/FIFO exclusion preserved. Installed 118 focused tests plus ten quota regressions passed. Installed bilingual browser 320/390/768/1440 and LikeC4 passed without overflow/errors.

Task reached 428/746; original 121 and later 428 checkpoints retained. 746 sources/745 targets/745 hardlink identities and sampled hashes unchanged. Notification counts remained 104/16. At 13:40:38 UTC a new rate limit had an observable matching failed turn, unlike missing old history. Deadline remained 15:40:38 UTC (23:40:38 UTC+8), checks zero; deployment did not advance it/replay/clear unknowns. Six old observations and superseded unknown audit remained.

## User boundary and coordinator

User confirmed configuration/ports/domains already existed and requested internal logic only. Earlier cloud-access requests were withdrawn; preserve configuration, do not request SSH/console or make extra access a prerequisite. Read-only public inspection can document old assets separately.

Unified recovery coordinator validates original file/directory/input/policy/lease and accepts completed results before consuming quota probes. Session observation schedules independently each minute; quota stays at its original two-hour deadline/count. Persist confirmed failures and archive before waiting, without early research. Publish only after terminal task/idle window.

The completed-result/new-probe-unavailable crossover passed. Original task reached terminal state and real automatic archival worked. Public waiting_session assets still lacked deployment evidence and remained an explicitly separate presentation item.

## Final internal acceptance: 2026-10-30 16:10 UTC

Original task resumed automatically at 15:40:38 without early checks/manual unknown clearing and reached 746/746, `completed_with_warnings`: 84 complete, 662 review (553 uncertain matches, 97 old identification unknown, 12 old subtitle unknown), failed zero/blocked zero. Unknown files stayed fenced without task/thread bypass.

Fifty-eight `library_thread_gc` records archived. Zero attributable Media threads remained in the observed active list; fourteen unrelated entries stayed untouched. Unknown/running/manually extended threads remained protected. Notification counts stayed delivered 104/suppressed sixteen, no further backfill.

Coordinator/pre-call durable quota budgets deployed through `setup.sh local`. Independent source tests: 106 recovery + nineteen platform/model; twelve JS and LikeC4 passed. Final installed Python 125 and JS twelve passed; installed disposable bilingual browser at four widths had zero errors/overflow.

746 source/745 target paths and 745 hardlink identities plus sampled hashes were unchanged. Original 121/all 746 results matched. Installed source hashes matched; unfinished FIFO excluded/restored. `.env`, setup/Compose hashes and unrelated container IDs/images/start times remained unchanged.

Research failure checkpoints reconstructed parent waiting deadlines after crashes; attempts persisted before external probes. Subtitle unknowns remained fenced without claiming equivalent thread-output recovery. Public old assets remained recorded undeployed display scope under the user's boundary, not an internal logic blocker.

Private receipts: `state/session-recovery-20261030/coordinator-release/verified.json`, `installed-tests.log`, `thread-audit.json`, `configuration-hashes.json`, `other-services.before/after`, `setup.log`.

Internal recovery/original terminal acceptance completed, without claiming the entire project or strict FIFO/public delivery complete.

## Later simplification review

No package reorganization/framework/dependency. Four runtime modules retain distinct session/coordinator/notice/archival responsibilities, reusing Records/supervisor/Codex/notifications. Removed unused early manual observation, retaining automatic scheduling/legacy waiting migration. Consolidated budget reuse/lease-permission closures and duplicate wait persistence.

Fixed bounded history falsely blocking new tasks: reproduced with 130 completed entries, then scanned genuinely unknown entries only while still rejecting later true unknowns. Related 126 passed. Current docs/model stayed under docs, dated report/JSON under history; unfinished FIFO/three line-ending-only edits untouched. At this checkpoint no commit/push had yet occurred.

Removed one-time `enqueue_existing` helper, testing regular enqueue/drain directly; seven archival tests passed after simplification in the installed final package, in addition to 126 full related tests. README/index links added without new top-level directory/dependency/table. Final setup release reverified hashes/original 746/source-hardlinks/configuration/unrelated services. Commit/push remained pending at that historical report; the later delivery review records closure.
