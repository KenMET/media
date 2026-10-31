# English project content goal: 2026-11-01

## Scope and explicit correction

Convert project-authored documentation, contributor rules, source comments/docstrings, model explanations, setup/CLI output, operational errors and notifications to English. Retain bilingual web UI and its existing default/preference. The user explicitly clarified that ingestion/hardlink naming remains Chinese-first exactly as before: work/season/extra directories and filenames are not translated or renamed. Subtitle language/output and multilingual recognition remain unchanged.

New policy is in [language-policy.md](../language-policy.md) and AGENTS.md. Current and historical documentation was translated with dates, identifiers, counts and deployment limitations retained. Structured evidence preserves exactly the same decoded values; multilingual media/protocol/fixture literals use explicit Unicode escapes rather than changing their meaning. Runtime code, tests, manual tools and documentation retain existing directories.

## Self-review findings and fixes

- Reverted an initially mistaken English-path implementation after the user's clarification. Nine naming/classification/media-data modules retain identical executable AST after removing docstrings, including Chinese-first path construction.
- Translated setup, readiness, pairing, ingestion/subtitle/terminal notifications and OAuth explanations. Original identities, submission fences, leases, locks and recovery remain intact.
- Updated the explicit subtitle copy fallback to recognize the translated cross-filesystem error while retaining compatibility with historical wording. A disposable regression checks actual copied bytes, independent inode and staging cleanup.
- Kept raw-string/regex and JSON decoded semantics intact, fixed a partially translated OAuth sentence and a notification-label replacement collision, and a conflicting research instruction that still requested Chinese reasons, and avoided unrelated newline churn.
- Added an automated non-web language regression check and validated internal documentation links.
- Existing unfinished FIFO runtime/test/progress work remains excluded. The local untracked FIFO specification was translated for consistency without publishing its unfinished implementation.

## Validation and delivery boundary

Serial low-priority main regression passed 372 tests with one skipped; twelve web localization/request tests passed. Focused naming/client/notification/language checks passed eighteen tests; final atomic-write/language checks passed ten with one skipped because FFmpeg is unavailable locally. Disposable browser pagination/mobile checks passed with mocked APIs and no real media.

Additional subtitle suite ran eighty tests: seventy-nine passed, one existing synchronization validation-count assertion failed (expected three calls, observed two). The same single test failed identically in an untouched HEAD export. It is not presented as a new regression or a passing suite. An initial standalone ingestion quality run required fixture-root configuration and is not counted as a passing suite; naming-specific checks and executable-equivalence review establish the language scope.

Shell syntax, Python parsing, structured-evidence equality and internal links passed. The independent staged release snapshot (excluding unfinished FIFO) passed 354 main tests with one FFmpeg-dependent skip. Exact staged review found no private runtime files or private-key material, and staged runtime/state.py matched HEAD. Commit/push and remote verification are reported at delivery.

No Docker executable is available in this editing environment; no container was rebuilt and no production media/state was touched. Runtime text changes require the existing deployment hosts to rebuild through `sh setup.sh local` (NAS control/workers at a safe checkpoint) and `sh setup.sh cloud` (cloud web/MCP). Standalone uses `sh setup.sh`. Preserve existing configuration/ports/domains/topology. Push alone is not deployed evidence.
