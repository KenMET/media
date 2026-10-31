# Multiuser web and gateway security review

Later repairs addressed S1 shared login throttling, D1 broad admin binds, D3 server quotas and D2/D4 public/multiuser validation/guidance. Actual deployment was still LAN HTTP, not public TLS. See [cloud execution](cloud-execution-goal.md) and [current split guide](../split-deployment.md). Findings below retain their original review status rather than superseding later repairs.

Date: 2026-10-26. Read-only review of web/accounts/capabilities/gateway/local-remote MCP/Compose admin ports; no authentication configuration change, restart, real password attack, download or LAN scan. Used source, offline disposable reproduction and selected read-only runtime settings, not a full penetration/CVE audit.

## S1: shared gateway login-source bucket (medium)

Historical locations: `platform/api.py:211`, `platform/gateway.py:105–119`, `platform/accounts.py:121–133`. Local login keyed throttling by socket peer. Gateway lacked authenticated client provenance, making every user appear from one gateway IP. Ten failures blocked even correct logins until the 900-second source window expired; existing sessions remained.

Disposable installed-image/temporary-SQLite/InProcessHTTP reproduction simulated two different outer peers. First sent ten nonexistent-account failures, second valid admin login returned 429. No real account/service was attacked. Ignored script `state/security-audit-probe-20261026.py`.

Unauthenticated gateway visitors could temporarily deny login to others. Required actual socket-based gateway limits and authenticated dedicated provenance, trusted only from service-authenticated gateways, without trusting arbitrary X-Forwarded-For or removing source throttles.

## Deployment/resource findings

**D1: broad admin binds.** Historical `compose.yml:40,63`/`compose.cloud.yml:27` used 0.0.0.0 for downloader/Jackett, with LAN bypass, disabled downloader Host checks and no Jackett admin password (`bootstrap.py:47–58`). Actual exposure depended on firewall/security groups. The live test already bound admin 18411/18412 to loopback, so no public-admin exposure was established. BT data listening was separate. Cloud defaults needed loopback/protected administration.

**D2: HTTP.** Actual 18414 used `MEDIA_WEB_PUBLIC=false`, wildcard bind and no Secure cookie. HttpOnly/SameSite/CSRF did not encrypt credentials/sessions. Trusted LAN testing could continue; public/untrusted use required real HTTPS and Secure cookies, not Secure alone on HTTP.

**D3: absent server business budgets.** Search/acquisition/subtitle/token creation lacked account frequency/concurrency/count limits; UI locks did not constrain direct APIs. Different keys could consume disk/model/external budgets despite per-key idempotency. Source confirmed the gap without production load tests. Required queue/concurrency/admission limits and meaningful errors.

**D4: owner LAN MCP is a separate trust boundary.** Default `MEDIA_AUTH_MODE=none` (`compose.yml:84`) used unscoped owner MediaService, intentionally preserved. Untrusted direct callers bypassed ordinary web capability/private views. Restrict reachability or explicitly choose platform identity for multiuser use; web login alone did not protect every LAN entrypoint.

## Verified fences and recommendations

Accounts/sessions/CSRF/capabilities/ownership and constrained IDs/parameters are checked server-side. Acquisition/subtitles retain existing idempotency/locks. Real isolated protocol revocation returned HTTP 200 before token revoke and 401 on the next call, not merely a database assertion. Gateway/provider routes are allowlisted with independent service credentials plus user identity. Actual admin loopback binds were checked without revealing secrets.

No evidence established anonymous remote takeover or ordinary-web-to-admin escalation; that was not a vulnerability-free guarantee. Media tool sandboxing/root/host network/latest images/capacity remained in [earlier review](../security-review.md).

Original priority: repair S1 with cross-peer tests; restrict cloud administration/clarify MCP identity/provide HTTPS; add backend resource quotas. The initial review alone did not claim those recommendations were implemented; later status above records the subsequent delivery.
