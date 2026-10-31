# Existing media: rules first, AI fallback

NAS `local-worker` owns identification, directory enumeration, duration probing, model calls and SQLite persistence. Cloud owns web assets and existing manual TMDB search. Intelligent identification needs no NAS-to-cloud callback, relocated TMDB key or topology change.

## Automatic workflow

Whole-library automatic organization covers pending identity, abnormal mapping and unready subtitles independently of current page/search/filter. Work-row/detail actions handle one work. Current whole-library scope is pending only; explicit reidentification belongs in a single-work detail page. Existing valid mappings/subtitles are retained.

The worker checks rules/duration, researches when necessary, saves identity/classification, repairs safe missing links and processes missing subtitles. Deterministic results or usable AI confidence at least 0.9 can save automatically. Unknown/low-confidence results, changed sources, conflicts and subtitle failures remain individual unresolved results without blocking other works or requiring approval for reliable items. Extras stay indexed/grouped but skip ordinary feature linking/subtitles. Library-only files never acquire invented download sources.

Background work persists after closing/refreshing. Dedicated task links expose substeps, work/file progress, overlapping identified/new mapping/subtitle counts, and all paginated results. Reconnection follows [task experience](task-experience.md). Duplicate active scope returns the original task. One whole-library parent internally groups works beyond 24-card pages and the account's ten-task admission limit. Each group supports 500 indexed videos; one whole-library request supports 20,000 files; larger requests fail explicitly.

Advanced controls retain preview-only suggestions, manual identity selection, file scope, classification, mapping previews and subtitle review. Only these explicit tools use preview/confirm. Unindexed files must first be imported.

## Rules and context

Use saved identity, complete fingerprints, explicit extra markers and measured duration first. Confirmed unchanged normal-duration files can use deterministic identity; explicit short extras can use classification rules.

Send to AI when identity/rules are uncertain, probing is unavailable, duration is below about 55% or above 170% of group median, differs from saved reference by more than `max(5 minutes, 25%)`, or an extra exceeds 20 minutes. Thresholds trigger research rather than discarding short media. Source/library paths of one physical video share a probe result.

Model context includes full source/target paths, related directory paths, measured durations, known work clues and why rules were insufficient. It never reads subtitle/other file bodies; skip symlinks, hidden directories and `.env`. A selected file in a shared download/category root includes only itself and same-prefix companions, not unrelated works. Expand full directories only when explicitly selected. Retain selected directory scope rather than enumerating another directory reached through a hardlink.

A task supports 500 indexed videos; context supports 2,000 files, 500 physical videos and about 600KB of paths/fingerprints. Exceeding limits asks for narrower season/folder groups, never silently truncates. Each AI group contains at most 12 requested files, 24 search items per call and a 300-second budget, with directory context retained.

## Research evidence

Library research uses a dedicated read-only App Server profile. Web search/open/find are allowed; shell, file editing, MCP, plugins, subagents and interactive approval are disabled. Other media/subtitle client tool policies remain unchanged.

AI may infer context from parent directories, research real titles/seasons/episodes, and distinguish features, extras, interviews, deleted scenes, trailers, shorts and unknowns. Every result must retain its requested key; context files cannot impersonate request files. Reasons explain duration, with unavailable reference duration left null.

Record actual search/open activity. When page bodies are blocked, search snippets/citations may support a match after cross-checking title/year/duration/episodes and explaining access limits. Blocking alone does not invalidate a strong match. Identity proposals require matching TMDB IDs/citations; TV features also require the corresponding season citation. Identity-free extras can use researched public context.

Sources distinguish attempted page opens from search citations whose bodies were not confirmed readable. Accept reported search citations only with recorded search activity; unaudited memory-only claims cannot save. Display public HTTPS links only, rejecting private/non-web targets.

Citations are not claims that page bodies were read or TMDB API fields independently verified. AI judges source relevance/reliability and may return wrong links. Advanced previews expose evidence. Automatic confidence thresholds reduce but cannot eliminate model errors. Identity/link/value consistency checks are not independent factual verification. Wrong keys, confidence below 0.8 and genuinely unknown identity cannot save directly.

Protocol references: [App Server events](https://learn.chatgpt.com/docs/app-server), [web search configuration](https://learn.chatgpt.com/docs/web-search).

## Persistence and safety

`library_task` uses existing workers, SQLite leases/renewal, permissions and queue budgets. Probe cache keys contain complete fingerprints. Private SQLite stores manifests, rule results, sources and previews.

AI outputs structured decisions only; code owns file mutations. Automatic saving records `approval_mode=automatic`, not fabricated user approval. Recheck directories/files/permissions/overlapping work and update identity/classification atomically under the mutation lock. Linking reuses version recovery, creates only missing hardlinks and never overwrites targets or source/subtitle bytes. Automatic mode cannot bypass conflicts, changed identity or revoked permission.

Persist intent and thread/turn identity before model submission. Unknown outcomes or interruption never silently resubmit; accepted groups and committed links recover. Subtitle calls also persist intent before external work and retain unknown fencing. Definite quota/auth/network failures stop further AI for the pass while deterministic work may continue.

Verify existing subtitle files before invoking the established engine. Claimed success still requires ready files/records; otherwise report unready. Advanced manual proposals expire after 24 hours; repeated identical confirmation returns its receipt.

## Disposable verification

```sh
PYTHONPATH=src MEDIA_PREVIEW_EMPTY=true MEDIA_PREVIEW_COLLECTIONS=true \
  MEDIA_PREVIEW_EXTRAS=true MEDIA_PREVIEW_ANALYSIS=true MEDIA_PREVIEW_MANY_MOVIES=30 \
  MEDIA_PREVIEW_MANIFEST=/tmp/media-collections-preview.json \
  nice -n 15 python3 tests/manual/preview_platform.py
PLAYWRIGHT_MODULE=/path/to/playwright-core CHROME_EXECUTABLE=/path/to/chrome \
  nice -n 15 node tests/manual/acceptance_auto_library_browser.cjs
```

The preview uses disposable media/SQLite and fake AI/probes, retaining real HTTP/queue/save/hardlink paths. It does not connect to real downloader/model/subtitle services. Separate live model acceptance sends fictional paths only, never production SQLite or media.
