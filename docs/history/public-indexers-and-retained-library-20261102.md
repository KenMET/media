# Public indexer settings and retained-library feedback: 2026-11-02

Status: implementation and isolated acceptance in progress. Deployment and live authenticated management acceptance are pending; this is not a completion report.

## Scope and decisions

- Refresh processing-stage snapshots on authorized task reads. Show physically verified existing hardlinks, retained-new-version reasons, identity review and zero-media subtitle stages explicitly without changing persisted task/quality/lease decisions.
- Add an administrator-only Settings / Jackett page. Public inventory comes from Jackett's authenticated Torznab inventory, with private/semi-private entries filtered on the server. Public-only enforcement repeats for every operation.
- Support supported nonsecret configuration options/default addition, explicit configuration-revision-fenced removal, real Jackett testing and a separate persistent Media search toggle. Disabling retains configuration; removal deletes only the chosen site's configuration.
- Keep the API key, administrator login, cookie session and hidden/site credentials server-side. Fresh NAS administrator/CSRF authorization gates cloud mutations. No new LAN MCP login requirement, provider topology, ports or domains.

## Current evidence

Read-only production diagnosis found the screenshot's new movie candidate unlinked as `quality_not_comparable`, with a physically present existing version. The persisted subtitle stage had already succeeded with media_count=0 while the acquisition still held an older processing snapshot. Current UI/API changes address those distinct facts rather than treating subtitle absence as the cause.

Live Jackett inspection found 618 total indexers with public/private/semi-private classification and configured flags. Torznab inventory succeeds with the existing server key. Dashboard administration redirects to login: an administrator password is set, but no management password is configured in the Media environment. The user has been asked asynchronously for a private credential location, not a password in chat. Implementation supports a private state file; no credential or indexer configuration has been changed for production acceptance.

Isolated checks currently cover retained-link identity/path boundaries and unchanged bytes, private-site rejection, secret-field filtering, config revision/confirmation, persistent search exclusion, safe test results and administrator/CSRF gates. A browser harness covers existing-library feedback, current zero-media subtitle status, filters, toggle/test/add/remove, double-click and cancel/Escape fencing, missing management credentials, admin visibility and bilingual 320/390/768/1440 layouts. These are injected/disposable checks, not live management proof.

## Remaining completion gates

Review/fix the exact scoped diff, rerun required serial low-priority checks from a clean staged tree, configure authorized private Jackett login without exposing/transferring `pw.txt`, and verify live administrator inventory/testing. Commit/push only the completed scope, leaving unrelated FIFO work untouched. Deploy the NAS control service only through `sh setup.sh local control` from a clean source snapshot with unchanged mounts/configuration; workers need no restart for read-only feedback. Deploy cloud services with `sh setup.sh cloud up`. Verify source/package/public asset parity, live task feedback and management behavior before completing the Goal.

Primary API reference: [Jackett indexer controller](https://github.com/Jackett/Jackett/blob/master/src/Jackett.Server/Controllers/IndexerApiController.cs). Authentication follows [Jackett's dashboard login](https://github.com/Jackett/Jackett/blob/master/src/Jackett.Server/Controllers/UIController.cs).
