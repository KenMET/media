# Inventory and mobile acceptance: 2026-10-28

Implemented administrator read-only disk preview, idempotent SQLite import, verified hardlink registration, independent media/subtitle indexes and missing/conflict states. Mobile gained four-entry bottom navigation, avatar account access, consistent cards/forms/type, bilingual UI and safe-area handling.

All validation used disposable media/SQLite and fictional providers, with no real downloader/media, deployment or production import. Python suite 135 passed; final inventory tests ten passed; frontend coordination/localization eight passed. Chromium/Playwright covered real HTTP login/discovery/preview/import/refresh/unverified subtitles/download/search/detail/account/admin/users/bilingual inventory. Widths 320/375/390/430/768/1440px showed no overflow or JS errors.

Verified original bytes/inodes, no acquisition adoption, idempotent repeated/rescanned imports, stale evidence rejection, permissions/CSRF/transaction rollback/device identity/lost locks, out-of-root/skipped preservation and existing review state.

See [inventory](../existing-media.md). Artifacts: `/tmp/media-ui-acceptance/result.json` and `python-tests.log`; preview stopped afterward. Private `.env` was unchanged; its `MEDIA_DATA_DIR=./data` mapped project data to container `/data`, not host `/data`. Production/MySQL cutover remained separate.
