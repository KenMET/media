# Site search progress and stable website navigation: 2026-11-01

Runtime commits: `fa23042` (Jackett progress) and `fb62a71` (navigation and task presentation). Subsequent acceptance/report-only commits do not change runtime bytes or require rebuilding the image.

## Delivered behavior

Movie and TV searches share a loading panel above resources. It displays configured Jackett site IDs and live waiting/searching/responded/timeout/failure states rather than season fractions. Earlier resources remain usable until all scoped requests terminate. A site response is an observation, not a promise that later localized-title or season queries are finished. The existing search command opts into a bounded NDJSON progress stream; ordinary API/MCP callers retain JSON. Request-local observers prevent concurrent searches from sharing events. Authentication, CSRF, permission checks, budgets, release records and final receipts remain authoritative.

Global download/maintenance banners and their rendering/styles were removed. Download status is available in Tasks / Downloads. Unknown submissions retain durable keys and read-only recovery; their pending notice appears only in the task center. Hiding presentation never retries or cancels backend work.

The application shell and task navigation persist across page changes. Discovery source/type/period controls, library category/search controls, download query/status controls and file-result filters stay available while their own results load. Shared compact selection groups replace oversized unrelated pills. Both languages fit 320/390/768/1440 widths. Unsupported source controls remain disabled. English ranking labels are concise without changing the all-time ranking API.

## Review and fixes

Self-review covered the actual behavior, module/branch necessity, standard-library/existing-client reuse, directory policy, credentials and the exact staged scope. It removed obsolete banner logic, duplicated task tabs and the obsolete library-filter dispatch. Existing loading/error handling is reused for task lists. Request ownership is centralized in `loadData` instead of a separate library-only counter. Obsolete reads cannot overwrite newer results, including a late background download refresh. Read-only selectors keep labels/focus while consent/mutation controls keep their locks. Review also fixed narrow English overflow, duplicate history buttons on refresh and file-filter errors that otherwise left a permanent spinner. Retrying a file filter preserves the selected filter.

No dependency, download identity, media naming, deployment topology or filesystem mutation logic changed. Existing unrelated delivery/FIFO edits were left unstaged. Private connection fields were checked against staged diffs; `pw.txt` was not transferred, archived, included in an image or committed.

## Validation

All checks ran serially at low CPU priority from a clean exported staged tree, excluding unrelated work:

- 36 Python checks: search progress, provider search, cloud execution, gateway authorization and language policy. SQLite/media fixtures use disposable directories.
- 22 JavaScript checks: release ordering/progress/parser, localization and request/reconnection helpers.
- `tests/manual/acceptance_navigation_browser.cjs`: stable shell/control identity and focus, scoped loading, delayed-response races for discovery/library/downloads/files, failure/retry, persistent task categories, retained input, no global banners and bilingual responsive rendering.
- `tests/manual/acceptance_season_workflows.cjs`: row preview/cancel/confirmation, immutable selected season, repeated taps, lost/invalid receipts, subscription cancellation, real site-event parsing and compact layouts.

The navigation browser also passed with actual public HTTPS HTML/JavaScript/CSS and intercepted API responses. Its optional `MEDIA_BROWSER_ASSET_ORIGIN` mode keeps every API request intercepted and sends no production mutation. Live verification separately denied anonymous progress requests without exposing site data. No production download, subscription, library mutation or push notification was created for acceptance.

## Deployment evidence

The clean cloud checkout fast-forwarded and ran the supported `sh setup.sh cloud up`. `media-cloud-cloud-web-1` and `media-cloud-cloud-mcp-1` are healthy on image `sha256:cbb86d27be7547fd34166d1c381519e4a620e2e2a9ba457dc434980f661b6d24`. Existing Jackett was reused. NAS workers and containers were not restarted.

Committed source and installed package bytes match both running containers; packaging intentionally omits legacy source tests. Gateway and public HTTPS responses match `app.js`, `app.css`, `i18n.js`, `releases.js`, `library.js`, `tasks.js` and `ux.js`. The cloud environment checksum is unchanged. Ports, domains, mounts and credentials were preserved. Release evidence is retained in the ignored cloud state release directory.

No manual rebuild remains for the public website; reload existing tabs. The supported command for repeating this cloud rebuild is `sh setup.sh cloud up`. The NAS built-in website was not rebuilt as part of this cloud rollout.
