# Library artwork, desktop layout and whole-library scope

Read-only inspection found 72 works, 67 without saved posters, including 65 confirmed TMDB IDs. Existing cloud provider requests found official posters for all 65 without errors. This was missing display metadata, not failed mapping/subtitles; rerunning identity AI was inappropriate.

The UI reuses `/api/detail` asynchronously by confirmed ID, never guessing/searching unknown collections. Page generations reject stale writes; one browser session shares results. SQLite detail TTL is 24 hours with five-minute failure backoff and identity validation. Artwork writes no media identity/mapping/subtitle/source state and uses no model. Dedicated metadata quota is 120/minute, concurrency two, preserving search/acquisition/AI budgets.

Desktop columns: three at >=1200px, two at 701–1199px, one on mobile. Cards/navigation/dedicated search remain.

Removed the old global `all` action. Backend rejects unscoped `all` before queue/idempotency/model work; normal single-work organization uses pending. Advanced reidentification remains work-scoped with season preview/confirmation. Poster-only gaps are never pending. Unchanged confirmed identity is reused, but genuinely changed/unknown files may still require AI.

Review covered end-to-end scope, cache identity/fallback and page switching. No dependency/table/runtime repair script or unfinished FIFO changes were included.

Validation: isolated release source on NAS dependencies passed 41 Python tests, serial nice 15 with disposable SQLite/media. Covered global-all rejection, missing-subtitle identity reuse with zero AI and cache/backoff/mismatch. Twelve JS tests passed. Disposable browser at 1440/1000/390/320px showed 3/2/1/1 columns, no overflow/errors. Six poster gaps caused only six detail calls across layouts; global actions submitted pending only. Fixture posters were not public deployment evidence.

NAS deployed commit `15b16f5` at an idle checkpoint through `sh setup.sh local`; control/workers healthy, zero restarts, installed hashes matching. Other container IDs/images/start times and four preexisting dirty file digests were unchanged. Real unscoped all was rejected without jobs. Normal pending returned zero/completed, task `293feb1552e74553bb005e8a18379cc6`, without AI.

Cloud was not rebuilt. The user's earlier rebuild preceded this commit; artwork/three-column UI still required:

```sh
git pull --ff-only
sh setup.sh cloud
```

NAS protection was already deployed. Release used committed `runtime/state.py` and restored unfinished FIFO afterward.
