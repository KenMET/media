# 两端部署：复用现有反向代理和 FRP

只保留一份[统一模板 `.env.example`](../.env.example)，其中包含 cloud、local / NAS 两个分组。两台主机各自复制为本机 `.env`，填写所属分组；不是要求同步同一份私有配置和凭据。已有 `.env` 不会被启动器覆盖。

## 最小配置

标准模板保留需要部署者明确核对的连接参数：cloud 的网站端口、MCP 端口、本机 FRP 映射端口、TMDB key 和 Jackett 地址；NAS 的控制端口、下载器地址、媒体目录、模型地址与凭据文件。端口和模型地址虽然有程序默认值，仍显式列出，便于与现有 FRP、反代和模型服务对照。模型凭据文件必须实际存在且有效，不自动创建可用模型凭据。若采用内置 Jackett，可省略 `JACKETT_URL`；若采用内置下载器，可省略 `QBITTORRENT_URL`。

标准模板不再罗列高级参数；端口和模型地址列出默认值供直接修改。目录派生、状态目录等仍使用默认行为：

| 用途 | 默认行为 | 仅需要修改时填写 |
| --- | --- | --- |
| cloud 网站 | 0.0.0.0:18214 | `MEDIA_GATEWAY_BIND`、`MEDIA_GATEWAY_PORT` |
| cloud MCP | 127.0.0.1:18210 | `MEDIA_MCP_PORT` |
| cloud 访问 FRP 本机映射 | 127.0.0.1:28213 | `MEDIA_CONTROL_PORT` |
| NAS 控制端 | 模板 192.168.8.1:18213 | `MEDIA_LOCAL_CONTROL_BIND`、`MEDIA_LOCAL_CONTROL_PORT` |
| NAS 模型服务 | ws://127.0.0.1:8108 | `CODEX_APP_SERVER_URL` |
| 下载 / 硬链接 | `MEDIA_DATA_DIR` 下的 downloads / media_hub | 通常无需修改容器内部根路径 |
| NAS / cloud 状态 | 部署目录 ./state / ./state-cloud | 仅已有自定义状态目录时保留原设置 |

已有下载器要求登录时，添加真实 `QBITTORRENT_USERNAME` 和 `QBITTORRENT_PASSWORD`；省略表示免认证访问，不表示尝试默认密码。网站默认允许容器反代连接，仍要求用户认证。需要按真实客户端 IP 区分登录限流时，可额外指定反代实际来源 `MEDIA_PROXY_IPS`；未指定时忽略非回环来源提供的客户端 IP 头，使用真实 socket 来源限流，不信任可伪造的头。

媒体 key 与字幕 key 仍在 `.env` 配置，当前网页不提供编辑这些凭据的功能。`TMDB_API_KEY` 放 cloud，用于作品搜索、详情和 TMDB 榜单；`OPENSUBTITLES_API_KEY`、`SUBDL_API_KEY`、`ASSRT_API_KEY` 放 NAS，由字幕 worker 使用。三个字幕来源可按需选择，留空仅跳过相应来源，不影响本地字幕复用/提取、其他来源或已有文本的模型翻译。OpenSubtitles 适配器还支持 `OPENSUBTITLES_USERNAME`、`OPENSUBTITLES_PASSWORD`，按所用账号及下载接口要求添加；Media 不生成第三方 key。在线字幕获取当前仍由本地字幕处理流程执行，不属于已迁至云端的 TMDB/Jackett 搜索链路。

`BARK_URL` 是可选的完整设备推送地址，放 NAS 使用；已有通知配置可以继续保留，留空时只记录本地通知。该地址包含私有设备 key，不要提交或公开。

既有 `.env` 的自定义端口、媒体根和状态目录不要机械删除。模板精简不会搬迁已有数据库或改变正在运行的容器；新安装直接使用最小模板，旧安装核对路径后合并。

## NAS

保留现有 `/data/downloads`、`/data/media_hub`。填写已有下载器地址及认证、现有模型连接。`MEDIA_LOCAL_CONTROL_PORT=18213` 是本地控制端口，交给已有 FRPC 转发。NAS 不填写云端域名、URL 或地址，不主动连接云端 Provider。

```sh
cp .env.example .env
# 编辑 .env；已有文件时不要覆盖，按模板合并。
sh setup.sh local
```

local 按 `MEDIA_LOCAL_CONTROL_BIND` 监听 NAS 的明确地址，模板为 `192.168.8.1`；需要使用其他 NAS 地址时修改这一项。内部认证文件自动生成。新配置默认启用本地执行模式：仅运行 worker 与控制服务、按需启动下载器，不启动 Jackett，不执行搜索。下载、入库和字幕使用云端下发的冻结信息，仍核对文件身份。不自动接管旧下载器任务、不导入 MySQL。正式接管旧目录前仍要完成 [数据迁移](production-cutover-plan.md)，不能用启动命令代替迁移。

## 云端

填写 cloud 分组的端口、TMDB key 和已有 Jackett（留空则启动内置）。网站使用 `MEDIA_GATEWAY_PORT`，NAS 控制端使用 `MEDIA_LOCAL_CONTROL_PORT`，避免统一模板的同名参数相互覆盖。本机 FRP 映射入口使用 `MEDIA_CONTROL_PORT`。内部固定连接 `127.0.0.1`，不用填写两端 URL。无需在 Media 配置域名、证书、`MEDIA_WEB_PUBLIC_URL` 或 `MEDIA_ALLOWED_HOSTS`。

```sh
cp .env.example .env
# 编辑 .env；已有文件时不要覆盖，按模板合并。
sh setup.sh cloud
```

先启动 local 并接通现有 FRP（NAS `192.168.8.1:18213` → 云端本机 `127.0.0.1:28213`），再启动 cloud。云端自动通过该端口建立内部认证，保存 0600 凭据，确认成功后 NAS 关闭初次配对入口。原来的 API 身份认证仍然保留；不是删除 token 校验，也不是自动信任任意远程地址。已有内部凭据文件会沿用，不打印或覆盖。

网站管理员、密码和会话保存在 NAS。首次初始化令牌也由 NAS 控制 API 生成，默认在 NAS 项目目录的 `state/web-bootstrap-token`；云端 `find` 不会找到它。可在 NAS 项目目录运行 `docker compose -f compose.local.yml exec -T web cat /state/web-bootstrap-token`，仅在自己的终端读取，再填入云端网站初始化页面。不要把令牌发到聊天或日志中，也不需要将文件复制到云端。已有管理员时初始化入口关闭，不能靠重建 token 文件重置账户。

FRPC 的 `localIP` 应与 `MEDIA_LOCAL_CONTROL_BIND` 一致，`localPort` 等于 `MEDIA_LOCAL_CONTROL_PORT`，`remotePort` 等于 cloud 的 `MEDIA_CONTROL_PORT`。此方案要求 FRPC 与控制 API 使用同一宿主机网络；当前不自动修改共享 FRP 服务的其他映射。未填写新监听项的旧配置仍回退到原 `MEDIA_WEB_BIND_HOST` 或 local 的回环默认值。

网页和 MCP 的中英文搜索、榜单、详情、Jackett 查询及种子内容获取均在 cloud 执行。云端按用户隔离搜索结果，选定后把有大小限制的种子字节或 magnet、媒体身份和集数交给 NAS；NAS 检查权限、过期时间、infohash、已有媒体、计划版本和幂等键，再生成本地任务。worker 直接消费已冻结材料，不访问云端 Jackett 地址。下载过程中 BT tracker/peer 与字幕/模型服务仍由对应本地执行组件按需访问；“不回调云端 Provider”不等于 NAS 完全断网。

此自动配对信任你已配置好的私有 FRP 通道以及两台主机的本机进程。**云端映射端口必须仅本机可达**，不能公开；云端自动配对拒绝非回环 HTTP 地址。配对接口只存在于 local 控制端并要求显式开启：回环监听仅接受回环来源；明确的 NAS 私网监听地址仅接受来源 IP 与实际监听 IP 均等于该 NAS 地址的本机自连接，不接受其他 LAN 设备或伪造来源头。通配/公网监听不能进行自动配对。云端网站不会将该接口转发给公网。若云端凭据丢失，在 NAS 执行 `sh setup.sh local pair` 重新允许连接，再在云端执行启动命令；不要删除正式数据库。

跨公网的 FRP 传输仍须使用已有认证和加密配置；只把映射端口绑定回环并不等于传输加密。Media 不修改你现有的 FRP 配置。

云端网站默认监听 `0.0.0.0:18214`，不再只监听回环。Docker bridge 反代的上游填写容器可达的云主机 IP 和 `MEDIA_GATEWAY_PORT`，例如本次 `10.3.0.7:8800`，不要填写反代容器自己的 `127.0.0.1`，也不要填 FRP 控制映射口 `8802`。反代需保留 Host，覆盖或追加真实客户端来源。同源检查、登录/CSRF 和 MCP 用户令牌仍启用，网站会设置 Secure cookie，外部 HTTPS 由现有反代提供。

`MEDIA_GATEWAY_BIND` 可省略或留空，默认就是 `0.0.0.0`。云端网站只读取这个专用监听项，不再被旧 `MEDIA_WEB_BIND_HOST=127.0.0.1` 带回回环地址；Compose 同时把旧内部项映射为相同值以兼容已有镜像。修改后需要重新创建网站容器，仅 `docker restart` 不会更新容器环境。

已有反代若已按标准追加/覆盖 `X-Forwarded-For`，无需再加 X-Real-IP：应用优先读取该链末端由本机代理追加的实际来源，不使用客户端可伪造的第一个值。只有回环代理来源才有此权限；反代不能原样透传客户端的来源头而不追加/覆盖。

网站的网络监听与代理来源头信任分别处理：不设置 `MEDIA_PROXY_IPS` 时允许正常访问登录入口，所有业务仍需身份认证；设置后额外限制为回环和指定的准确代理 IP，并信任这些代理提供的来源头。`MEDIA_PROXY_IPS` 指代理连接到应用时的真实来源地址，不能把上游云主机 `10.3.0.7` 当作代理 IP 填入。MCP 仍保持回环或显式代理来源限制；Docker 反代 `/mcp` 时需指定代理来源 IP，其监听会相应调整。未配置可信代理时，经过同一代理的请求共享该 socket IP 的限流桶。

新模式只有 cloud → NAS 的应用连接，NAS 不需要 `MEDIA_CATALOG_URL`。FRPC 自身与 FRPS 的连接配置继续由你管理；Media 不替它配置服务器地址。

## 宿主机持久化

云端 Jackett 固定复用原有宿主机目录，直接写在 `compose.cloud.yml` 中，不需要 `.env` 路径变量：

| 宿主机 | 容器内 | 内容 |
| --- | --- | --- |
| `/root/container_cache/jackett/config` | Jackett `/config` | `Jackett/ServerConfig.json`、`Indexers`、`DataProtection`、日志及配置内缓存 |
| `/root/container_cache/jackett/downloads` | Jackett `/downloads` | Jackett 导出的种子/blackhole 文件，不是 NAS 的影片下载目录 |
| `/root/container_cache/jackett/config` | cloud web/MCP `/services/jackett`（只读） | 读取现有 API key 与 public 站点配置 |

已有目录可原样使用。初始化只在 `ServerConfig.json` 不存在时创建默认配置，不覆盖已有站点、API key 或 DataProtection。`JACKETT_URL` 非空时不启动、初始化第二个 Jackett，但仍按上述固定目录只读获取该主机上的现有配置。cloud 不再读取 `MEDIA_JACKETT_CONFIG_DIR`。

NAS 标准模板只保留 `MEDIA_DATA_DIR`：宿主机该目录整体挂载到容器 `/data`，默认下载与媒体库分别使用其 `downloads`、`media_hub` 子目录。例如宿主机 `/mnt/media` 对应 `/mnt/media/downloads`、`/mnt/media/media_hub`，容器内仍为 `/data/downloads`、`/data/media_hub`。无需设置 `MEDIA_DOWNLOAD_ROOT` 或 `MEDIA_LIBRARY_ROOT`；它们仅用于特殊容器内路径的高级配置。

其他应用状态已经绑定到宿主机：cloud 的 `./state-cloud` 保存榜单缓存与用户隔离的搜索快照，NAS 默认的 `./state` 保存用户、下载记录、处理任务与恢复状态；私有内部凭据默认在宿主机 `./state/control-token`。无需设置 `MEDIA_STATE_PATH`。容器删除重建仍会复用这些目录。此处 `./` 相对于各自部署目录，重装到其他目录时应保留原状态目录；不能删除后期待容器恢复数据。榜单缓存仍按过期时间刷新，不会因持久化而永久冻结。

已有部署若显式配置了 `MEDIA_STATE_PATH`，继续保留原值；直接删除该项会切换到默认 `./state`，不会自动迁移原数据库。模板精简不改动用户已有 `.env` 或状态目录。

仅重建容器即可复用上述绑定目录；Media 不会在本轮把现有云端目录复制到 NAS，也不会替换已运行的 Jackett。传统不分角色的单机配置仍保留原目录选项，避免自动搬迁已有安装。

## 兼容和端口

- 统一模板使用 `MEDIA_GATEWAY_PORT` 表示 cloud 网站、`MEDIA_LOCAL_CONTROL_PORT` 表示 NAS 控制端。旧 local 的 `MEDIA_WEB_PORT` 仍作兼容回退，新控制端口优先；旧 cloud 仅填写 `MEDIA_WEB_PORT` 仍兼容，`MEDIA_GATEWAY_PORT` 优先。
- `MEDIA_CONTROL_PORT` 优先于旧 `MEDIA_CONTROL_URL`；只允许 1–65535 的数字并固定使用回环 HTTP。未设置端口时旧 URL 保留兼容；新 cloud 配置默认端口 28213。同机、不经过 FRP 的隔离测试可设为本地控制端口，例如 18213。
- 已显式设置旧 `MEDIA_CATALOG_URL` 的 local 配置保留原兼容模式；切换时移除它并重启 local，即默认启用 `MEDIA_EXECUTION_ONLY=true`，拒绝 Provider 网络访问。旧单机不受影响。不要只改模板而误以为已修改自己的 `.env`。
- 需要直接用 NAS IP 访问同机测试网页时，显式设置 `MEDIA_WEB_MODE=lan`、`MEDIA_WEB_BIND_HOST=0.0.0.0`；仍使用原有 LAN 边界。非回环监听不会开放自动配对。不是推荐的公网部署方式。
- 已显式设置旧 `MEDIA_WEB_PUBLIC` 的配置继续使用旧模式；要改为现有反代模式，可显式加入 `MEDIA_WEB_MODE=proxy`。新配置省略这两个开关时，`setup.sh cloud` 默认采用 proxy。
- 现有下载器/Jackett URL 非空时复用已有服务，为空才启动对应内置容器。内置管理端口仍默认回环绑定。
- 首次网站管理员初始化仍按启动提示进行；内部服务配对凭据与网站用户密码、模型凭据是不同的用途。

本轮不改动用户现有 `.env`、FRP、反代或生产数据；只交付部署入口、模板及隔离验证。

本轮验证结果见 [云端搜索重构验收](history/cloud-execution-goal.md)。尚未在真实新加坡服务器执行部署。

## 启动状态检查

local 启动时会只读调用 qBittorrent 版本 API，核对下载器服务和认证，不创建分类、不提交下载、不修改已有任务；失败会明确提示地址或认证检查。控制 API 就绪之后，worker 仍需完成模型连接、目录/硬链接检查及子进程初始化。脚本每 5 秒检查一次，最多检查 60 次；全部健康检查通过后才成功退出，持续未就绪则超时并非零退出。排错使用 `sh setup.sh local logs`。
