# Live discovery and download acceptance

Date: 2026-10-25. All roles ran on NAS `192.168.8.1`; cloud meant a service role, not Singapore deployment. Supplements [initial acceptance](platform-acceptance.md).

Real discovery/public localized-original search/download/model/ingestion/subtitles/permissions/restart passed. Python 78 and Node localization four passed; installation contained four CLIs/four assets. Browser verified language switching/preference, real lists, English search/tasks/library.

## Discovery

TMDB movie/TV day/week returned 20 items each. SIMKL independently returned four real lists, historically truncated to 40, without a key. Last-Modified was current; source/fetch times were distinct, cache one hour/backoff five minutes. Files older than two days or anomalously future-dated were rejected; failures retained stale cache/time. Sources/ratings/links distinguished TMDB, SIMKL and Douban. SIMKL IDs linked details; missing IDs required title confirmation. Douban remained disabled/unavailable without falsely substituting TMDB.

References: [SIMKL lists](https://simkl.docs.apiary.io/reference/anime/genres), [new docs](https://api.simkl.org), [images](https://api.simkl.org/conventions/images). Attribution remained explicit; no random query strings were added to list files.

## Real acquisition

Used WebTorrent's authorized Sintel short, Blender Foundation CC BY 3.0, retaining credits. Sources: [free torrents](https://webtorrent.io/free-torrents), [Blender](https://durian.blender.org/about/).

129,302,391 bytes, infohash `08ada5a7a6183aae1e09d831df6748d566095a10`. Dedicated qBittorrent completed a real transfer; the script recomputed every torrent piece SHA-1 in official file order rather than trusting 100% progress. Gateway plan/submission replay retained one job, readable through MCP. Existing live model identified/named/linked video with unchanged bytes/inode. Nine real sidecars were found; English translation produced Chinese subtitles with one saved record and completed state.

Real HTTP denied ordinary access, permitted read-only after a grant, denied retry, then denied after revocation; disabling invalidated sessions. Stopping local retained cloud health but queries returned 503. Restart preserved the same completed job, single torrent and ready worker.

All files/state/downloader configuration were disposable with `.acceptance`; production was not mounted/restarted. No unrelated adoption/deletion occurred.

## Public search and bilingual UI

Dedicated Jackett used bundled Nyaa public definitions without accounts. `Frieren` and its Chinese title returned actual releases. Initial episode-encoded queries yielded none; original/localized/English metadata names and bounded suffix-free fallback were added without changing frozen scope or post-download checks. Both inputs finally resolved `tv:209867`, with eight S01E01 candidates and a plan restricted to that episode. Positive results came from English metadata; fallback had separate coverage. Source claims still required physical identity checks. These searches submitted no TV downloads.

Web language selection persists per browser. Only authored templates/copy translate; titles/releases/user input/provider data/JSON remain untouched.

Tools: `tests/manual/acceptance_catalog_live.py` (eight lists/details), `acceptance_download_live.py` (fixed isolated downloader/state/media, hashes/link/subtitles/HTTP/MCP/permission), `acceptance_recovery_live.py` (before/offline/after), `acceptance_search_live.py` (real bilingual identity/public search only), `tests/test_i18n.mjs` (defaults/copy/dynamic data/preference).

One public site did not establish every source/private account or real two-host topology. No Singapore deployment/whole-downloader adoption occurred.

## Retained local instance

Later UI uses ordinary download/media-management capability switches, loading/duplicate-click/mobile support; old object-grant tests remain historical compatibility records. Users no longer need object IDs/grants for normal use.

`http://192.168.8.1:18414` used private accounts in ignored `state/live-login.txt`, live TMDB/SIMKL, dedicated Jackett/qBittorrent/workers and a test media disk. Explicit download actions created real tasks. Ignored copy: `state/platform-compose-acceptance-20261025`. Port 18314 remained the earlier fictional preview, not this live instance. To stop the retained copy, run cloud stop then local stop through setup in that copy, preserving state/files for restoration.
