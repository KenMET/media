# Public indexer settings and retained-library feedback: 2026-11-02

Status: completed. Implementation, deployment, isolated acceptance and live authenticated public-indexer management acceptance passed.

## Scope and decisions

- Refresh processing-stage snapshots on authorized task reads. Show physically verified existing hardlinks, retained-new-version reasons, identity review and zero-media subtitle stages explicitly without changing persisted task/quality/lease decisions.
- Add an administrator-only Settings / Jackett page. Public inventory comes from Jackett's authenticated Torznab inventory, with private/semi-private entries filtered on the server. Public-only enforcement repeats for every operation.
- Support supported nonsecret configuration options/default addition, explicit configuration-revision-fenced removal, real Jackett testing and a separate persistent Media search toggle. Disabling retains configuration; removal deletes only the chosen site's configuration.
- Keep the API key, administrator login, cookie session and hidden/site credentials server-side. Fresh NAS administrator/CSRF authorization gates cloud mutations. No new LAN MCP login requirement, provider topology, ports or domains.

## Current evidence

Read-only production diagnosis found the screenshot's new movie candidate unlinked as `quality_not_comparable`, with a physically present existing version. The persisted subtitle stage had already succeeded with media_count=0 while the acquisition still held an older processing snapshot. Current UI/API changes address those distinct facts rather than treating subtitle absence as the cause.

Live Jackett inspection found 618 total indexers with public/private/semi-private classification and configured flags. Torznab inventory succeeds with the existing server key. Dashboard administration redirects to login: an administrator password is set, but no management password is configured in the Media environment. The user has been asked asynchronously for a private credential location, not a password in chat. Implementation supports a private state file; no credential or indexer configuration has been changed for production acceptance.

The clean staged snapshot passed 44 backend tests, 22 JavaScript tests and three browser suites (indexer settings, navigation and download/subscription confirmation). An additional 15-test serial backend run covers the lazy-key regression found during live acceptance. Isolated checks cover retained-link identity/path boundaries and unchanged bytes, private-site rejection, secret-field filtering, config revision/confirmation, persistent search exclusion, safe test results and administrator/CSRF gates. A browser harness covers existing-library feedback, current zero-media subtitle status, filters, toggle/test/add/remove, double-click and cancel/Escape fencing, missing management credentials, admin visibility and bilingual 320/390/768/1440 layouts. These are injected/disposable checks, not live management proof.

## Deployment and review evidence

Commit `d0620c2` was pushed and verified against origin/main. NAS control was rebuilt through `sh setup.sh local control` from an archived committed tree, excluding unrelated FIFO changes. Cloud MCP and web were rebuilt through `sh setup.sh cloud up`. The NAS worker image/start time remained identical; control environment hashes and effective mount sources/permissions matched the baseline. The state bind uses a release-local symlink resolving to the original state directory. Cloud `.env` checksum remained unchanged.

All 152 source files and 133 installed runtime/package files matched the committed tree in the three updated containers. The public browser passed the indexer/retained-library acceptance suite using live assets and injected APIs; it did not mutate production indexers. A live read-only task query verified retained_count=1, quality_review=true, explains_review=true and subtitle_no_media=true for the reported movie.

Review covered server-side public filtering, administrator/CSRF gates, private-field suppression, revision/confirmation fencing, preserving worker and quality decisions, and modal ownership during navigation. A real first-inventory request exposed a lazy API-key initialization ordering bug; initialization now precedes request construction, with a regression using a private disposable config file. Correction commit `318c154` was pushed, verified against origin/main and deployed to NAS control plus both cloud services using the same supported setup commands. Final source/package parity passed in all three containers, control environment/effective mounts remained identical, and the worker image/start timestamp remained unchanged. Live public inventory returned 100 public sites, 7 configured and enabled. A read-only configuration request reached the explicit `jackett_admin_auth_required` gate, confirming that authenticated administration was still pending at that checkpoint.

## Final authenticated acceptance

The user authorized trying default credentials. A bounded login check succeeded without exposing, transferring or changing `pw.txt`; that file remains local to authorized SSH authentication. The working credential was saved only on the cloud server beside the state database in `jackett-admin-password`, mode 0600. No Jackett password was reset, no deployment configuration changed, and no credential was placed in code, documentation, browser responses or Git. Both cloud services read the shared private state file without a rebuild.

Live authenticated acceptance used the deployed `JackettAdmin` implementation: Knaben connectivity passed; an initially unconfigured public Nyaa entry was added, disabled/enabled in Media search, tested successfully, and removed using its fresh revision and explicit confirmation. Cleanup was guarded in a finally block and applied only to the newly added site. SHA-256 fingerprints confirmed that every pre-existing indexer configuration file remained byte-identical; the configured inventory returned to the original seven sites. No download or media mutation was performed.

Runtime inspection confirmed the bundled cloud Jackett uses a Docker bridge with its published port bound only to loopback, rather than host networking. Its dashboard password and port mapping remain unchanged. No manual rebuild remains: existing private-state credential loading is dynamic. All completion gates above are satisfied.

Primary API reference: [Jackett indexer controller](https://github.com/Jackett/Jackett/blob/master/src/Jackett.Server/Controllers/IndexerApiController.cs). Authentication follows [Jackett's dashboard login](https://github.com/Jackett/Jackett/blob/master/src/Jackett.Server/Controllers/UIController.cs).
