# Media MCP project

This directory is independently installable and deployable. Keep all runtime
imports under media_mcp; do not import the parent repository's apps package.
Use start.sh as the supported Docker entrypoint. Default MCP access is unauthenticated on private LAN addresses only. Do not add
login requirements to the LAN profile; optional OAuth/bearer modes are explicit choices.

Run tests serially at low CPU priority. SQLite acceptance requires a disposable state directory and media mount. Never point acceptance at real media.

Preserve submission-unknown fencing, job identity checks, SQLite lease ownership and filesystem mutation locks, hardlink source bytes, and version recovery. Do not adopt unrelated
qBittorrent tasks or add deletion capabilities through retry parameters.
Credentials belong in ignored .env/state files, never in Skill or tool output.
