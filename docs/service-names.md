# 两端服务与配置命名

网页入口在 cloud，拥有 SQLite 和媒体目录的控制 API 在 NAS。两端不再共用 `web`、`mcp` 这样的 Compose 服务名。

| 所属端 | Compose 服务 | 命令入口 | 职责 |
| --- | --- | --- | --- |
| local / NAS | `local-control` | `media-local-control` | 控制 API、用户与会话、SQLite、扫描与入库 |
| local / NAS | `local-worker` | `media-local-worker` | 下载调度、识别整理、字幕处理 |
| local / 传统单机 | `local-mcp` | `media-local-mcp` | 个人 LAN 或显式 platform MCP；`setup.sh local` 不启动它 |
| cloud | `cloud-web` | `media-cloud-web` | 网站静态资源、浏览器网关、搜索和到 NAS 的请求转发 |
| cloud | `cloud-mcp` | `media-cloud-mcp` | 具有用户身份的云端 MCP 入口 |

`qbittorrent`、`jackett` 是具名依赖，`init-*` 只负责所选内置依赖的初始化。已有 URL 非空时继续复用已有服务。

## 配置分组与旧名称

同一用途的新名称优先；新名称未填写或为空时，才回退到旧名称。旧 `.env` 不会被模板覆盖。

| 用途 | 新名称 | 兼容旧名称 | 默认 |
| --- | --- | --- | --- |
| cloud 网站监听 | `MEDIA_CLOUD_WEB_BIND` | `MEDIA_GATEWAY_BIND` | `0.0.0.0` |
| cloud 网站端口 | `MEDIA_CLOUD_WEB_PORT` | `MEDIA_GATEWAY_PORT`、`MEDIA_WEB_PORT` | `18214` |
| cloud MCP 监听 | `MEDIA_CLOUD_MCP_BIND` | `MEDIA_BIND_HOST` | 由既有反代模式决定 |
| cloud MCP 端口 | `MEDIA_CLOUD_MCP_PORT` | `MEDIA_MCP_PORT` | `18210` |
| cloud 本机 FRP 映射口 | `MEDIA_CLOUD_CONTROL_PORT` | `MEDIA_CONTROL_PORT` | split setup 默认 `28213` |
| cloud 高级控制 URL | `MEDIA_CLOUD_CONTROL_URL` | `MEDIA_CONTROL_URL` | 优先使用本机映射口 |
| cloud 缓存状态目录 | `MEDIA_CLOUD_STATE_PATH` | 无变化 | `./state-cloud` |
| cloud 镜像 | `MEDIA_CLOUD_IMAGE` | 无变化 | `media-mcp-cloud:local` |
| NAS 控制监听 | `MEDIA_LOCAL_CONTROL_BIND` | `MEDIA_WEB_BIND_HOST` | 模板 `192.168.8.1`；未显式配置的旧 local 为回环 |
| NAS 控制端口 | `MEDIA_LOCAL_CONTROL_PORT` | `MEDIA_WEB_PORT` | `18213` |
| NAS 媒体宿主机目录 | `MEDIA_LOCAL_DATA_DIR` | `MEDIA_DATA_DIR` | 模板 `/data`；无配置的旧部署兼容 `./data` |
| NAS SQLite 状态目录 | `MEDIA_LOCAL_STATE_PATH` | `MEDIA_STATE_PATH` | `./state` |
| NAS 镜像 | `MEDIA_LOCAL_IMAGE` | `MEDIA_IMAGE` | `media-mcp:local` |
| 传统单机 MCP 端口 | `MEDIA_LOCAL_MCP_PORT` | `MEDIA_MCP_PORT` | `18210` |
| 传统单机 MCP 监听 | `MEDIA_LOCAL_MCP_BIND` | Compose 的 `MEDIA_LAN_BIND`，直接命令的 `MEDIA_BIND_HOST` | LAN 模式默认 `0.0.0.0` |

新模板分为 cloud 网站、cloud MCP、cloud FRP/缓存、cloud 搜索，以及 NAS 控制 API、NAS 文件/SQLite、NAS 下载器、NAS 模型/字幕/通知。容器内 `MEDIA_DB_PATH`、`MEDIA_STATE_DIR` 是运行时路径，与宿主机挂载配置不同；下载根和整理根仍为 `MEDIA_DOWNLOAD_ROOT`、`MEDIA_LIBRARY_ROOT`，都只在 NAS 使用。

HTTP 会话、CSRF、反代和访问策略由控制 API 与网站网关共用，现有 `MEDIA_WEB_MODE`、`MEDIA_WEB_PUBLIC`、`MEDIA_ALLOWED_HOSTS`、`MEDIA_PROXY_IPS` 等保持原有语义。它们不是网站监听端口或媒体挂载项。账户、凭据文件和媒体任务身份不因命名变化而改变。

旧命令 `media-web`、`media-gateway`、`media-worker`、`media-mcp` 作为兼容别名保留。已有脚本可继续运行，新部署和文档使用表中的角色名称。MCP 工具的协议标识 `media-mcp` 保持兼容；HTTP 控制服务和网站网关的状态标识分别为 `media-local-control`、`media-cloud-web`。

## 更新已有部署

继续使用唯一 Docker 入口，在各自机器的项目目录执行：

```sh
# NAS：更新 local-control 和 local-worker
sh setup.sh local

# 云端：更新 cloud-web 和 cloud-mcp
sh setup.sh cloud
```

启动器先完成镜像构建，再通过 Compose 项目标签与实际工作目录识别旧的 `web` / `worker` / `mcp` 应用容器，停止并移除这些旧容器，随后启动新服务。不会使用 `down -v`，不会移除数据卷，也不会处理其他工作目录的容器。

已有 Compose project 标识 `media-standalone`（local）和 `media-cloud` 保持稳定，避免创建第二套依赖或改变现有部署归属；它们是兼容部署标识，不是应用服务名。比如 NAS 应用容器会变成 `media-standalone-local-control-1` 和 `media-standalone-local-worker-1`。已有下载器和 Jackett 不因应用服务改名而重建。

私有 `.env` 不必立即改名；若手动替换旧变量，请保持原值，尤其是媒体和状态目录。不能将真实媒体目录 `/data` 改成项目内的 `./data`。仅 `docker restart` 不会应用 Compose 服务名或环境变量变化。

状态和日志仍使用 `sh setup.sh local status/logs` 与 `sh setup.sh cloud status/logs`。初始化令牌的诊断命令现在在 NAS 使用 `local-control` 服务；文件仍叫 `web-bootstrap-token`，已有管理员和密钥保持不变。
