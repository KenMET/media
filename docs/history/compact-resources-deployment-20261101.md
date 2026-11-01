# Compact resource browser cloud deployment: 2026-11-01

Outcome: cloud deployment and release verification completed. UI implementation is commit `4cfebb2`; private-file exclusion rules are commit `cddafba`. Later deployment-report changes do not require another image rebuild.

## Deployment

The existing cloud checkout was clean at `86ee5c6`. It advanced with a fast-forward pull to `cddafba`, then used the sole supported entrypoint, `sh setup.sh cloud up`. Existing environment files, Compose project, ports, state and bind mounts were retained. Both entrypoint readiness checks passed.

Rebuilt/recreated application containers:

- `media-cloud-cloud-web-1`: healthy.
- `media-cloud-cloud-mcp-1`: healthy.

Both use image `sha256:ed6a290a88d8efd6fc535b608c9f85878b37b3d5bf5cb11edefc8a9eae4daceb`. Existing Jackett remained running; local/NAS workers, reverse proxy, database and other services were not rebuilt. The cloud `.env` checksum was identical before and after deployment.

## Evidence and limits

All committed runtime source files were compared against each cloud container's build source and installed package. Installed-package checks exclude legacy test files that packaging intentionally omits. Both comparisons passed. The running gateway returned committed copies of `app.js`, `app.css`, `i18n.js`, `ux.js` and the new `releases.js` over its actual HTTP port. The existing public HTTPS reverse proxy also returned matching committed `app.js`, `releases.js` and CSS bytes.

Prior staged-source acceptance passed 46 focused Python tests, 19 serial JavaScript tests and the Chinese/English responsive browser workflow. The browser fixture covers automatic S03/S02/S01 packs followed by episodes, partial providers, long names, a collapsed long overview, explicit subscription season selection and widths 320/390/768/1440 with short phone viewports. Provider data in that browser workflow are mocked. Public deployment checks prove actual image/asset parity and health; no claim is made that a production user search or download was submitted during acceptance.

`pw.txt` was read only locally for authorized SSH authentication. The file itself was not uploaded, copied into the release or committed. It is mode 0600 locally and excluded by project Git and Docker ignore rules. Credential values are absent from this report and Git. No environment, account policy, media name, source bytes, hardlink or seeding state was changed by this UI deployment. Unrelated unfinished FIFO work remains excluded.

The cloud website is now on the reviewed resource-browser code. Reload existing browser tabs to load the new assets; no additional container rebuild is required for this release. Current behavior is documented in [resource browsing](../resource-browsing.md).
