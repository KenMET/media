# 部署、更新与运维

快速首次使用按 [README](../README.md) 顺序执行。本页所有命令默认在服务器的 `media/` 目录执行，不在 Windows 客户端执行 Linux 部署命令。

## 配置表

`.env` 从 `.env.example` 复制。不要用 `source .env` 来加载配置；Compose 会读取它。当前启动器用简单的 `KEY=value` 读取路径和端口：不要为这些值加引号、变量引用、行尾注释或空格。使用实际绝对路径或 `./相对路径`，避免路径包含空格。

| 配置 | 默认 / 说明 |
| --- | --- |
| `TMDB_API_KEY` | 必填；作品/年份/季集元数据查询 |
| `CODEX_APP_SERVER_URL` | `ws://127.0.0.1:8108`；既有适配模型服务，不由本项目安装 |
| `CODEX_TOKEN_FILE` | `./state/codex-token`；宿主机 token 文件，必须与模型端点匹配，不能为空 |
| `MEDIA_STATE_PATH` | `./state`；本机 SQLite、WAL、SHM、锁及日志目录 |
| `MEDIA_DATA_DIR` | `./data`；完整下载/库根目录，容器内统一为 `/data` |
| `MEDIA_SERVICES_DIR` | `./services`；Jackett 和下载器的独立持久状态 |
| `MEDIA_LAN_BIND` | `0.0.0.0`；本组合保留默认。直接改为某个网卡 IP/loopback 还会影响下载器回环访问和健康探针，不是已验证的快捷配置 |
| `MEDIA_LAN_IP` | 可选；只改变启动打印的访问地址，不改变监听或防火墙 |
| `MEDIA_LAN_CIDRS` | 可选，逗号分隔 MCP 实际客户端来源网段；默认私网/本机。收窄时保留 `127.0.0.0/8,::1/128` 给健康检查 |
| `MEDIA_ALLOWED_HOSTS` | 可选，逗号分隔准确 DNS 主机名，例如 `media.home`；不含协议、端口、路径，不支持通配符。LAN IP 和 localhost 无需填写 |
| `MEDIA_MCP_PORT` | `18210`；HTTP MCP，路径 `/mcp` |
| `MEDIA_QBITTORRENT_PORT` | `18211`；下载器管理/API 端口 |
| `MEDIA_JACKETT_PORT` | `18212`；Jackett 管理/API 端口 |
| `MEDIA_TORRENT_PORT` | `48181` TCP/UDP；BT 数据传输，与管理端口不同 |
| `PUID` / `PGID` | `0` / `0`；内置下载器/Jackett 的文件属主；不是 MCP/worker 的非 root 开关 |
| `TZ` | `Asia/Shanghai` |
| `OPENSUBTITLES_API_KEY`、`SUBDL_API_KEY`、`ASSRT_API_KEY` | 对应可选字幕服务凭据；仍受各自额度、认证和可用性影响 |
| `BARK_URL` | 可选完整设备推送 endpoint；为空只写通知日志，不会推送到手机 |
| `SUBTITLE_SYNC_MODE` | `required`；同步不成功不当作已同步，可选 `auto`、`disabled` 会降低对齐保证 |
| `SUBTITLE_ENABLE_AUDIO_ASR` | `false`；改 true 不会自动安装或下载 ASR 模型 |
| `INSTALL_OCR` | `true`；镜像构建时安装 PGS OCR 工具；改动需重建 |
| `MEDIA_AUTH_MODE` | `none`；可显式选择 `bearer`/`oauth`，仍受 LAN 中间件限制 |

可选认证：bearer 模式还需服务端 `MEDIA_MCP_TOKEN`（至少 32 字符）；OAuth 需 `MEDIA_PUBLIC_URL` 和 `MEDIA_OWNER_PASSWORD`（至少 24 字符）。这些是另一个显式部署选择，不是快速开始的必填项；选择认证也不会自动提供 TLS、隧道或公网网络通路。不要在聊天中传入密钥。

目录设置在首次下载前确定。更改 `MEDIA_DATA_DIR`、容器内路径、PUID/GID 或数据库位置，不等于已经迁移已有任务路径和文件权限。初始化不会递归修改已有文件，既有配置切换 UID 时需停机检查归属后再使用。

## 模型连接检查

MCP/worker 采用宿主机网络；因此默认模型地址的 `127.0.0.1` 是服务器自身。若模型运行于另一台主机或容器，使用服务器能访问的实际端点，不能假设本机端口相同。

所需的是本项目适配的 WebSocket App Server 协议和 bearer 认证入口，不是任意聊天网页、REST API 或直接运行一个未适配的同名服务。本目录没有自包含的模型服务部署脚本；迁到新主机必须先提供这个外部依赖。缺少它仍能启动网页/MCP，但 worker 不会进入正常提交/处理状态。

检查 `sh start.sh logs` 中的模型认证、硬链接探针和 worker 心跳。`token_missing`、`token_unreadable`、`token_rejected` 分别检查空文件、可读权限和 token 是否匹配端点。不要打印 token 排错。默认占位空文件只用于让其他服务能启动，不代表已完成模型配置。

## 网络与访问边界

MCP/worker 使用 host network，下载器/Jackett 使用 bridge 并发布端口。默认回环 API 地址依赖这些端口可在服务器本机访问。不要为排错同时改多个网络选项。

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
| `sh start.sh status` | 容器状态/健康检查；不直接说明某个任务成功 |
| `media_status` | worker 心跳、凭据/站点存在；不验证外部搜索效果 |
| Jackett Test + Manual Search | 单站连接及具体词搜索效果；不保证种子传输速度 |
| `media_get_job` | 指定任务各阶段的实际状态，是进度依据 |
| 字幕 `content_verifications` | 已记录的内容校验与对白覆盖率；来源标签和 handled 数量不能代替它 |
| `notifications.jsonl` | 后端写入通知事件；存在记录不等于手机送达 |

MCP 请求成功或拿到 job_id 只表示已提交。下载完成、视频硬链接入库、字幕完成分别判断。

## 更新和正常停止

```sh
sh start.sh status
sh start.sh logs
sh start.sh stop
sh start.sh
```

`start.sh` 默认构建 Media 镜像，再更新 MCP/worker 和必要服务。启动器不删除持久目录，不停止父项目 Quant/Crawler。每次更新按顺序运行，不在资源紧张的服务器上同时构建、测试多个项目。

更新第三方镜像是另外一步，先备份，再显式拉取你选择的固定版本或 digest；`.env` 可设置 `QBITTORRENT_IMAGE`、`JACKETT_IMAGE`。默认 `latest` 会随拉取变化，不是可重现版本锁定。不要把“重建 Media”当作“所有第三方组件已更新且无漏洞”。

不要执行 `docker compose down -v` 或清空 `state/` 来修复任务。容器日志会轮转；发布前保留原始错误码和阶段，分享日志时脱敏。

## 备份、迁移与恢复

下面是**默认目录布局**示例。若改过路径，把配置中的实际目录加入备份清单。将备份写到本机已有且空间足够的私有目录，归档不放在被打包目录内：

```sh
sh start.sh stop
umask 077
tar -cpf /你的私有备份目录/media-state.tar .env state services
# 视频、做种源文件、字幕另行备份；需要完整可恢复备份时也必须包含 data。
```

`.env`、token、站点 cookie/passkey、数据库与归档均视为私有。仅备份元数据不能恢复丢失的视频。先停止所有写入者，再拷贝数据库所在整个状态目录；不要只复制运行中的 SQLite 主文件遗漏 WAL。若有其他共享目录写入服务，也先停止它们。

恢复时在空的目标目录保留正确权限，恢复匹配版本代码、配置及所有实际持久目录，确认本机路径和模型服务可达，再运行 `sh start.sh`。不要覆盖正在运行的状态。更换目录、UID 或数据路径后要先检查权限和任务中的路径，不能承诺无需迁移就直接续传。回滚需使用对应旧镜像/代码与一致的状态备份，不要只回退一个 SQLite 文件。

## 常见错误

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
