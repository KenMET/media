# 双入口平台：同机测试

当前阶段按用户要求，将 local、cloud 两组服务都放在大陆测试主机（192.168.8.1）。不需要新加坡地址、域名、FRP 或 TLS；真正公网部署留到功能验收完成后。

后续真实榜单、public 站点中英文搜索、实际下载与双语界面结果见 [真实验收记录](history/live-acceptance.md)。发现页可选 SIMKL 今日/本周榜单，无需 key；搜索与详情继续使用 TMDB。网页语言在登录页/顶栏切换，无新增环境配置项。

## 启动与端口

唯一部署入口是 `setup.sh`。正式拆机使用各自目录与角色模板。同机也可以用两个目录；若为开发测试共用一个目录和私有 `.env`，先在该文件明确以下端口及 LAN 模式（只用于可信局域网、隔离数据）：

```dotenv
MEDIA_WEB_PORT=18213
MEDIA_GATEWAY_PORT=18214
MEDIA_CONTROL_PORT=18213
MEDIA_WEB_PUBLIC=false
MEDIA_WEB_MODE=lan
MEDIA_WEB_BIND_HOST=0.0.0.0
MEDIA_SERVICE_PAIRING=false
```

两组在本机读取同一私有内部凭据文件，不需要首次配对。下载器、模型、TMDB 凭据和隔离目录按下文补充，再运行：

```sh
sh setup.sh local
sh setup.sh cloud
```

| 分组 | 服务 | 默认入口/状态位置 |
| --- | --- | --- |
| local | 控制 API、网页后端、用户/会话、worker | 18213，`state/media.sqlite3` |
| local | 下载器 | 已填 `QBITTORRENT_URL` 则复用，否则内置 18211 |
| cloud | 网页网关 | 18214，浏览器打开 `http://192.168.8.1:18214` |
| cloud | MCP | `http://192.168.8.1:18210/mcp`，个人访问令牌认证 |
| cloud | Jackett | 已填 `JACKETT_URL` 则复用，否则内置 18212 |
| cloud | 热点缓存 | `state-cloud/catalog.sqlite3` |

不带分组的 `sh setup.sh` 仍提供传统单机组合：MCP、web、worker 以及所需内置依赖。它的 MCP 默认 LAN 免登录，网页仍使用账号登录。不要在已运行分组测试的相同默认端口上再启动这个组合。

新配置由 cloud 完成搜索和种子获取；local 不再请求云端 Provider，也不需要云端地址。同机测试显式设 `MEDIA_CONTROL_PORT=18213`，cloud 即连接本机 local 控制端；真实 FRP 部署填写映射端口（默认 28213）。旧 `MEDIA_CATALOG_URL` / `MEDIA_CONTROL_URL` 仅保留兼容，已有测试配置不会自动被改写。

cloud 与 local 分开 `.env` 时各自用 `MEDIA_WEB_PORT`；旧同目录共享配置可继续用 `MEDIA_GATEWAY_PORT` 指定 cloud 端口。local 控制端改端口后，同机测试同步 `MEDIA_CONTROL_PORT`；真实部署则同步 FRPC 的目标端口。

## 测试目录与已有服务

测试必须使用新建的可丢弃目录，且不能挂载真实媒体。例如独立测试副本中的 `.env`：

```dotenv
MEDIA_DATA_DIR=./data-test
MEDIA_STATE_PATH=./state-test
MEDIA_CLOUD_STATE_PATH=./state-cloud-test
```

目录路径在 Linux 服务器配置。当前代码通过 SMB 编辑不代表 SQLite 应放在 SMB 上：运行时上述路径必须对应 NAS 自身的本地磁盘。下载目录和库目录位于同一文件系统，并在下载器与 worker 中保持相同容器路径。

如果测试下载器也是已有实例，不能指向真实下载器执行写入验收；使用独立实例、分类和可丢弃下载目录。旧项目的 `media-monitor`、量化、爬虫和其他容器不停止、不重建，也不接管它们的下载任务。

默认 `state/control-token` 会在需要时生成，不打印内容，两个分组只读挂载同一文件。它不是登录密码。若自定义 `MEDIA_CONTROL_TOKEN_FILE`，先准备好该私有文件；不要在聊天、日志或版本控制中传递内容。分组状态目录可以独立设置，凭据文件的默认路径仍是 `state/`。

## 首次登录和 AI 连接

1. local web 首次运行会在本地状态目录生成 `web-bootstrap-token`，也可使用显式配置的 `MEDIA_WEB_BOOTSTRAP_TOKEN` 或 `MEDIA_WEB_BOOTSTRAP_TOKEN_FILE`。
2. 浏览器访问 cloud 网页 18214，选择“首次初始化”，在本机私下读取令牌并输入，然后创建管理员。初始化只允许一次，没有默认管理员密码。
3. 登录后可以创建普通用户、搜索作品/种子、提交任务、查看下载/入库/字幕阶段及历史。
4. “服务与账号”中创建个人 MCP 令牌，只显示一次，有效期 30 天。客户端将它作为 bearer token 配置到 cloud MCP 的 `/mcp` 地址。禁用账号、修改密码或撤销令牌后，AI 操作同样失效。
5. 传统单机模式若需要同样的账号权限，显式设置 `MEDIA_AUTH_MODE=platform`。默认 `none` 的 LAN 所有者模式保留；历史无归属任务仅管理员可见。

网页与 MCP 共同使用本地任务状态和幂等/身份/文件保护。网页不会直接调用下载器；资源私有下载 URL 和 API key 不下发浏览器。

## 功能边界与状态

- 发现页：TMDB 日周趋势、电影/剧集；缺少 TMDB key 时显示配置状态。
- 豆瓣：有独立适配器、来源标记、缓存和失败退避。2026-10-25 在开发机对公开热门接口的实测返回 HTTP 418，未验证实际数据接入成功；NAS 出口同样返回 HTTP 418。不会用 TMDB 数据假冒豆瓣。可通过 `MEDIA_DOUBAN_ENDPOINT` 指向你允许使用、兼容 subjects JSON 的数据源。
- 豆瓣接通已按用户后续确认移出首版验收：NAS 出口对热门接口和公开榜单页同样返回 HTTP 418；首版只验收适配器、缓存与明确失败状态。
- 多用户：管理员/普通用户、启停、密码修改、个人 MCP 令牌、任务/媒体的 read/manage 分配和操作记录。分配表示应用访问权，不是复制视频或创建独立用户文件系统。
- 下载进度：下载器完成不等于入库/字幕完成；速度、ETA 带采样时间，断线不能当成最新进度。没有兼容模型服务时 worker 不进入正常处理状态。
- 本地是账号、会话、权限、任务的唯一事实来源。cloud 仅保存热点缓存，不同步数据库。local 离线时 cloud 的登录和操作不可用，已接受任务在依赖可达时继续处理。
- 当前不包括在线播放、转码、文件删除、公开注册、豆瓣想看同步、全量下载器任务接管。

## 运维与隔离验证

```sh
sh setup.sh local status
sh setup.sh cloud status
sh setup.sh local logs
sh setup.sh cloud logs
sh setup.sh cloud stop
sh setup.sh local stop
```

stop 只停止对应分组及当前由该分组管理的依赖；指定 URL 的已有服务不停止。切换已有/内置依赖不会自动退役旧容器，保留其状态后明确处理。

已有 Python 隔离环境中，串行、低 CPU 优先级执行：

```sh
nice -n 15 .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

浏览器 QA 使用 `tests/manual/preview_platform.py`：只连接虚构元数据/资源，使用临时 SQLite，不启动 worker 或连接真实下载器。它不是生产部署入口，测试账号不适用于真实系统。手工脚本分组与运行条件见 [tests/README](../tests/README.md)。

备份前停止 local 和 cloud 分组，保存匹配版本代码、整个本地状态目录（含 WAL/锁/恢复信息）、私有配置和需要保留的媒体。升级只新增平台表，不给历史任务自动分配普通用户；回滚要恢复版本匹配的一致性状态备份，不能只回退一个 SQLite 主文件。

未来真正拆到新加坡时，复用已有 HTTPS 反代与受保护 FRP 隧道，使用两端精简模板；无需重复填写域名 allowlist。直接暴露后端的旧高级模式另有要求。不要转发免登录的传统单机 MCP。
# 关于新默认值

拆机正式部署优先看 [两端精简部署](split-deployment.md)。本文件的同机 LAN 网页访问需显式 `MEDIA_WEB_MODE=lan`、`MEDIA_WEB_BIND_HOST=0.0.0.0`；cloud 新默认仅供本机反代访问。已有显式 `MEDIA_WEB_PUBLIC=false` 的旧同机配置继续按原 LAN 模式运行。
