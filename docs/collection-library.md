# Collection library and maintenance

The library groups poster cards by work; TV details expand seasons, episodes and versions, while movies show versions. File details expose source/target paths and subtitle records. Compact rows place a small poster left and summary right; mobile posters are 64px with roughly 10% smaller spacing/controls. Detail routes support refresh, browser navigation and link restoration.

## Grouping and status

Confirmed files group by `movie:ID` / `tv:ID`; unidentified canonical TV paths group under their `series/<work>` directory. Download folders use conservative directory/name clues to avoid merging unrelated root files. Prefer the trailing canonical filename year rather than numeric title text.

The backend groups and filters permissions before pagination, keeping multi-page TV works together. Ordinary users see only authorized files/counts/state; aggregates never leak another user's media/paths. Administrators/media managers can maintain the whole library.

Versions/resolutions remain separate files beneath an episode. Partially confirmed files can share a collection when a unique work identity exists; conflicting identities never merge automatically.

Summary cards show title/year/mapping/subtitle totals. Unknown identities use placeholders. Confirmed titles missing posters asynchronously fetch cached details by existing TMDB ID without AI or name search. SxxExx filenames remain clues, not verified episode identity.

Subtitle states distinguish processing records, discovered/unverified, missing and review. Discovery alone proves neither language/content nor synchronization. Summary mapping totals come from saved records; detail/mapping previews recheck current file identity.

## Extras and filtering

All videos remain indexed. Explicit Extras/Featurettes/Deleted Scenes/Bonus Features directories and equivalent multilingual labels, NCOP/NCED, trailers and S00 markers classify extras. Unfamiliar titles, short duration or small size alone do not hide files. Confirmed feature movies named Trailer/Sample are not excluded solely by title.

Extras attach to a unique parent work; otherwise retain folder-based groups. Default lists include feature-containing works; the extras filter includes both extras-only and mixed collections. Feature mapping/subtitle metrics exclude extras and show extra counts separately.

Managers can classify selected files through advanced options, modifying only SQLite indexes after confirmation. Classification binds to fingerprints, so replacement files cannot inherit stale hiding. Changes respect locks/overlapping work and invalidate old identity/mapping snapshots without moving/deleting files. Extras skip ordinary linking/subtitle maintenance; researched features can be restored to normal classification.

## Automatic organization

Whole-library automatic organization covers all pending media; row/detail actions handle one work. Normal processing needs no file selection, preview confirmation or separate mapping/subtitle request. NAS checks rules/duration, researches full paths/context as needed, saves reliable identity, repairs safe missing links and checks subtitles. Uncertain/conflicting items remain unresolved without blocking other works. Advanced tools handle exceptions. See [identification](library-ai-identification.md) for thresholds and evidence.

## Manual identification

1. Select a work, season or files; no selection explicitly means the entire work.
2. Search/select a title. Manual metadata/seasons come from cloud; NAS does not call TMDB. Intelligent research uses the local worker's existing AI connection.
3. Check season/episode assignments and optional common season. Missing episodes cannot be confirmed from filenames alone.
4. Preview and explicitly confirm. This updates identity/metadata/fingerprint baselines, not videos, existing links or subtitles.

Previews bind files/paths/records/identity for 15 minutes. Changed files/permissions or overlapping maintenance require a new preview. Repeating the same identity is safe; different candidates cannot silently replace confirmation.

`media_library_identity` holds confirmed file identity; `library_title` stores poster/overview/season evidence. Real mappings remain in `media_link`; no download jobs are invented. Unmapped files can be identified before linking.

## Mapping repair

Advanced mapping checks create a separate queued preview; automatic organization executes equivalent verified actions directly.

- Correct only mapping state when actual hardlinks remain identical; never restore a demoted preferred version automatically.
- Retain valid mappings without forced rename or preferred-version replacement.
- Recreate a missing saved target only after source/record identity and free destination checks.
- Build canonical targets for identified unorganized files; refuse occupied targets.
- Reidentify changed sources before linking new bytes.
- Keep library-only resources indexed without inventing source paths.

Use existing mutation locks/version recovery logs and create missing links only. Preserve source bytes, existing targets and subtitles. Recover committed links/results after crashes; journal uncommitted changes. Retry never grants deletion.

## Subtitles and task ownership

Support missing/failed/unverified processing or revalidation of selected files. Only confirmed, trusted mappings enter the queue; unknown/conflicting/insufficient relations are skipped with reasons. A trustworthy target may support processing despite a missing source.

Reuse extraction/matching/verification/provider processing, preserving valid results. Default skip requires the recorded file still to exist. Stale records do not prevent checks. Zero matched media never reports success. Content/verification evidence, not language labels alone, establishes readiness.

Maintenance lives in `library_task`, separate from acquisition history and qBittorrent ownership. The `library` worker supervised by `local-worker` uses SQLite leases, 20-second renewal and mutation locks. Recheck current permission/lease before writes; external subtitle calls release/reacquire locks with identity checks.

Same-key retries return the original task; overlapping maintenance is rejected. Account queue/submission budgets apply. Progress/results persist in details. Advanced scope allows 500 files; whole-library auto internally groups up to 20,000. Episode evidence must come from the selected title's real metadata.

## Deletion

Advanced explicit deletion previews list selected source files, library hardlinks, recorded/indexed subtitles, attributable companions and cleanable directories. Indexed independent files can be deleted by verified physical identity without prior AI identification.

Preview is read-only. Execution rechecks permissions/identity/fingerprints/download ownership and stops associated queue work. Cancellation revokes leases, while actual deletion waits for worker mutation checkpoints. qBittorrent removes only precisely owned tasks and always retains downloader files. Files use non-overwriting temporary quarantine hardlinks in their original directory; original entries are removed, records cleaned, then quarantine released. Interrupted execution resumes with the same plan without deleting later replacements.

Include entire media directories only when no unrelated indexed media or unknown videos exist. Shared directories retain other files. Newly appearing files are retained and reported. Clean selected mappings/subtitles/inventory/identity/classification and unreferenced display records, while preserving deletion audit and unknown-request evidence. Public cloud TMDB cache is independent of personal media deletion.

Whole-library auto processes pending only and rejects global `all`; reidentify within a single work. Completed files and poster-only gaps do not trigger AI.

## Deployment and disposable acceptance

The feature spans NAS APIs/workers and cloud assets/provider forwarding. Update each through `sh setup.sh local` / `sh setup.sh cloud`. `library.js` is packaged with existing interfaces; keep private configuration/state/media out of Git.

```sh
MEDIA_PREVIEW_COLLECTIONS=true MEDIA_PREVIEW_MANIFEST=/tmp/media-collections-preview.json \
  PYTHONPATH=src nice -n 15 python3 tests/manual/preview_platform.py
# In another terminal:
PLAYWRIGHT_MODULE=/path/to/playwright-core CHROME_EXECUTABLE=/path/to/chrome \
  nice -n 15 node tests/manual/acceptance_collections_browser.cjs
```

Fictional providers/subtitles and disposable files exercise real queues, fingerprints, SQLite and hardlinks. Destructive acceptance checks the disposable marker and fixture bytes first. It covers grouping/posters/season identity/recovery/linking/subtitle persistence/bilingual/mobile/desktop. Artifacts default to `/tmp/media-collections-acceptance/`. Never run it against production.
