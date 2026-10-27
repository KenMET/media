# 部署、更新与运维

快速首次使用按 [README](../README.md) 顺序执行。本页所有命令默认在服务器的 `media/` 目录执行，不在 Windows 客户端执行 Linux 部署命令。

已有反向代理和私有 FRP 时，优先使用 [两端精简部署](split-deployment.md) 与角色专用 `.env` 模板；新 cloud 默认只接受本机反代，不需要重复域名配置，并自动建立内部认证。两端连接只填 `MEDIA_CONTROL_PORT`，NAS 不配置云端地址；搜索和种子获取全部在 cloud。本页下方依赖组合与显式 `MEDIA_WEB_PUBLIC=true` 的域名/TLS 校验是保留的传统单机/高级模式，并非新模板必填项。

## 配置表

### 复用已有下载器和 Jackett

在各服务所属角色内分别判断：URL 填写非空地址时连接已有服务；URL 未配置或为空时，初始化并启动对应内置容器，使用默认本机端口。新 local 只负责下载器，cloud 只负责 Jackett；传统单机支持任意混合组合。例如复用已有服务：

```dotenv
QBITTORRENT_URL=http://实际主机地址:8080
QBITTORRENT_USERNAME=你的用户名
QBITTORRENT_PASSWORD=你的密码
JACKETT_URL=http://实际主机地址:9117
MEDIA_JACKETT_CONFIG_DIR=/服务器上的已有Jackett配置根目录
```

凭据只保存在私有 `.env` 中；下载器允许无认证访问时可省略用户名和密码。Jackett API key 默认从只读配置读取，也可显式填写 `JACKETT_API_KEY`。URL 不要包含凭据。

然后用 `sh setup.sh`。例如只填 `QBITTORRENT_URL`、留空 `JACKETT_URL`，就复用下载器并自动启动 Jackett。指定的外部服务不可达时报告失败，不回退启动另一个容器。logs/stop 仅管理 MCP、worker 和当前选中的内置依赖。切换到外部地址不会自动停止旧的内置容器；若需退役请显式处理并保留持久数据。URL 使用简单的、无引号的完整地址，不要加行尾注释；宿主机同名环境变量优先于 `.env`。

复用已有 Jackett 时，当前站点列表来自配置文件，配置根目录必须包含 `Jackett/ServerConfig.json` 和 `Jackett/Indexers/`。该目录只读挂载；缺失时搜索会报告未配置或没有站点。只有远程 URL/API key 还不够。本段描述传统单机模式；local/cloud 分组部署见 [同机测试说明](platform-testing.md)。

`MEDIA_DATA_DIR` 是宿主机挂载到容器 `/data` 的目录。下载器返回的文件路径必须在 worker 中原样可用；默认 `/data/downloads`，可通过 `MEDIA_DOWNLOAD_ROOT` 指定 `/data` 下其他路径。当前没有路径翻译功能。下载根与库根（默认 `/data/media_hub`，可设 `MEDIA_LIBRARY_ROOT`）必须支持同一文件系统硬链接。容器使用 host 网络，URL 中 localhost 指部署服务器本身，其他容器应使用宿主机发布端口或实际可达地址。

`.env.example` 只列日常必需配置和外部服务接入项。下面的高级配置仍可自行加入 `.env`，省略时使用原有默认值；精简模板不会覆盖或清理已有 `.env`。

`.env` 从 `.env.example` 复制。不要用 `source .env` 来加载配置；Compose 会读取它。当前启动器用简单的 `KEY=value` 读取路径和端口：不要为这些值加引号、变量引用、行尾注释或空格。使用实际绝对路径或 `./相对路径`，避免路径包含空格。

| 配置 | 默认 / 说明 |
| --- | --- |
| `QBITTORRENT_URL` | 省略或空值自动启动对应容器；填写后连接已有服务 |
| `QBITTORRENT_USERNAME` / `QBITTORRENT_PASSWORD` | 默认空；使用已有下载器认证 |
| `JACKETT_URL` | 省略或空值自动启动对应容器；填写后连接已有服务 |
| `JACKETT_API_KEY` | 可选，默认读取挂载配置 |
| `MEDIA_JACKETT_CONFIG_DIR` | 仅传统单机使用，默认 `MEDIA_SERVICES_DIR/jackett`；cloud 固定 `/root/container_cache/jackett/config`，无需此变量 |
| `TMDB_API_KEY` | 必填；作品/年份/季集元数据查询 |
| `CODEX_APP_SERVER_URL` | `ws://127.0.0.1:8108`；既有适配模型服务，不由本项目安装 |
| `CODEX_TOKEN_FILE` | `./state/codex-token`；宿主机 token 文件，必须与模型端点匹配，不能为空 |
| `MEDIA_STATE_PATH` | `./state`；本机 SQLite、WAL、SHM、锁及日志目录 |
| `MEDIA_DATA_DIR` | `./data`；完整下载/库根目录，容器内统一为 `/data` |
| `MEDIA_SERVICES_DIR` | `./services`；内置依赖的持久配置目录 |
| `MEDIA_LAN_BIND` | `0.0.0.0`；个人 LAN MCP 监听地址；调整时保留本机健康探针可达 |
| `MEDIA_ADMIN_BIND` | `127.0.0.1`；内置下载器/Jackett 管理端口独立绑定。公网模式启动器仅允许本机绑定 |
| `MEDIA_LAN_IP` | 可选；只改变启动打印的访问地址，不改变监听或防火墙 |
| `MEDIA_LAN_CIDRS` | 可选，逗号分隔 MCP 实际客户端来源网段；默认私网/本机。收窄时保留 `127.0.0.0/8,::1/128` 给健康检查 |
| `MEDIA_ALLOWED_HOSTS` | 可选，逗号分隔准确 DNS 主机名，例如 `media.home`；不含协议、端口、路径，不支持通配符。LAN IP 和 localhost 无需填写 |
| `MEDIA_MCP_PORT` | `18210`；HTTP MCP，路径 `/mcp` |
| `MEDIA_QBITTORRENT_PORT` | `18211`；下载器管理/API 端口 |
| `MEDIA_JACKETT_PORT` | `18212`；Jackett 管理/API 端口 |
| `MEDIA_TORRENT_PORT` | `48181` TCP/UDP；仅内置下载器的 BT 数据端口 |
| `PUID` / `PGID` | `0` / `0`；内置依赖文件属主；不修改外部依赖配置，不是 MCP/worker 的非 root 开关 |
| `TZ` | `Asia/Shanghai` |
| `OPENSUBTITLES_API_KEY`、`SUBDL_API_KEY`、`ASSRT_API_KEY` | 对应可选字幕服务凭据；仍受各自额度、认证和可用性影响 |
| `BARK_URL` | 可选完整设备推送 endpoint；为空只写通知日志，不会推送到手机 |
| `SUBTITLE_SYNC_MODE` | `required`；同步不成功不当作已同步，可选 `auto`、`disabled` 会降低对齐保证 |
| `SUBTITLE_ENABLE_AUDIO_ASR` | `false`；改 true 不会自动安装或下载 ASR 模型 |
| `INSTALL_OCR` | `true`；镜像构建时安装 PGS OCR 工具；改动需重建 |
| `MEDIA_AUTH_MODE` | 传统单机默认 `none`；可选 `bearer`/`oauth` 单所有者认证或 `platform` 网页账号个人令牌，仍受 LAN 中间件限制。cloud 分组自动使用个人令牌认证 |

可选认证：bearer 模式还需服务端 `MEDIA_MCP_TOKEN`（至少 32 字符）；OAuth 需 `MEDIA_PUBLIC_URL` 和 `MEDIA_OWNER_PASSWORD`（至少 24 字符）。这些是另一个显式部署选择，不是快速开始的必填项；选择认证也不会自动提供 TLS、隧道或公网网络通路。不要在聊天中传入密钥。

目录设置在首次下载前确定。更改 `MEDIA_DATA_DIR`、容器内路径、PUID/GID 或数据库位置，不等于已经迁移已有任务路径和文件权限。本启动器不初始化已有下载器或 Jackett；调整权限前需检查已有文件归属。

## 模型连接检查

模型运行时没有本项目支持的内置部署镜像，不参与上述自动容器选择。`CODEX_APP_SERVER_URL` 未配置或为空时连接默认兼容端点 `ws://127.0.0.1:8108`，仍需你提前部署并提供匹配凭据。TMDB/字幕服务的 API key 为空也不代表能自动启动这些外部平台。

MCP/worker 采用宿主机网络；因此默认模型地址的 `127.0.0.1` 是服务器自身。若模型运行于另一台主机或容器，使用服务器能访问的实际端点，不能假设本机端口相同。

所需的是本项目适配的 WebSocket App Server 协议和 bearer 认证入口，不是任意聊天网页、REST API 或直接运行一个未适配的同名服务。本目录没有自包含的模型服务部署脚本；迁到新主机必须先提供这个外部依赖。缺少它仍能启动网页/MCP，但 worker 不会进入正常提交/处理状态。

检查 `sh setup.sh logs` 中的模型认证、硬链接探针和 worker 心跳。`token_missing`、`token_unreadable`、`token_rejected` 分别检查空文件、可读权限和 token 是否匹配端点。不要打印 token 排错。默认占位空文件只用于让其他服务能启动，不代表已完成模型配置。

## 网络与访问边界

MCP/worker 使用 host network。下载器/Jackett 的网络由各自部署管理；默认回环 API 地址要求对应端口可在服务器本机访问。不要为排错同时改多个网络选项。

- 默认免登录信任私有网段客户端；私网地址不是用户身份。访客 Wi-Fi、其他 VPN 用户和其他容器是否可达，也必须考虑。
- MCP 不信任转发头，检查实际 socket 来源；Host 只接受 LAN IP、localhost 或明确配置的主机名，浏览器 Origin 必须匹配 Host。
- 自定义域名或反向代理需设置准确 `MEDIA_ALLOWED_HOSTS`，保留 Host，并确认客户端身份和网络隔离。添加域名不等于授权公网访问。
- 管理端口 `18210/18211/18212` 不做路由器公网转发，不通过不受信任代理暴露。防火墙只允许受信任设备/网段。
- `48181` 是 BT 数据端口，是否需要入站连接由网络情况决定；开放它不能替代配置资源站，也不应顺带开放管理端口。
- 客户端不支持云端访问 LAN 时，先解决受保护的网络通路，不要通过把默认服务暴露公网来解决。隧道/代理可能让外部请求显示为本机来源，LAN 判断不能代替该通路的身份认证。

下载器与 Jackett 的独立管理页面**不经过 MCP 中间件**。已知限制和安全建议见 [安全检查](security-review.md)。

## 如何检查每一步

| 检查 | 能说明什么 / 不能说明什么 |
| --- | --- |
| `/healthz` 返回 ok | MCP HTTP 进程可用；不代表模型、Jackett、字幕、推送均正常 |
| `sh setup.sh status` | 容器状态/健康检查；不直接说明某个任务成功 |
| `media_status` | worker 心跳、凭据/站点存在；不验证外部搜索效果 |
| Jackett Test + Manual Search | 单站连接及具体词搜索效果；不保证种子传输速度 |
| `media_get_job` | 指定任务各阶段的实际状态，是进度依据 |
| 字幕 `content_verifications` | 已记录的内容校验与对白覆盖率；来源标签和 handled 数量不能代替它 |
| `notifications.jsonl` | 后端写入通知事件；存在记录不等于手机送达 |

MCP 请求成功或拿到 job_id 只表示已提交。下载完成、视频硬链接入库、字幕完成分别判断。

## 更新和正常停止

```sh
sh setup.sh status
sh setup.sh logs
sh setup.sh stop
sh setup.sh
```

`setup.sh` 构建 Media 镜像，再更新所属分组，并初始化、启动未指定 URL 的内置依赖。启动器不删除持久目录，不停止父项目 Quant/Crawler。每次更新按顺序运行，不在资源紧张的服务器上同时构建、测试多个项目。

外部第三方服务由其自身部署管理；内置服务可通过 `QBITTORRENT_IMAGE`、`JACKETT_IMAGE` 选择镜像，更新前先备份再显式拉取固定版本或 digest。默认 latest 不等于可重现版本。不要把“重建 Media”当作“所有第三方组件已更新且无漏洞”。

不要执行 `docker compose down -v` 或清空 `state/` 来修复任务。容器日志会轮转；发布前保留原始错误码和阶段，分享日志时脱敏。

## 备份、迁移与恢复

下面是**默认目录布局**示例。若改过路径，把配置中的实际目录加入备份清单。将备份写到本机已有且空间足够的私有目录，归档不放在被打包目录内：

```sh
sh setup.sh stop
umask 077
tar -cpf /你的私有备份目录/media-state.tar .env state services
# 视频、做种源文件、字幕另行备份；需要完整可恢复备份时也必须包含 data。
```

`.env`、token、站点 cookie/passkey、数据库与归档均视为私有。仅备份元数据不能恢复丢失的视频。先停止所有写入者，再拷贝数据库所在整个状态目录；不要只复制运行中的 SQLite 主文件遗漏 WAL。若有其他共享目录写入服务，也先停止它们。

恢复时在空的目标目录保留正确权限，恢复匹配版本代码、配置及所有实际持久目录，确认本机路径和模型服务可达，再运行 `sh setup.sh`。不要覆盖正在运行的状态。更换目录、UID 或数据路径后要先检查权限和任务中的路径，不能承诺无需迁移就直接续传。回滚需使用对应旧镜像/代码与一致的状态备份，不要只回退一个 SQLite 文件。

## 常见错误

### 安全入口与服务端配额（2026-10-26）

多人使用前明确身份边界：网页角色只约束网页及 platform MCP。默认个人 LAN MCP 仍免认证，并可访问无账户范围的任务；限制该端口的可达设备。若独立部署需要统一网页/MCP 身份，显式设置 `MEDIA_MULTI_USER=true`、`MEDIA_AUTH_MODE=platform`。`setup.sh local` 只起控制与 worker，不额外启动免认证 MCP；cloud MCP 本身要求可撤销的用户令牌。

内置下载器、Jackett 管理页默认只绑定回环地址，需要管理时可通过已认证的 SSH 隧道或受保护管理入口访问。`MEDIA_ADMIN_BIND` 与 MCP 监听分开；不要为图方便直接将管理页发布到公网。外部已有服务的地址/认证不由本项目自动修改。

正式公网网页请配置 `MEDIA_WEB_PUBLIC=true`、`MEDIA_WEB_PUBLIC_URL=https://media.example.com`、`MEDIA_ALLOWED_HOSTS=media.example.com`。公网模式验证 HTTPS 源与允许域名，并设置 Secure cookie；TLS 证书、域名和反向代理需实际配置，不由该变量自动创建。将网页后端绑定回环地址（`MEDIA_WEB_BIND_HOST=127.0.0.1`），不要公网发布裸 HTTP 后端。cloud MCP 同样应通过 HTTPS 反代访问，将 `MEDIA_BIND_HOST` 绑定到反代可达的受限地址。当前 LAN 测试可保持 HTTP，不在未启用 TLS 时单独开启 Secure cookie。

网关只认可其 socket 来源。若 HTTPS 反代与网关分开，可显式填写准确的 `MEDIA_WEB_TRUSTED_PROXIES` IP/CIDR，例如同机反代 `127.0.0.1/32`。反代必须**覆盖** `X-Real-IP` 为实际来源，并保留入口 Host；不要追加客户端提供的值，不要信任整个互联网网段。以 Nginx 为例，反代需设置 `proxy_set_header Host $http_host;` 和 `proxy_set_header X-Real-IP $remote_addr;`。该设置不启用 Uvicorn 对任意转发头的全局信任，也不更改 LAN socket 检查。控制端的专用 `x-media-client-ip` 仅接受服务凭据认证的网关，外部传入同名头会被覆盖或拒绝。

后端配额不依赖页面按钮：搜索每分钟 30 次、并发 2；计划每分钟 10 次、并发 2；新下载/字幕任务每 10 分钟合计 10 次；每账号最多 10 个未终结任务，本地全局新任务准入上限 100；连接密钥每小时创建 5 个、有效数量 10 个。管理员也适用。cloud 榜单与 local 查询的数据库配额池独立。命中限制返回 429 和 `account_rate_limited` / `account_concurrency_limited` / `account_queue_full` / `account_token_limit`。已提交请求沿用原 key 核对结果，不再占用新任务额度；不要换 key 绕过限制。未知提交和待复核任务保留队列占用，必须按原有安全流程解决。数量限制不代替磁盘容量监控。

当前验收范围见 [云端搜索与本地执行验收](history/cloud-execution-goal.md)，历史安全发现见 [安全复核](history/security-review-20261026.md)。

| 错误 / 现象 | 处理 |
| --- | --- |
| Docker/Compose 不可用 | 先在服务器完成 Docker 安装与启动；此脚本不安装 Docker |
| 构建依赖、OCR 或镜像下载失败 | 检查服务器镜像仓库/软件源网络和架构；保留缓存重试，不删任务数据库 |
| MCP 已启动但 worker 未就绪 | 查模型端点、token、硬链接权限、心跳；不要声称已正常下载 |
| `hardlink_cross_device` / probe 失败 | 下载与库放同一文件系统，并使用统一 `/data` 挂载 |
| `untrusted_host` | 先用实际 LAN IP 访问；DNS 名显式加入 `MEDIA_ALLOWED_HOSTS` |
| `cross_origin_request_denied` | 页面 Origin 与入口 Host 不同；使用正确同源入口或原生 MCP 客户端，不取消检查 |
| `configured_sites=0` / 搜不到 | 按 [Jackett 文档](jackett.md) 添加、测试并做确切片名搜索 |
| 已下载但 needs_review | 用 job_id 查看错误码；身份、路径或范围冲突不要强行覆盖 |
| `submission_unknown` | 保持原任务和 key 观察对账，禁止换 key 重复下载 |
| 字幕是英文但文件标中文 | 内容核验会拒绝；更新后为已有 media_id 重跑字幕，不重下视频 |
| 旧字幕文件变成 `.rejected-language` | 不合格原件的保留备份；新的中文字幕另行获取，备份不自动删除 |
| `missing` / 字幕持续失败 | 检查 Provider 额度、来源素材、模型和同步工具；不是所有片都有可用中文 |
| 没有手机推送 | 检查 BARK_URL 是否完整、服务器网络和本地日志；日志存在不代表送达 |

仅在用户明确要求、原因已处理后使用 `media_retry_job`，它只重试允许的处理阶段。确定在提交前失败的下载准备任务，可以重新搜索/规划新任务；不能用这个办法绕过“提交结果未知”保护。
