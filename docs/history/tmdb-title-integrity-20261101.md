# TMDB title integrity: 2026-11-01

The live Chinese TMDB top-rated response contained advertising domains in localized titles and, for some records, original titles. A same-ID English response supplied clean names for the screenshot's leading movies. This was provider metadata pollution, not website title concatenation. The observation does not establish who edited the upstream data or whether ratings were manipulated.

Runtime commit `9e2a440` detects obvious advertising domains after Unicode normalization, repairs damaged title fields from an identity-matched English response or a clean original name, and omits records with no usable name. A detail without a usable title fails rather than passing advertising into resource discovery. Clean Chinese names, provider IDs, dates, ratings, ordering and media filenames remain unchanged. English fallback is fetched once per affected response, not once per item. Ordinary domain-like film titles remain accepted. Versioned TMDB list/detail cache keys prevent previously polluted catalog snapshots from being reused without deleting existing state.

Self-review checked recursion termination, provider-ID matching rather than positional matching, translation outages, unrepairable fields, cache invalidation, existing-library reuse, directory policy and the exact staged diff. No dependency, authentication, download fence or filesystem behavior changed. Unrelated delivery/FIFO work and private connection material were excluded.

Validation passed 29 serial low-priority Python checks with disposable state: title-integrity regressions, catalog/cache behavior, resource search and language policy. Cases include obfuscated numeric domains, mismatched IDs, preserved Chinese names/ranking, unavailable translations, legitimate domain-like titles and rejection of old list/detail snapshots.

The cloud checkout fast-forwarded and used `sh setup.sh cloud up`. Both cloud web and cloud MCP containers are healthy on image `sha256:d5492e81b4856959361df3e7548ab29bbe70f34d798e5b46985d13eced090865`. Runtime source and installed package match the committed runtime; the environment checksum is unchanged. NAS containers were not rebuilt or restarted.

Read-only live provider verification returned 19 usable movie entries and 20 usable TV entries on the first top-rated pages, with no detected advertising left in title fields. The leading movies now use clean Batman, Avatar Aang and Swapped names. Clean Chinese TV names remain localized. This check did not change media state or create a download/subscription. It verifies the running adapter and fresh cache namespaces, not upstream metadata correctness beyond the checked fields.

No manual cloud rebuild remains; reload the website to request the new cache namespace. The supported cloud rebuild command remains `sh setup.sh cloud up`. Later test/report-only commits do not require another image rebuild.
