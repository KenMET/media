# Independent Media delivery goal

Historical status: 0.2 implemented and accepted in a disposable stack; real sites and ChatGPT account integration still required target configuration.

Original objective: an independently relocatable personal LAN project, with one `./start.sh` launching Media MCP, workers, qBittorrent and Jackett; local SQLite and unauthenticated MCP restricted to private/loopback peers. That historical entrypoint has since been replaced by `setup.sh`.

Acceptance required independent `media_mcp` imports, no production adoption, no MySQL/password/MCP token/OAuth requirement, persistent bundled dependencies with automatic internal keys, deduplication/unknown reconciliation/atomic leases/OS locks/version recovery, a common data root with video hardlinks and reused subtitles, real SQLite concurrency/recovery and LAN HTTP tests, and isolated Docker acceptance. New Jackett still needed sites, and cloud ChatGPT still needed a network path.

See [acceptance index](../acceptance.md).
