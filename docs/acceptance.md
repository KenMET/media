# Historical acceptance and extraction index

These reports record past evidence, not renewed acceptance of the current image. Use the [README](../README.md) for setup and [security review](security-review.md) for its stated review scope.

| Record | Scope |
| --- | --- |
| [Recovery review/delivery](history/session-recovery-review-goal-20261031.md) | Correctness, simplicity, reuse, layout, Git and deployment boundaries |
| [Session recovery/archival](history/session-recovery-goal-20261030.md) | Independent session/quota recovery, notifications and original task outcome |
| [Cloud search/local execution](history/cloud-execution-goal.md) | One-way connection, 118 tests, providers and isolated ingestion |
| [Local functional acceptance](history/local-functional-acceptance-20261026.md) | Permissions, real downloads/subtitles, quotas/recovery |
| [Live providers/bilingual UI](history/live-acceptance.md) | Discovery, localized/original public search and download evidence |
| [Initial 0.3](history/platform-acceptance.md) | Initial web/MCP scope/results |
| [2026-10-26 security](history/security-review-20261026.md) | Original findings and repair boundaries |
| [0.2](history/acceptance-0.2.md) | Original SQLite/bundled dependencies/LAN acceptance |
| [0.2 receipt](history/runtime-receipt-0.2.json) | Historical image/source hashes only |
| [0.1](history/acceptance-0.1.md) | Superseded MySQL/OAuth acceptance |
| [0.1 receipt](history/runtime-receipt-0.1.json) | Old hashes |
| [Original goal](history/GOAL.md) | Historical scope, not queue configuration |
| [Extraction manifest](history/source-manifest.json) | Original paths/hashes; destinations relative to Media root |

Reports are outside runtime/build inputs. Old startup/script paths are historical only; `setup.sh` remains the sole supported deployment entrypoint. Manual tools live under `tests/manual/`. Runtime configuration, task databases and media never belong in this history directory.
