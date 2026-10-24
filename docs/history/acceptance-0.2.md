# 0.2 局域网组合验收（历史收据）

以下数量、镜像 ID 和源码哈希对应当时隔离实例，不代表后续修改后的当前镜像。后续安全与文档检查见 [当前安全检查](../security-review.md)。

日期：2026-10-24。当前默认方案为 SQLite + 内置 qBittorrent/Jackett + LAN 无认证。旧的 MySQL/OAuth 默认方案见 [历史记录](acceptance-0.1.md)，不再作为启动要求。

## 已完成

- `start.sh` 一条命令构建 Media、初始化服务配置并启动四个常驻服务：MCP、worker、qBittorrent、Jackett。没有 MySQL 容器或数据库账户。
- SQLite 3.40.1，WAL + FULL synchronous + busy timeout。任务 claim 使用 `BEGIN IMMEDIATE`，租约过期接管与旧 owner 拒绝已验证。
- 使用同一状态目录下的 OS 文件锁替代 MySQL advisory lock；进程崩溃释放锁、锁文件被替换时拒绝继续、外部 I/O 后的过期快照拒绝已验证。
- 原有版本交换日志已迁为 SQLite 原生 SQL，真实文件与数据库的升级、字幕归档和发布失败回滚通过。
- 从真实局域网客户端无凭据调用 TCP Streamable HTTP，11 个工具正常，完成任务可查询；MCP 只按实际 peer 的私有网段放行，公共 peer 的伪造转发头在测试中被拒绝。实际 Uvicorn 关闭 proxy_headers。
- 内置 Jackett 自动生成/保留 API key，Media 从只读配置读取；真实 caps 请求返回 HTTP 200 和 caps XML，无需人工填写 key。
- 内置 qBittorrent 无人工账号配置即可在本机/白名单 LAN 使用。真实 API 添加隔离 torrent、校验已存在的样本视频 payload，并报告完成文件；没有外部电影下载或对原下载器的操作。
- 同一隔离链路通过真实 SQLite、ffmpeg 生成视频、作品识别固定响应、命名、硬链接、字幕处理，最终 completed。视频 link count=2，字幕记录与文件=1。
- 镜像替换后 SQLite 中完成记录保留；后台 worker 通过真实现有 Codex 的模型认证启动门禁，三个心跳与四个容器 health 均通过。
- 旧生产 Media、Portal、MySQL、Quant、Crawler 和已有下载器没有停止、重建或改配置。

## 自动化验证

| 项目 | 结果 |
| --- | --- |
| ingest 回归 | 32 项通过 |
| subtitle 回归 | 83 项通过 |
| SQLite 并发/恢复、bootstrap、MCP、LAN、可选认证与入口测试 | 25 项通过 |
| 合计 | **140 项通过** |
| Skill quick_validate | 通过 |
| LikeC4 `validate docs/new` | 通过 |
| shell 语法与 Python 语法 | 通过 |
| 最终镜像与源码 | 83 个运行文件逐文件一致 |

SQLite 多进程测试是为任务领取和 OS 锁竞争而设的小范围测试，测试套件仍串行执行。没有运行 Quant/Crawler 全量套件。

镜像 ID：`sha256:dc228c1a8fcbd6612f547809126896ccaad81b480458449f004a14620348fb76`。
运行源码 SHA256：`bc525c40b4c852cf38bc0766674629cd2d2a5385333c673fd4c2c3169ec00091`。
完整收据见 [runtime-receipt-0.2.json](runtime-receipt-0.2.json)。镜像中没有 PyMySQL。

## 隔离条件

验收项目名 `media-lan-acceptance`，临时入口为 MCP 19210、qBittorrent 19211、Jackett 19212，torrent 端口 49181；持久数据和两个软件的配置均位于独立测试目录。验收后清理此实例，不把临时地址作为生产服务保留。

`tests/acceptance_sqlite.py` 只允许 `MEDIA_ACCEPTANCE=isolated-container`、容器内数据库路径 `/state/media.sqlite3` 与 `/state/.acceptance` 标记，且要求 fresh acquisition 表。`MEDIA_ACCEPTANCE_QBIT=real` 使用专用验收下载器，不对生产实例运行。

## 仍需实际使用时配置/验证

- 新 Jackett 的资源站。验收实例为全新配置，`configured_sites=0`；需用户在 Jackett 页面添加自己的站点及必要登录。
- 实际站点搜索、外部资源传输速度、在线字幕额度和长片 OCR/翻译质量。本轮没有从资源站下载真实电影。
- 用户的 ChatGPT 插件安装与私网网络通路。本地 MCP 无认证不意味着 OpenAI 云端能直接访问 LAN 地址。
- 原有媒体记录或旧下载任务的正式导入与旧服务退出。本轮默认新目录，不自动接管。

当前活动 `.env` 已切换新组合，保留原有 TMDB/字幕/Codex/Bark 配置；不再要求数据库密码、MCP token、所有者密码或手工 Jackett key。旧 profile 私有备份于忽略的 `state/env-backups/`。
