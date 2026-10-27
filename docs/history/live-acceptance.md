# 真实榜单与下载验收

日期：2026-10-25。全部服务仍运行于本地 NAS 192.168.8.1；`cloud` 表示服务分组，不表示已经部署到新加坡。此记录补充首版 [隔离验收](platform-acceptance.md)。

状态：真实榜单、public 站点中英文搜索、真实下载/模型/入库/字幕、权限和重启恢复均已通过。Python 回归 78 项、Node 界面语言测试 4 项通过；安装包含四个 CLI 和四个静态资源。浏览器已验证中文/English 切换、偏好保留、真实榜单、英文搜索与任务/媒体库页面。

## 真实榜单

- TMDB：复用已有私有配置，电影/剧集、今日/本周四组真实接口均返回 20 项。
- SIMKL：新增独立来源，电影/剧集、今日/本周四组均返回真实数据，页面取前 40 项。无需 API key，不增加必填环境变量。
- SIMKL 文件的 Last-Modified 实测为当天；单独保存来源更新时间和本机抓取时间。缓存一小时、失败退避五分钟；超过两天未更新或异常未来时间的文件不作为当前榜单接收。失败保留旧缓存与原更新时间，明确标记过期。
- 页面标题、评分来源和链接明确区分 TMDB、SIMKL、豆瓣。SIMKL 条目使用来源提供的 TMDB ID 进入真实详情；缺失映射时先搜索、由用户确认。
- 豆瓣适配器继续保留，但不作为可用来源承诺；网页“豆瓣热门”按钮禁用并标注暂不可用，中英文均有提示。当前真实榜单由 TMDB/SIMKL 提供。

官方依据：[SIMKL 榜单说明](https://simkl.docs.apiary.io/reference/anime/genres)、[SIMKL 新版文档](https://api.simkl.org)、[海报地址约定](https://api.simkl.org/conventions/images)。SIMKL 榜单标题按官方要求标注来源，数据文件不附加随机查询参数。

## 真实下载与处理

使用 WebTorrent 官方发布的开放短片 Sintel，而非商业资源站测试资源。原片版权：Blender Foundation，CC BY 3.0，保留片尾署名。来源：[WebTorrent 免费测试种子](https://webtorrent.io/free-torrents)、[Blender 官方说明](https://durian.blender.org/about/)。

- 下载量 129,302,391 字节；官方种子 infohash 为 `08ada5a7a6183aae1e09d831df6748d566095a10`。
- 本地独立 qBittorrent 实际下载完成。验收脚本按官方种子文件顺序重新计算全部 piece SHA-1，逐一匹配，不仅依赖进度 100%。
- 网页网关提交计划与任务，同一个请求重放仍只有一个任务；MCP 查询到同一条完成记录。
- 使用现有真实模型服务，worker 完成识别、规范命名、视频硬链接入库。源视频与库视频 inode 一致，字节未改变。
- 字幕流程发现九份真实旁车字幕，从英文字幕翻译生成中文字幕，保存一条字幕记录，任务最终为 `completed`。
- 真实 HTTP 验证普通用户不可读取该任务；授予 read 后可读但不能重试；撤销后不可读；禁用用户立即使其会话失效。
- local 分组停止时，cloud 网关健康接口仍可达，任务查询/操作返回 503。重启后同一任务保持完成，qBittorrent 仍只有该任务，worker 恢复就绪。

所有文件、SQLite 和下载器状态均位于有 `.acceptance` 标记的可丢弃测试副本，不挂载正式媒体；既有生产容器未重建或重启。脚本不接管其他下载任务，不删除文件。

## Public 站点与双语

独立 Jackett 实例配置自带的 Nyaa public 定义，无站点账号。直接查询 `Frieren` 和 `葬送的芙莉莲` 均返回真实资源。首次应用级验收发现季集编码导致零结果，因此增加原名、中文名、英文元数据标题，以及有界的无后缀回退搜索；保持冻结季集范围和下载后身份校验。

最终应用验收：两个输入均映射为 `tv:209867`，指定 S01E01 时返回八个可用候选，下载计划仍为第一季第一集。该正向结果来自增加英文元数据标题后的搜索，无后缀回退另有独立测试。public 站点不保证资源标题真实，文件身份仍在下载后核对。

网页语言在登录页和顶栏切换，保存在当前浏览器。仅翻译开发者编写的界面模板和文案，作品名、资源名、用户输入、服务返回数据与 JSON 不经过翻译替换。English 与中文搜索均使用真实元数据/索引接口。public 站点的搜索验收不提交这些影视资源下载。

## 验证入口

- `tests/manual/acceptance_catalog_live.py`：临时 SQLite，真实榜单八组及详情映射。
- `tests/manual/acceptance_download_live.py`：只接受指定隔离下载器、标记 state/data；提交、哈希/硬链接/字幕、网页/MCP/权限验证。
- `tests/manual/acceptance_recovery_live.py`：重启前、断线期间、恢复后的三阶段验证。
- `tests/manual/acceptance_search_live.py`：真实中英文作品映射、local/cloud Provider、Jackett public 资源搜索，不提交下载。
- `tests/test_i18n.mjs`：默认语言、英文文案、动态内容不被翻译、选择持久化。

实际双机网络、真实私有站账号，以及每一家 public 站点的可达性不由上述单一站点结果推断。当前没有进行新加坡部署，也没有全量接管已有下载器。

## 当前本地验收实例

网页权限与交互已继续改进，普通用户使用下载/媒体管理能力开关，交互具备加载状态、防连点和手机适配；相关回归保留在 `tests/test_ux.mjs`、`tests/test_i18n.mjs` 与平台测试中。本文的旧对象授权测试是当时的后端兼容性记录；当前普通用户不需要填写对象 ID 或分配记录。

地址：`http://192.168.8.1:18414`。测试账号仅保存在忽略的 `state/live-login.txt`。右上角或登录页可切换 English / 中文。此实例连接真实 TMDB/SIMKL、独立 Jackett、独立 qBittorrent 和真实 worker，点击确认下载会实际创建任务；它使用测试媒体盘，不是正式媒体库。

副本目录为忽略的 `state/platform-compose-acceptance-20261025`；保留 local/cloud 分组供人工检查。原来的 18314 是首版虚构数据预览，不作为本次真实测试入口。停止新验收实例时，在 NAS 的该副本目录依次执行 `sh setup.sh cloud stop`、`sh setup.sh local stop`，保留状态和下载文件即可恢复。
