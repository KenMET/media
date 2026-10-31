# Local/cloud service naming acceptance: 2026-10-28

Compose/entrypoints/status/health distinguish local-control/local-worker/local-mcp and cloud-web/cloud-mcp. Role-prefixed template variables retain old aliases. Setup builds before migrating only legacy application containers matching the same Compose project and actual working directory, retaining projects/dependencies/volumes. Explicit MCP role commands prevent opposite-role variables changing responsibility; generic `media-mcp` retains automatic selection.

Python 144 passed, covering alias precedence, binds, roles, private config preservation, matching-directory migration and unrelated-directory exclusion. Four local/cloud old/new Compose renders verified service names/ports/commands/media mounts, outputting selected fields only rather than credentials/environment dumps.

NAS `sh setup.sh local` exited zero. `media-standalone-local-control-1` and `media-standalone-local-worker-1` were healthy; old web/worker migrated. Control retained port 8109 and HTTP identity `media-local-control`. Mounts remained `/data -> /data` and original state -> `/state`. Fresh process read 807 mappings/2879 inventory and 100 initial media records. Five role commands and control/MCP/config installed hashes matched.

Private `.env` renamed only attributable variables with original values after configuration/SQLite backup and no active acquisitions. No secrets/state/backups committed. Cloud definitions/rendering were validated but runtime was not rebuilt; cloud still required `sh setup.sh cloud`. NAS evidence was not cloud deployment.
