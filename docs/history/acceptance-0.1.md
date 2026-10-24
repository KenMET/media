> 历史记录：0.1 的 MySQL/OAuth 验收。当前默认部署已改为 SQLite、内置下载器和 LAN 无认证，参见 [当前文档索引](../acceptance.md)。

# 独立 Media 验收记录

日期：2026-10-23。范围：代码提取、独立安装和镜像、MCP/OAuth/Skill、持久下载意图与整理/字幕链路。原生产服务和数据库未接管。

## 已完成

- 运行源码全部位于本目录，Python 包名 `media_mcp`，不导入原仓 `apps.*`。保留旧生产代码，独立包按 `source-manifest.json` 记录提取来源。
- `./start.sh` 在 OpenWrt 实际启动独立 Compose 项目，输出 loopback MCP 地址；启动失败不会输出“已启动”。随机凭据兼容 OpenWrt 的 openssl/hexdump，不依赖 od。
- 从干净的 `python:3.12-slim-bookworm` 构建独立镜像，未使用原 Phantom 镜像作为基底。Docker context 仅为 `media/`。
- 11 个工具与 Skill resource 可发现。实际 TCP Streamable HTTP 测试通过所有者浏览器登录、PKCE、MCP 调用与 token 撤销；未认证访问返回 401。
- 单元级 OAuth 测试覆盖错误 PKCE、授权码重复使用、服务重启后 token 保留、refresh 轮换与旧 access/refresh 失效、撤销、错误 redirect 与 CSRF。
- 单元测试覆盖下载提交超时后的只读对账、不重复提交、非本任务 torrent 拒绝、过期计划、冲突、幂等键、路径与作品/季集范围保护。
- 实际隔离 MySQL 8.4.13（默认镜像系列）、任务 claim/renew/旧 owner 拒绝、生成视频、规范路径、硬链接、中文字幕外挂和任务持久完成通过。下载 API 与媒体识别响应使用固定样本，不是一次真实资源站下载。
- 一次只读探针复用现有 Codex App Server，真实认证模型回合成功；新线程无继承 MCP 工具。随后隔离 worker 通过真实认证门禁，monitor/ingest/subtitle 三个心跳与容器健康均通过。未新增 Codex 登录或 runtime。
- 镜像中 ffmpeg、ffprobe、mkvmerge、mkvpropedit、tesseract、dotnet 和 PgsToSrt DLL 均存在。
- LikeC4 当前架构与独立项目视图同步更新，并通过 `likec4 validate docs/new`。

## 测试结果

串行、低 CPU 优先级执行：

| 检查 | 结果 |
| --- | --- |
| 迁出 ingest 回归 | 32 项通过 |
| 迁出 subtitle 回归 | 83 项通过 |
| 新增 MCP、OAuth、下载状态、路径、启动脚本与独立依赖检查 | 16 项通过 |
| 总计 | **131 项通过** |
| Skill quick_validate | 通过 |
| compileall / shell 语法 | 通过 |
| 真实 TCP OAuth + MCP | 11 个工具可用，撤销后 401；worker_ready 从 false 到真实门禁通过后的 true |
| 隔离 MySQL/文件链路 | completed，视频硬链接数 2，字幕记录/文件 1 |

`tests/acceptance_mysql.py` 与 `tests/acceptance_http.py` 仅允许标记的隔离环境：`MEDIA_ACCEPTANCE=isolated-container`、`MEDIA_DB_NAME=media_acceptance_*`、`/state/.acceptance`。数据库测试还要求 fresh acquisition 表。不要对真实库或真实挂载运行。

验收端口曾使用 `127.0.0.1:18219/mcp`，数据库仅 loopback `18316`，Compose 项目名 `media-mcp-acceptance`，文件挂载均在独立测试目录。此端口是测试入口，不是给 ChatGPT 的公网地址。隔离实例在验收结束后清理，不作为生产部署保留。

## 源码与镜像一致性

部署镜像内安装的 81 个运行时 Python 文件与本目录源码逐文件比对一致，排除测试和 Python 缓存；详情见 [runtime-receipt-0.1.json](runtime-receipt-0.1.json)。

- 镜像 ID：`sha256:315cd37f459f85bd3bbc27403a038ec63ed6b0f829c0c573d174f0f36bea1155`
- 运行源码 SHA256：`ae23d84753b7226ed5364f0bd0115385afb5cd373705c73d926f7e96553ad50e`

这是本轮构建验收收据，未来修改源码后应重新验证，不代表任何外部服务已更新。

## 尚未验收的外部条件

- 用户真实资源站、Jackett 配置、TMDB 配额与 qBittorrent 账号下的一次完整资源搜索和真实下载；本轮未提交真实下载。
- 用户 ChatGPT 账号中的安装、授权、手机端操作，以及稳定 HTTPS 或 Tunnel 的实际可达性。协议层通过不能替代账号端验收。
- 在线字幕供应商当前网络、额度及特定发行版适配；PGS OCR 和可选 ASR 的真实长片质量。ASR 默认关闭。
- 追更、强制版本替换、删除、媒体服务器刷新、Portal 新入口不在本版工具范围。
- 旧媒体数据库与 NAS-Tools 配置的正式迁移、唯一写入者切换和旧服务停用；按 migration.md 独立安排。

部署时先填写本机 `.env`，确认目录与下载器路径一致，再配置私网/HTTPS 接入。不要把测试通过解读为现有 NAS-Tools 已经被关闭，或把 MCP 启动解读为所有外部来源已可用。
