# Jackett indexer configuration

The bundled Jackett web entrypoint defaults to `http://host-LAN-IP:18212`; its container port is `9117`. Inside a container, localhost refers to that container.

## Add indexers

1. Open the correct new Jackett instance rather than an old service.
2. Choose **Add indexer**, filter by name/type, and add only sources you use and can access. Movie, TV and anime coverage differs.
3. Public sites may require an available base URL. Configure private credentials/cookies/passkeys locally; never send them or the API key through chat.
4. Save and **Test** each site. A configuration file alone is not evidence of availability.
5. Use **Manual Search** against only the new site with an exact title, trying localized and original names, such as the Chinese title of Interstellar and `Interstellar`. Check title, year and category.
6. Run `media_status` and `media_search_releases`. `configured_sites` is a configuration count; `diagnostics` describes actual per-site search outcomes.

Media reads the internal API key through a read-only configuration mount and queries sites individually. Manual key copying, Torznab feed copying and qBittorrent search plugins are unnecessary. Only downloads submitted through Media MCP receive ownership labels; manually added downloader jobs are not adopted.

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
