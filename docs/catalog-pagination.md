# Discovery pagination

TMDB day/week trends and all-time top rated provide previous/next controls and page numbers, using provider totals up to 500 pages. Changing source, movie/TV or window resets to page one. SIMKL exposes its top 100 list, validates entries and presents 20 per page; it cannot extend beyond that source list.

`GET /api/discover` accepts `page` (1–500, default 1) and returns `page`, `total_pages`, `has_next` and current `items`. TMDB pages cache independently; SIMKL pages share one source snapshot. Source failures retain the corresponding stale page/list and warning. Legacy preview cache remains in SQLite; new keys avoid format mixing.

Disposable browser acceptance requires Playwright/Chromium:

```sh
node tests/manual/acceptance_catalog_pagination.cjs
```

All APIs are mocked and no real media is mounted. `PLAYWRIGHT_MODULE` can point to an existing module.

Deploy cloud with `sh setup.sh cloud up` and split NAS control with `sh setup.sh local control`. Standalone `sh setup.sh up` also affects workers and requires a safe checkpoint. Pushing source does not update another host's images.
