# Media 安全与可用性检查

检查日期：2026-10-24。范围是独立 `media/` 的配置/启动、MCP 边界、索引器下载、文件与字幕处理、凭据和用户文档。使用源码审查、隔离测试与已有运行证据；没有扫描整个内网、对生产服务执行攻击、停止服务或重建部署。本记录不是“没有任何漏洞”的保证，也不是第三方依赖的完整 CVE/SBOM 审计。

## 本次修复

| 问题 | 影响 | 修复 |
| --- | --- | --- |
| MCP 只检查 LAN 来源，没有自己的 Host/Origin 边界 | LAN 机器上的浏览器访问恶意域名时，可能被 DNS 重绑定或跨站请求利用；是否可直接利用还取决于 HTTP/MCP 栈的其他保护 | 增加 Host 白名单与同源 Origin 检查；IP/localhost 默认支持，DNS 名需显式配置；HTTP/WebSocket 均拒绝异常请求 |
| Jackett 搜索先读取整个响应再检查 4 MiB | 异常站点响应可能经本地 Jackett 消耗过多内存 | 流式读取、在超过限制时停止并关闭响应，保留单站失败隔离 |
| 已有 `.env` 可能保持编辑器创建的宽松权限 | 同机其他账号可能读取凭据 | 启动时将 `.env` 权限收紧至 0600；不输出内容 |
| init 以 root 生成 0600 的服务配置，未匹配非 root PUID/GID | 首次选择非 root UID 的下载器/Jackett 可能无法读取或保存配置 | 管理目录与新生成文件匹配配置 UID/GID；不递归修改现有媒体/配置文件 |
| 启动输出始终宣称无需登录 | 显式启用 bearer/OAuth 时描述错误 | 输出实际配置的认证模式 |

默认 MCP 仍免登录，没有擅自新增登录要求。新 Host 检查可能阻止原先任意 DNS 别名；使用实际 LAN IP，或按部署文档设置准确的 `MEDIA_ALLOWED_HOSTS`。

## 已有防线与实际限制

- MCP 使用实际 socket peer，不根据 `X-Forwarded-For` 放行；私网 allowlist 可收窄，但不是用户身份。
- 下载采用返回的 release/plan ID、修订和幂等 key。结果未知先对账；不接管无本任务标签的下载器任务。
- Jackett 下载 URL 限同源，有限同源跳转或有效 v1 magnet 交接；提交前计算/比较 infohash，不请求任意外部 HTTP 跳转。
- 文件路径检查拒绝越界和符号链接别名；SQLite 租约、OS 锁与版本日志维持任务和发布边界。硬链接会共享字节，因此不得原地编辑成片。
- 在线字幕 ZIP/GZIP 解压有限额，XML 使用 defusedxml。文本中文校验检查实际对白覆盖率，不信任来源标签、ASS 样式或片头署名；30% 阈值是启发式，不是翻译正确性或全片完整性的证明。
- 字幕重处理保留不合格原件，未引入通过重试删除下载任务或视频的能力。
- 凭据路径、数据、services 目录被 Git/Docker 构建上下文忽略；这不代替检查实际提交内容。模型 token 只读挂载，模型服务不由 Media 启动。

## 尚存的重要风险

### 管理网页的安全范围仍是可信 LAN（高）

qBittorrent 默认对白名单 LAN 免登录；Jackett 初始没有管理员密码。两者的网页不经过 MCP 的新 Host/Origin 检查。qBittorrent 初始化还配置 `WebUI\HostHeaderValidation=false`，因此**MCP 修复不等于整个组合都具备 DNS 重绑定防护**。不可信访客、被入侵的 LAN 主机、可访问内网的代理都可能操作管理界面或获取站点配置。

这轮未直接改动用户正在运行的下载器认证与反向代理设置，也没有将 qBittorrent Host 校验简单开成 true：本组合外部 18211 映射到内部 8080，版本相关的 Host 端口校验可能使 UI/API 和后台全部失效。需要单独验证管理入口网络/端口及允许域名后再调整。相关行为可参照 [qBittorrent 官方源码](https://github.com/qbittorrent/qBittorrent/blob/master/src/webui/webapplication.cpp) 的 Host/跨站检查；实际部署镜像仍须实测。

当前部署必须限制管理端口仅可信设备可达，不使用公网转发；不要将无认证管理界面经公共隧道暴露。若需要不可信网络或多人访问，应另行部署受认证的管理入口，并评估缩小 qBittorrent 免登录范围、设置 Jackett 管理员密码及兼容的后台 API 连接。防火墙不是浏览器 DNS 重绑定防线的完整替代，此项仍记录为未关闭风险。

### 运行权限与外部内容（中）

默认 PUID/PGID=0，MCP/worker 也以容器默认 root 运行且使用 host network。容器不是处理恶意媒体的强沙箱；ffmpeg、OCR、下载器、字幕服务和模型输入都是攻击面。仅给予所需数据目录，避免共享宿主机敏感根目录，不把 Docker socket 挂入服务。非 root PUID 只改变下载器/Jackett，不代表整个组合已降权。全面降权、网络出口策略和第三方工具隔离仍未做运行验收。

### 版本与供应链（中）

下载器/Jackett 默认镜像为 latest，构建还下载工具/系统包。为可重现更新应选定版本或 digest 并保留旧镜像，按计划单服务更新；本轮没有对所有依赖进行在线漏洞扫描或验证所有构建下载的签名/哈希。

### 可用性、积累与通知（中/低）

搜索和计划有有效期，但持久历史记录、备份字幕及媒体文件没有总容量自动回收策略；可信客户端仍可能提交大量搜索，亦无强制磁盘配额。磁盘、CPU 与外部服务额度要监控，避免将接口提供给不可信调用者。Bark 有网络失败可能，本地事件日志不是端到端送达回执，也没有承诺每个下载失败都发送手机告警。

## 验证与复核方式

本次只运行相关的小范围测试，低优先级、串行，使用可丢弃文件和内存记录，不跑 Quant/Crawler 全套、不碰生产媒体。检查项目包括 LAN Host/Origin/转发头/WebSocket、限长搜索响应、bootstrap 新配置所有权/不覆盖现有文件、启动与权限、已有下载与字幕回归。本地隔离 Linux 环境串行低优先级执行 35 项，全部通过：`test_lan_boundary`、`test_bootstrap`、`test_start`、`test_release_search`、`test_jackett_download`、`test_acquire`、`test_subtitle_content`。该小范围测试环境为 Python 3.10；项目声明的部署基线仍为 Python 3.11+，镜像为 Python 3.12；本轮没有用新镜像重新做完整 Docker 组合验收，也没有重新运行全部 MCP/FastMCP 集成测试。

启动脚本已固定 LF 行尾，新增 `.gitattributes` 约束，避免 Windows 编辑后 Linux `sh` 将 CRLF 当作命令字符。`.env.example` 保持 LF，启动器读取值时容忍行尾 CR。

另检查 Python/shell 语法、文档内部链接和 `.env.example` 与 Compose/代码的一致性，更新 LikeC4 并运行验证。历史 [acceptance.md](acceptance.md) 是原始部署的收据，不应当作本轮新镜像验收。
