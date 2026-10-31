# Empty scan and real media mount repair: 2026-10-28

The screenshot's found-resources text did not establish nonempty data. Read-only state showed zero previous/latest entries and zero mappings/inventory. Containers mounted empty project `data/` at `/data`, while actual media lived at host `/data`. Fixture acceptance could not establish correct production mounts.

## Repair evidence

Privately backed up `.env`/SQLite under ignored state, changed only private `MEDIA_DATA_DIR=/data`, and used `sh setup.sh local` to rebuild this project's web/worker. Existing downloader/unrelated services/databases were unchanged; acquisition/processing queues were empty before restart.

Docker mount was verified `/data -> /data`; control/workers were healthy and scanner/frontend hashes matched source. A nonempty scan found 2,879 entries: 1,614 paired video paths (807 hardlink pairs), nine unorganized videos, 777 matched and 479 unmatched sidecars. Import receipt: 2,879 indexes, 807 new mappings, 1,256 subtitle indexes; no acquisition creation or media writes.

A fresh process still read 2,879 indexes after import exited. First admin media page returned 100 items/cursor 100 including 90 subtitle observations; two reads took about 0.67 seconds. This was NAS/application evidence, not the user's browser/public-site acceptance. The public gateway continued reading NAS; even old frontend understood new `empty` state sufficiently to hide empty confirmation.

## Code and isolated regression

Empty previews return `empty`, suppress found/confirm copy, and cannot overwrite existing inventory. Host directory, roots, totals/time and transactional receipts are visible. Admin library can display independent indexed resources without mappings.

Python 137/frontend eight passed. Chromium covered empty, normal hardlinks and no-hardlink cases with persistence and 320–1440px layouts. Private configuration/database/backups/logs remained ignored; this was not a public default-path change.
