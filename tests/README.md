# Automated tests and manual acceptance

Python `test_*.py` uses disposable SQLite/files; `test_*.mjs` checks bilingual web UI and request coordination. Run serially at low CPU priority on Linux:

```sh
PYTHONPATH=src nice -n 15 python -m unittest discover -s tests -p 'test_*.py'
nice -n 15 node --test --test-concurrency=1 tests/test_i18n.mjs tests/test_ux.mjs
```

`manual/` is excluded from automatic discovery/deployment. Never run acceptance against production downloaders, real media or original databases.

| Tool | Purpose |
| --- | --- |
| `acceptance_sqlite.py` | Disposable downloads, leases, hardlinks, subtitles; optional dedicated real qBittorrent/cloud evidence |
| `acceptance_cloud_tcp.py` | Isolated HTTP/MCP, search/discovery/pairing; no download submission |
| Other `acceptance_*.py` | Historical isolated account/search/recovery scenarios; inspect fixed ports/accounts/dates before running |
| `acceptance_ai_library_browser.cjs` | Rules/AI routing, full-path scope, selective approval, unknown outcomes and mobile layout; see [identification](../docs/library-ai-identification.md) |
| `acceptance_collections_browser.cjs` | Grouping/posters/season identity/linking/subtitles; see [library](../docs/collection-library.md) |
| `acceptance_compact_library_browser.cjs` | Extras/filtering/reversible classification/compact layout; preview flags `MEDIA_PREVIEW_EMPTY=true MEDIA_PREVIEW_EXTRAS=true MEDIA_PREVIEW_COLLECTIONS=true` |
| `acceptance_inventory_browser.cjs` | Scan/import persistence, bilingual UI and 320–1440px layout; see [inventory](../docs/existing-media.md) |
| `acceptance_catalog_pagination.cjs` | Mocked-API browser pagination and bounds; no backend/media |
| `preview_platform.py` | Fictional browser QA without downloader; collection mode adds fake subtitles and disposable maintenance worker |
| `verify_package.py` | Installed package, entrypoints and static assets |
| `verify_cloud_evidence.py` | Read retained isolated evidence and verify source bytes/hardlinks |

For cross-script imports, set `PYTHONPATH=src:tests:tests/manual` at the project root. File/database acceptance also requires script-specific `.acceptance` markers and disposable state/media mounts. Historical results under `docs/history/` do not replace regression after changes.
