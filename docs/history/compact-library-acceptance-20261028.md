# Compact library, extras and batch identity: 2026-10-28

Compact rows use left posters/right summaries, mobile 64px posters and about 10% smaller navigation/spacing without page scaling. Feature-only progress excludes separately counted extras.

The historical batch flow handled at most ten loaded works with persistent previews and explicit metadata confirmation. Unknown titles required a unique TMDB title/alias/year match; ambiguity/invalid episodes stayed manual. It neither used AI guesses nor automatically linked files. Mapping/subtitle maintenance stayed separate in details. Later automatic research superseded this historical interaction.

Explicit extra folders/markers classify without using unfamiliar names, duration or size as exclusion. Unique parents retain their extras; otherwise folder groups remain. Extras-only groups are recoverable by filter. Manual feature/extra classification binds fingerprints and never moves/deletes videos.

## Validation

Python 170 and frontend nine passed. Disposable browser: seven feature collections, two containing extras, five unique batch matches, unchanged identity before confirmation, persistence after save, reversible classification and row actions. At 390px, three full rows plus the next row beginning were visible; 320/375/390/430/768/1440px had no overflow/JS errors, with English verified. Original collection regression covered season identity/grouping/source inode/subtitle retention/navigation.

Fictional providers/posters/subtitles exercised real HTTP/SQLite/queues/disposable hardlinks, without real downloader/providers. Artifacts: `/tmp/media-compact-acceptance/result.json`, `library-390.png`, `batch-preview.png`, `regression/`.

## Deployment

NAS `sh setup.sh local` produced healthy control/workers after backup and baseline counts, with installed/source SHA256 parity. Read-only state: 73 default feature works, 75 total groups, five with extras; all 816 videos retained, 12 classified extras; 807 mappings, 2879 inventory and the existing one identity retained. Manual classifications/maintenance tasks remained zero; no live bulk maintenance. Default query took about 0.43 seconds.

`Chandler Charters` and `Children’s Funeral` under Featurettes/Deleted Scenes grouped under Manchester by the Sea: one feature/four extras, without guessed deletion.

Cloud SSH was unavailable; `sh setup.sh cloud` after pulling remained necessary. NAS deployment did not establish public UI delivery. This change did not modify setup or commit private state/backups; two unrelated line-ending edits remained separate.
