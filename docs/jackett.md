# Jackett indexer configuration

The bundled Jackett web entrypoint defaults to `http://host-LAN-IP:18212`; its container port is `9117`. Inside a container, localhost refers to that container.

## Website management

Administrators use **Settings / Jackett public sites**. The server filters the inventory to `public`; private and semi-private entries cannot be viewed or changed through this page. Search/filter the list by name, language or added/enabled status. Changes load only the site list, keeping filter controls available.

- **Add / Configure** loads supported nonsecret options and saves through Jackett's configuration API. Default settings are retained for other fields. Jackett may test as part of saving; a saved configuration is not proof of connectivity.
- **Enable / Disable search** controls Media searches and preserves the Jackett configuration. Preferences persist in the ignored state directory and apply to subsequent searches without rebuilding.
- **Test** runs Jackett's real indexer test and records a safe result/timestamp. Raw upstream errors, cookies and API keys are not exposed.
- **Remove** requires explicit confirmation and a fresh configuration revision. It removes only the selected public site's Jackett configuration. Downloads and library files are retained.

The cloud manages its own Jackett service. The NAS remains the source of fresh Media administrator and CSRF authorization. An execution-only NAS without a catalog bridge directs management to the cloud website. Existing LAN MCP authentication behavior is unchanged.

## Private management authentication

Torznab inventory/search uses the existing server-owned API key. Jackett's dashboard configuration/test/delete endpoints separately require its administrator login. Media uses a server-only session and reads `JACKETT_ADMIN_PASSWORD_FILE`, defaulting to `jackett-admin-password` beside the state database; an explicitly configured `JACKETT_ADMIN_PASSWORD` is also supported. The password file must be private (mode 0600) and ignored. Never commit it, show its contents, copy `pw.txt` into a build context, or send credentials through chat. If Jackett has no administrator password, its normal empty-password login is used; Media does not remove or change an existing password.

If the management credential is absent/expired, inventory and Media search preferences remain available, while configuration/testing/removal fail explicitly. Update the private credential and retry; no credential is returned to the browser. Jackett site-specific cookies/passwords/keys are not shown or edited in this public-only page. Sources requiring such credentials retain Jackett's existing requirements.

Media reads configured site files through the existing read-only mount. Manual API-key copying, Torznab feed copying and qBittorrent search plugins are unnecessary. Only downloads submitted through Media receive ownership labels; manually added downloader tasks are not adopted.

## Evidence of success

- **Test** validates one site request, not arbitrary keyword filtering.
- **Manual Search** verifies relevant results for your title.
- **Media search** verifies diagnostics and filtered candidates. `partial` means some sites failed or exceeded budget; `failed` means querying failed. Neither establishes that no release exists.
- **Download** requires an accessible torrent and peers; search success does not prove transfer availability or fresh login state.

Media searches original/localized names, restricts categories, filters known title/year/resolution mismatches and deduplicates. A movie release without a year can be excluded as `year_unconfirmed`. Site requests have 5-second timeouts and each title has a 20-second site scheduling budget. A timeout does not permanently disable the site.

## Networking, proxies and challenges

Check server/container DNS, egress, site URL and login expiry independently. Desktop browser access does not establish container access.

If using an existing authorized HTTP/SOCKS proxy, configure a container-reachable endpoint and credentials in Jackett. Host loopback is not another container's loopback. Do not disable TLS verification to hide errors.

For `Challenge detected but FlareSolverr is not configured`, this bundle does not include FlareSolverr. Prefer sources that work without it, or separately provision a compatible instance using official guidance. It adds resource cost and does not guarantee all challenges succeed. I2P/Tor egress is not bundled either.

See [official configuration](https://github.com/Jackett/Jackett#configuration) and [FlareSolverr configuration](https://github.com/Jackett/Jackett#flaresolverr-configuration). Media does not automatically install proxies/solvers or log in to sites.

| Symptom | Check |
| --- | --- |
| `configured_sites=0` | Add/save at least one site in the correct instance |
| Localized query returns latest uploads | Compare exact original-title search; unrelated results must be filtered |
| `jackett_timeout` | Inspect manual search, connectivity and challenge pages; use successful sources meanwhile |
| API/query failure | Inspect Jackett logs, config mount and login; never share key-bearing URLs |
| No download speed | Check peers, tracker errors, connectivity and disk, without duplicate submission |
| `indexer_redirect_not_allowed` | Valid magnets and bounded same-origin redirects work; external HTTP redirects remain blocked |
| New site never appears | Check `services/jackett/Jackett/Indexers/*.json` and whether you edited the wrong instance |

Rebuilds retain sites. Never commit `services/jackett/`, which may contain accounts, cookies, passkeys and API keys.
