# Existing generated subtitle indexing and header repair: 2026-10-29

12 Angry Men's source/library paths existed as one hardlink. A canonical bilingual generated ASS existed without a `media_subtitle` row. Content check found 1,711 dialogue entries, 1,709 containing Chinese; no new audiovisual synchronization acceptance occurred.

Two `SubtitleAgent` branches returned `exists` after keeping generated subtitles or migrating old names without registering SQLite. Automatic maintenance required files plus records, causing `automatic_subtitle_review`; this was not missing subtitles/identity failure.

Both branches now validate dialogue and register the existing file. Invalid generated markers still require review. Existing migration/style behavior remains, without another translation/provider request. Four disposable regressions covered canonical ASS, old-name ASS, false marker without Chinese dialogue and no-write dry run. Full Python 217 passed.

Before repairing this instance, privately backed up SQLite, checked video/subtitle identity/content under mutation lock and confirmed the file was outside the active task's remaining scope. Added records only: ready subtitle became true, subtitle SHA256 and hardlink/video identity stayed unchanged. Historical task errors were not rewritten; the UI distinguished historical uncertainty from current processing records.

Removed duplicate shared-header search from all pages, retained dedicated search, and reduced mobile header to 64px. Browser discovery/search/tasks/library retained search functionality with no top input, no JS errors/320–1440px overflow, and correct historical subtitle explanation. Evidence: `/tmp/media-header-acceptance/`, `/tmp/media-subtitle-history-browser.log`, `/tmp/media-subtitle-registration-result.log`, `/tmp/media-subtitle-header-full-tests.log`.

Initial NAS deployment used `sh setup.sh local control`, retaining worker start time and active whole-library work. The generic processor fix initially awaited worker rebuild; this instance's index was independently repaired. Cloud remained undeployed, requiring pull and `sh setup.sh cloud`. Private state/configuration/backups stayed out of Git; unrelated line endings remained separate.

## Later authorized cancellation and rebuild

The user explicitly requested cancelling/deleting/rebuilding. Revoked task `b85f8a889bd8482dbe2ea6d1f3d266f4` leases, attempted temporary model interruption, stopped through `sh setup.sh local stop`, then rebuilt control/workers with `sh setup.sh local`. The model terminal outcome remained unreadable; unknown/cancellation evidence remained private, and old late results were not accepted.

Removed old task/request aliases/cancelled queue records and expired unused previews. Business-table row digests matched before/after: 807 mappings, 2879 inventory, 116 identities, 124 classifications and 38 subtitles retained. No original media/completed result was deleted.

New pending task `764fd52f6dad4af99aa5cee0542a4028` covered 780 items, reusing identity/valid subtitles. Observation: three completed/three ready subtitles; generated-subtitle registrations grew from one to four, proving the new worker indexed three other files. Worker processor SHA256 `500e2874bd134a3b3c64aa57525ba537355642e6d6ece4d01bda61b8acea5d9f` matched tested source; both services were healthy, superseding the earlier pending-worker state.

Private backup/audit: NAS `state/cancel-rebuild-20261029/`. Observations: `/tmp/media-delete-and-recreate-task.log`, `/tmp/media-cancel-rebuild-observation.log`. These were authorized operations/read-only checks, not acceptance against production media.
