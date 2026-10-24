# Media 独立交付 Goal

交付状态：0.2 已实现并完成隔离组合验收；真实站点与 ChatGPT 账号接入仍由目标环境配置。

当前目标：将整个目录作为可独立迁仓的局域网个人媒体项目，一条 `./start.sh` 启动 Media MCP、后台 worker、qBittorrent 与 Jackett；SQLite 本地持久化；默认 MCP 无认证，只接受私有 LAN/本机来源。

验收标准：

- 不导入原仓 `apps.*`；原生产服务和数据保持独立。
- 不需要 MySQL、数据库密码、MCP token 或 OAuth 登录。
- 内置下载器与索引器独立持久化，内部 API key 自动管理。
- 保留去重、结果未知对账、SQLite 原子任务租约、OS 文件锁与版本恢复。
- 下载和库共享数据根目录，视频通过硬链接入库，字幕继续复用已有实现。
- 有真实 SQLite 并发/恢复测试、LAN 无认证 MCP 测试，以及隔离 Docker 组合验收。
- 明确 Jackett 新实例仍需添加资源站，ChatGPT 云端仍需网络通路。

实际进度与证据见 [验收记录](../acceptance.md)。
