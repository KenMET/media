# Media MCP project

This directory is independently installable and deployable. Keep all runtime
imports under media_mcp; do not import the parent repository's apps package.
Use setup.sh as the sole supported Docker entrypoint. Default MCP access is unauthenticated on private LAN addresses only. Do not add
login requirements to the LAN profile; optional OAuth/bearer modes are explicit choices.

Run tests serially at low CPU priority. SQLite acceptance requires a disposable state directory and media mount. Never point acceptance at real media.

Preserve submission-unknown fencing, job identity checks, SQLite lease ownership and filesystem mutation locks, hardlink source bytes, and version recovery. Do not adopt unrelated
qBittorrent tasks or add deletion capabilities through retry parameters.
Credentials belong in ignored .env/state files, never in Skill or tool output.

## Required completion workflow for substantial changes

Before finishing any substantial change, review the final diff yourself and fix
the findings. Check that the design solves the actual problem, that each module
and branch is necessary, and that no duplicate or one-off runtime logic remains.
Prefer standard-library functions, existing dependencies and project clients over
new implementations. Add a dependency or abstraction only when it simplifies a
real requirement. Keep the implementation concise without weakening safety fences.

Check directory rules as part of that review: runtime code stays under
`src/media_mcp`, automated tests under `tests`, manual acceptance tools under
`tests/manual`, current guidance under `docs`, and dated reports under
`docs/history`. Reuse existing directories and keep documentation links valid.
Do not reorganize unrelated files or mix unfinished work into a completed change.

Run checks appropriate to the change, following the serial, low-priority and
disposable-state rules above. Inspect the exact staged diff for correctness,
unrelated changes and credentials. Then commit and push the completed, reviewed
scope to the existing branch and remote. This is standing authorization for
ordinary scoped commits and pushes; do not ask again solely to perform them.
Do not force-push, discard other work, or publish unfinished changes. Verify the
remote commit after pushing and report any failure honestly.

Preserve the configured ports, domains, credentials and deployment topology.
Use only `setup.sh` for necessary Docker rebuilds, update only affected services,
and wait for a safe checkpoint before restarting workers. Documentation-only
changes do not require a container rebuild. A successful push does not prove that
another host has rebuilt its image.

The final report must state the review findings and fixes, validation performed,
commit and push result, containers actually rebuilt, and any containers or other
steps the user still needs to handle manually. Give the existing supported command
for manual rebuilds and distinguish deployed evidence from pending deployment.
