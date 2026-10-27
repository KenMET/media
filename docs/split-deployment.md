# 两端部署：复用现有反向代理和 FRP

推荐入口只有两份模板：[云端](../.env.cloud.example)、[NAS](../.env.local.example)。各自复制为本机 `.env` 后编辑；已有 `.env` 不会被启动器覆盖。

## 最小配置

标准模板保留需要部署者明确核对的连接参数：cloud 的网站端口、MCP 端口、本机 FRP 映射端口、TMDB key 和 Jackett 地址；NAS 的控制端口、下载器地址、媒体目录、模型地址与凭据文件。端口和模型地址虽然有程序默认值，仍显式列出，便于与现有 FRP、反代和模型服务对照。模型凭据文件必须实际存在且有效，不自动创建可用模型凭据。若采用内置 Jackett，可省略 `JACKETT_URL`；若采用内置下载器，可省略 `QBITTORRENT_URL`。

标准模板不再罗列高级参数；端口和模型地址列出默认值供直接修改。目录派生、状态目录等仍使用默认行为：

| 用途 | 默认行为 | 仅需要修改时填写 |
| --- | --- | --- |
| cloud 网站 | 127.0.0.1:18214 | `MEDIA_WEB_PORT` |
| cloud MCP | 127.0.0.1:18210 | `MEDIA_MCP_PORT` |
| cloud 访问 FRP 本机映射 | 127.0.0.1:28213 | `MEDIA_CONTROL_PORT` |
| NAS 控制端 | 127.0.0.1:18213 | `MEDIA_WEB_PORT` |
| NAS 模型服务 | ws://127.0.0.1:8108 | `CODEX_APP_SERVER_URL` |
| 下载 / 硬链接 | `MEDIA_DATA_DIR` 下的 downloads / media_hub | 通常无需修改容器内部根路径 |
| NAS / cloud 状态 | 部署目录 ./state / ./state-cloud | 仅已有自定义状态目录时保留原设置 |

仅有两类常见条件项：已有下载器要求登录时，添加真实 `QBITTORRENT_USERNAME` 和 `QBITTORRENT_PASSWORD`；已有反代运行在 Docker bridge 网络时，添加其固定 IP 的 `MEDIA_PROXY_IPS`。省略下载器账号密码表示免认证访问，不表示尝试默认密码。

媒体 key 与字幕 key 仍在 `.env` 配置，当前网页不提供编辑这些凭据的功能。`TMDB_API_KEY` 放 cloud，用于作品搜索、详情和 TMDB 榜单；`OPENSUBTITLES_API_KEY`、`SUBDL_API_KEY`、`ASSRT_API_KEY` 放 NAS，由字幕 worker 使用。三个字幕来源可按需选择，留空仅跳过相应来源，不影响本地字幕复用/提取、其他来源或已有文本的模型翻译。OpenSubtitles 适配器还支持 `OPENSUBTITLES_USERNAME`、`OPENSUBTITLES_PASSWORD`，按所用账号及下载接口要求添加；Media 不生成第三方 key。在线字幕获取当前仍由本地字幕处理流程执行，不属于已迁至云端的 TMDB/Jackett 搜索链路。

既有 `.env` 的自定义端口、媒体根和状态目录不要机械删除。模板精简不会搬迁已有数据库或改变正在运行的容器；新安装直接使用最小模板，旧安装核对路径后合并。

## NAS

保留现有 `/data/downloads`、`/data/media_hub`。填写已有下载器地址及认证、现有模型连接。`MEDIA_WEB_PORT=18213` 是本地控制端口，交给已有 FRPC 转发。NAS 不填写云端域名、URL 或地址，不主动连接云端 Provider。

```sh
cp .env.local.example .env
# 编辑 .env；已有文件时不要覆盖，按模板合并。
sh setup.sh local
```

local 默认只监听 `127.0.0.1`，内部认证文件自动生成。新配置默认启用本地执行模式：仅运行 worker 与控制服务、按需启动下载器，不启动 Jackett，不执行搜索。下载、入库和字幕使用云端下发的冻结信息，仍核对文件身份。不自动接管旧下载器任务、不导入 MySQL。正式接管旧目录前仍要完成 [数据迁移](production-cutover-plan.md)，不能用启动命令代替迁移。

## 云端

填写 TMDB key 和已有 Jackett（留空则启动内置）即可。网站端口默认 `18214`、本机 FRP 映射端口默认 `28213`，不改端口就无需填写；确需修改时再加 `MEDIA_WEB_PORT` 或 `MEDIA_CONTROL_PORT`。内部固定连接 `127.0.0.1`，不用填写两端 URL。无需在 Media 配置域名、证书、`MEDIA_WEB_PUBLIC_URL` 或 `MEDIA_ALLOWED_HOSTS`。

```sh
cp .env.cloud.example .env
# 编辑 .env；已有文件时不要覆盖，按模板合并。
sh setup.sh cloud
```

先启动 local 并接通现有 FRP（NAS `127.0.0.1:18213` → 云端本机 `127.0.0.1:28213`），再启动 cloud。云端自动通过该端口建立内部认证，保存 0600 凭据，确认成功后 NAS 关闭初次配对入口。原来的 API 身份认证仍然保留；不是删除 token 校验，也不是自动信任任意远程地址。已有内部凭据文件会沿用，不打印或覆盖。

网页和 MCP 的中英文搜索、榜单、详情、Jackett 查询及种子内容获取均在 cloud 执行。云端按用户隔离搜索结果，选定后把有大小限制的种子字节或 magnet、媒体身份和集数交给 NAS；NAS 检查权限、过期时间、infohash、已有媒体、计划版本和幂等键，再生成本地任务。worker 直接消费已冻结材料，不访问云端 Jackett 地址。下载过程中 BT tracker/peer 与字幕/模型服务仍由对应本地执行组件按需访问；“不回调云端 Provider”不等于 NAS 完全断网。

此自动配对信任你已配置好的私有 FRP 通道以及两台主机的本机进程。**云端映射端口必须仅本机可达**，不能公开；自动配对拒绝非回环 HTTP 地址。配对接口只存在于 local 控制端，要求显式开启及回环监听/来源；云端网站不会将该接口转发给公网。若云端凭据丢失，在 NAS 执行 `sh setup.sh local pair` 重新允许连接，再在云端执行启动命令；不要删除正式数据库。

跨公网的 FRP 传输仍须使用已有认证和加密配置；只把映射端口绑定回环并不等于传输加密。Media 不修改你现有的 FRP 配置。

默认云端是已有反代模式：网站 `127.0.0.1:18214`，MCP `127.0.0.1:18210`。你的 HTTPS 反代网站上游指向前者；使用 AI 时把 `/mcp` 指向后者。反代需保留 Host、覆盖 X-Real-IP 为真实客户端地址；例如 Nginx 的 `proxy_set_header Host $http_host;`、`proxy_set_header X-Real-IP $remote_addr;`。同源检查、登录/CSRF 和 MCP 用户令牌仍启用，网站会设置 Secure cookie，外部 HTTPS 由现有反代提供。

已有反代若已按标准追加/覆盖 `X-Forwarded-For`，无需再加 X-Real-IP：应用优先读取该链末端由本机代理追加的实际来源，不使用客户端可伪造的第一个值。只有回环代理来源才有此权限；反代不能原样透传客户端的来源头而不追加/覆盖。

默认只允许回环 socket 来源，不能靠伪造转发头绕过。如果 NPM 等反代在 Docker bridge 网络，补一项 `MEDIA_PROXY_IPS=反代容器的固定IP`，反代上游使用它可达的宿主机 IP 和网站端口（不能填反代容器自己的 127.0.0.1）。启动器会调整监听，但应用仍只允许回环和这些准确的代理 IP，不信任整个私网。容器 IP 变化时需要更新配置并重启；可给代理分配固定 IP。此选项也用于 MCP 入口。

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

- 新配置使用 `MEDIA_WEB_PORT` 表示当前角色的网页/控制端口。旧 `MEDIA_GATEWAY_PORT` 仍兼容且优先，避免破坏旧同机测试配置。
- `MEDIA_CONTROL_PORT` 优先于旧 `MEDIA_CONTROL_URL`；只允许 1–65535 的数字并固定使用回环 HTTP。未设置端口时旧 URL 保留兼容；新 cloud 配置默认端口 28213。同机、不经过 FRP 的隔离测试可设为本地控制端口，例如 18213。
- 已显式设置旧 `MEDIA_CATALOG_URL` 的 local 配置保留原兼容模式；切换时移除它并重启 local，即默认启用 `MEDIA_EXECUTION_ONLY=true`，拒绝 Provider 网络访问。旧单机不受影响。不要只改模板而误以为已修改自己的 `.env`。
- 需要直接用 NAS IP 访问同机测试网页时，显式设置 `MEDIA_WEB_MODE=lan`、`MEDIA_WEB_BIND_HOST=0.0.0.0`；仍使用原有 LAN 边界。非回环监听不会开放自动配对。不是推荐的公网部署方式。
- 已显式设置旧 `MEDIA_WEB_PUBLIC` 的配置继续使用旧模式；要改为现有反代模式，可显式加入 `MEDIA_WEB_MODE=proxy`。新配置省略这两个开关时，`setup.sh cloud` 默认采用 proxy。
- 现有下载器/Jackett URL 非空时复用已有服务，为空才启动对应内置容器。内置管理端口仍默认回环绑定。
- 首次网站管理员初始化仍按启动提示进行；内部服务配对凭据与网站用户密码、模型凭据是不同的用途。

本轮不改动用户现有 `.env`、FRP、反代或生产数据；只交付部署入口、模板及隔离验证。

本轮验证结果见 [云端搜索重构验收](history/cloud-execution-goal.md)。尚未在真实新加坡服务器执行部署。
