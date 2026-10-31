# Migration boundaries: 0.2 LAN bundle

For current read-only preflight and production reuse of legacy MySQL, downloader and hardlinks, see the [cutover plan](production-cutover-plan.md). This page records the original 0.2 extraction. Current `setup.sh` supports reusing dependencies through nonempty URLs, but no completed legacy MySQL importer is established here.

Use the [README](../README.md) and [operations guide](deployment.md) for current setup. The launcher does not provision third-party/model credentials.

The independent `media/` tree contains classification, naming, hardlinks, subtitles, persistent jobs, filesystem recovery, database, Codex and providers without importing `apps.*`.

Changes from the original 0.1 deployment:

- Local SQLite replaces bundled MySQL and database accounts.
- New qBittorrent/Jackett state persists under `services/`; the original 0.2 bundle no longer depended on old Jackett or manual internal keys.
- LAN MCP defaults to no authentication. Optional bearer/OAuth remains an explicit choice.
- New downloads default to `./data`, avoiding concurrent access with the original production processor.

At extraction, the active private `.env` changed accordingly while retaining TMDB, subtitle, Bark and Codex settings. Old settings were privately archived under ignored `state/env-backups/`, which the launcher does not load.

The original `apps/media`, database, downloader and NAS-Tools remain. Starting this project does not stop them or import their tasks, site logins or library records.

Before reusing old files, stop their writers and decide seeding ownership, mount roots and record import. MySQL data/DDL cannot serve as SQLite state. Production import and retirement are separate cutover operations. New downloads in new directories do not require legacy migration first.

SQLite, WAL and locks belong on a local filesystem. Workers must share database/lock paths. Never delete live locks or restore only one state file as a repair.

Do not commit `.env`, state, services, media or tokens when extracting source. Preserve those private directories appropriately during actual relocation; stop containers first.

Existing phone Remote and Codex runtime remain unchanged. Unauthenticated LAN MCP does not remove model-service authentication; credentials stay in files and need not be sent through chat.
