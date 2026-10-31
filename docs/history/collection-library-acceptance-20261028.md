# Collection library acceptance: 2026-10-28

Replaced file lists with work collections, filtering permissions/grouping before pagination. The original layout used two-column mobile posters and season/episode/version details. Whole-work/season/file identity, mapping previews/repair and subtitle maintenance used cloud metadata, NAS identity baselines and persistent maintenance jobs.

Preserved video bytes, valid links/subtitles, preferred-version demotion, target conflict rejection, changed-source review, zero-match subtitle rejection, leases/locks/version recovery.

## Disposable evidence

Python suite: 163 passed, then 17 collection tests passed after the final recovery fence. Frontend: eight passed. Browser: five collections, one TV work with three files/two seasons, partial confirmation retained grouping, linking preserved source inode, subtitle work retained existing sidecars, refresh/back/forward, bilingual UI and 320–1440px without overflow/JS errors. Inventory browser regression passed. Providers/posters/subtitle engine were fictional; this established queue/UI behavior, not provider quality.

Artifacts: `/tmp/media-collections-acceptance/result.json`, `mobile-library-after.png`, `mobile-series-detail.png`.

## NAS evidence and cloud boundary

`sh setup.sh local` updated control/worker after a private SQLite backup; `.env` was unchanged. Read-only state retained 807 mappings and 2879 inventory entries. 816 visible videos grouped into 80 confirmed/pending collections; Cyberpunk: Edgerunners' ten files remained one work. Filename seasons remained clues, not official metadata.

Library heartbeat and installed-module parity passed. No production bulk identification/linking/subtitle maintenance was run; identity/maintenance counts remained zero.

Cloud SSH was unavailable; public assets were not deployed. On the cloud host, `git pull --ff-only` then `sh setup.sh cloud` was still required. Local browser/NAS evidence did not establish public deployment.
