# 云端搜索、本地执行

本轮目标：标准分离部署只让云端主动连接 NAS；NAS 不需要云端地址。沿用现有 FRP、HTTPS 反代和下载目录。

## 最终配置

- 云端 `MEDIA_CONTROL_PORT=28213`：云端本机 FRP 入口；内部固定连接回环 HTTP，不填写 URL。
- 网站 `MEDIA_WEB_PORT=18214`，MCP 默认 18210；域名和证书仍由已有反代管理。
- NAS `MEDIA_WEB_PORT=18213`：FRPC 的本机目标；标准 local 模式不设置 `MEDIA_CATALOG_URL`。
- 已有下载器、模型服务仍需其实际连接配置；这些是外部依赖，不属于云端与 NAS 之间的协议。
- 内部认证沿用自动配对；不因端口不公开而移除身份验证。

## 实现边界

1. 云端执行中英文作品搜索、榜单、详情、种子搜索及种子内容获取，网页和 MCP 共用流程。
2. 搜索结果留在云端，按登录用户隔离；提交到 NAS 的媒体身份、季度/集数和下载材料必须经内部认证、严格校验和大小限制。
3. NAS 为最终计划、权限、下载任务和数据库权威：重复媒体检查、计划版本、幂等键、任务归属、submission_unknown、租约与文件锁继续生效。
4. 种子在云端解析取得后交给 NAS；NAS 不获取云端 Jackett 的 URL。worker 的媒体识别路径也必须审计，避免处理阶段暗中回调云端。
5. 旧 URL 配置保留兼容通路，标准模板只展示端口；不让旧单机测试配置静默切换。

## 验收

使用一次性 SQLite、下载目录和硬链接目录，串行、低优先级运行。验证网页和 MCP 的相同用户隔离/撤销权限，拒绝伪造与过大下载材料，重复提交和断线不重复下载。禁止 NAS Provider 网络请求时，仍须完成搜索到计划、下载和入库链路。最终安装包重复验证，现有媒体和生产数据库不参与。

## 已完成与证据（2026-10-27）

| 要求 | 当前实现与验收 |
| --- | --- |
| 云端执行搜索 | 网页和 MCP 共用 `CloudCommands`，直接调用云端 TMDB/Jackett；云端 SQLite 按用户保存 release，NAS 不保存搜索候选 |
| 单向应用连接 | cloud 只填 `MEDIA_CONTROL_PORT`，内部固定回环；新 local 不再配置云端地址，默认 `MEDIA_EXECUTION_ONLY=true`，拒绝 TMDB、Jackett 与 Provider 回调 |
| 下载材料可独立执行 | cloud 获取 torrent 字节或 magnet，NAS 严格校验身份、集数、过期时间、大小和 infohash；worker 使用已冻结材料，NAS 记录中不保存云端 Jackett URL |
| 权限与安全状态 | 每次操作向 NAS 重新验证会话/令牌和下载权限；保留 CSRF、用户隔离、配额、计划版本、幂等键、submission_unknown、租约、任务归属和文件锁 |
| 最小部署配置 | `setup.sh`、两个 Compose、两份角色模板和部署文档已同步；保留旧 URL 的显式配置兼容和个人 LAN MCP 原默认行为 |
| 最终安装包回归 | 镜像 `media-mcp-cloud-execution-test:0.3.0`（`50f187550007`），断网、0.5 CPU、nice 15、串行运行 **118 项测试全部通过**；4 个 CLI 和 5 个网页资源打包验证通过，两份 Compose 模板解析通过 |
| 真实端口与 Provider | 独立 NAS 控制端 18613、cloud web 18614、cloud MCP 18610；没有设置两端 URL。真实 HTTP/MCP 中英文片名搜索、TMDB 详情、SIMKL 日榜成功；Jackett public `nyaasi` 两次查询返回 ok；NAS 自身搜索明确拒绝 |
| 真实榜单 | 安装包通过实时请求取得 SIMKL/TMDB 电影和剧集的日榜、周榜，共 8 组；检查来源更新时间与新鲜度，无真实媒体挂载 |
| 自动配对 | 通过端口 18613 首次获取私有凭据并完成认证确认；NAS 封闭首次配对入口；凭据摘要与封闭标记一致，不打印原始值 |
| 完整本地执行 | 最终镜像在 `state/cloud-execution-final-20261027` 的新数据库和新媒体目录内验收；云端准备材料 → 真实 qBittorrent v5.1.4 接收/校验 → 完成处理 → 硬链接 → 字幕落盘 → 持久化 completed。NAS Provider 调用 0，源 SHA256 不变，同 inode、链接数 2，字幕 1 |

真实 TCP 验收脚本：`tests/manual/acceptance_cloud_tcp.py`。完整执行链脚本：`tests/manual/acceptance_sqlite.py` 的 `MEDIA_ACCEPTANCE_CLOUD=true` 分支。保留的隔离证据核对：`tests/manual/verify_cloud_evidence.py`。单元/协议覆盖：`tests/test_cloud_execution.py`、`tests/test_split_ports.py` 及原有安全回归。

下载执行链使用可控元数据和模型结果，真实下载器验证本地生成的完整 torrent 内容；它不声称从公网 BT peers 下载了新影片。真实 Provider 查询另由 TCP 与榜单验收验证。所有 SQLite、下载目录、硬链接目录均为一次性隔离目录；本轮测试容器全部停止，保留证据，不改动 18414 主测试栈、现有媒体、生产下载器或旧 MySQL。新加坡真实服务器、反代证书和 FRP 配置不在本机验收范围内。

状态：实现及本地隔离验收完成。旧 MySQL 导入仍属于独立迁移工作，不由启动器自动完成。
