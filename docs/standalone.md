# 传统单机部署

适用于可信个人 LAN；MCP 默认免认证。云端/NAS 分离部署请使用[两端部署](split-deployment.md)。

## 先准备这些

- Linux / OpenWrt 主机，Docker 和 Compose 可用，镜像支持主机 CPU 架构。命令在服务器执行，Windows 上编辑代码不等于已部署。
- 本机磁盘有下载、做种及字幕空间。下载和媒体库在同一个文件系统；SQLite 的 `state/` 不放 SMB/NFS。客户端通过共享目录编辑代码不影响服务器用本地路径运行。
- TMDB API key。没有它不能正常定位作品。
- 已运行的、与本项目适配的 **Codex App Server WebSocket 端点及其 bearer token**。默认 `ws://127.0.0.1:8108`；本项目不安装、不登录、不启动该模型服务。这个 token 不是 Media MCP 登录 token，也不是直接拿 OpenAI API key 替代。
- 一个能到达主机局域网地址的 MCP 客户端。客户端是否支持 HTTP MCP、是否允许调用写入工具，需要在客户端确认。

先检查：

```sh
docker version
docker compose version
```

只有旧版 `docker-compose` 时启动器也支持。配置路径、端口与模型依赖见 [部署与运维](deployment.md)。

## 5 步快速开始

### 1. 准备配置

在服务器进入此目录（若在父仓根目录，先 `cd media`）：

```sh
cp -n .env.example .env
chmod 600 .env
mkdir -p state
```

已有 `.env` 时保留它，不覆盖。编辑 `.env`，最少填写：

```dotenv
TMDB_API_KEY=你的TMDB_APIKey
CODEX_APP_SERVER_URL=ws://127.0.0.1:8108
CODEX_TOKEN_FILE=./state/codex-token
```

`QBITTORRENT_URL`、`JACKETT_URL` 留空时，自动启动内置服务（默认端口 18211、18212）；填写时使用已有服务，账号及 API key 在私有 `.env` 设置。可只填写其中一个 URL。复用已有 Jackett 还需只读挂载配置目录，见部署文档。

将**与该模型端点匹配的现有 token 文件**保存到 `CODEX_TOKEN_FILE` 指向的位置；它是服务器上的宿主机文件，不是容器内路径。通过本地文件编辑器或已有凭据文件复制，不在聊天、命令参数或日志中展示内容：

```sh
chmod 600 state/codex-token
```

如果使用其他路径，对那个文件设置权限。文件内容必须是原始 bearer token 文本，而不是 JSON、文件路径或带 `Bearer ` 前缀的请求头。该文件会只读挂载给 MCP/worker。

可选填写 `BARK_URL`（完整设备推送地址，包含私有 key）和字幕 Provider keys。没有 Bark 时只写本地通知日志，没有字幕 key 时仍可能使用已有/内嵌字幕及翻译，但不能保证每部作品都能找到中文。

### 2. 启动

```sh
sh setup.sh
sh setup.sh status
```

首次构建需要下载镜像、依赖和 OCR 工具，耗时取决于网络与主机。成功启动 MCP 不等于 worker 就绪；模型认证与硬链接探针通过后 worker 才开始提交下载和处理。

| 入口 | 默认地址 |
| --- | --- |
| Media MCP | `http://主机局域网IP:18210/mcp` |
| qBittorrent 网页 | `http://主机局域网IP:18211` |
| Jackett 网页 | `http://主机局域网IP:18212` |

`主机局域网IP` 要换成实际地址，不是浏览器所在电脑的 localhost。默认 `MEDIA_LOCAL_MCP_BIND=0.0.0.0` 表示监听，不是访问地址；先保留默认值，用防火墙限制访问网段。

### 3. 配置 Jackett

打开 `18212` 页面，选择 **Add indexer / 添加索引器**，添加你有权限使用且支持所需媒体类型的站点。逐站点填写必要的账号、cookie 或其他设置，保存后执行 **Test**，再用 **Manual Search** 搜索一个确切片名和原名。

**Test 返回最近资源，不等于片名搜索有效。** 内置 Jackett 首次启动没有站点，需要添加；复用已有 Jackett 时需挂载其配置目录，API key 可从配置自动读取或在 `.env` 指定。详细步骤、代理和挑战页面排错见 [Jackett 配置](jackett.md)。

### 4. 连接 MCP 并验证

在客户端添加上述 `/mcp` HTTP 地址，默认选择无认证。首次连接或更新后说：

> 请先调用 media_status 检查服务，再调用 media_get_workflow 读取流程。

正常应看到 `worker_ready=true`、`tmdb_configured=true`、`indexer_configured=true`、`configured_sites>0`。这些只是就绪信息，不保证外部站点搜索、字幕和手机推送均有效。

云端客户端不能仅凭你的局域网 IP 直接访问服务。需要自行建立受保护的网络通路；本目录不创建隧道，也不要直接把免登录端口映射到公网。使用自定义主机名时将其加入 `MEDIA_ALLOWED_HOSTS`，详见部署文档。

### 5. 开始使用

只查看资源，不下载：

> 帮我找《星际穿越》（2014）的电影资源，列出来看看，先不要下载。

自动下载并处理：

> 帮我下载《星际穿越》（2014），自动选择合适资源，完成规范命名、硬链接入库、中文字幕处理后推送通知。

剧集范围：

> 帮我下载《某剧》第二季第 1–3 集，要求 1080p，并处理中文字幕。

查进度：

> 检查刚才任务的进度，分别说明下载、入库和字幕状态。

为已入库作品补字幕：

> 检查《星际穿越》的媒体库记录，用返回的 media_id 调用 media_run_subtitles，重新处理并核验中文字幕，不要重新下载电影。

不要沿用其他安装实例的 `media_id`。已有版本冲突、同名歧义或关键错误会要求复核。只有明确要求下载时才提交；仅请求列资源不会授权下载。提交后会返回 `job_id`，聊天关闭也会继续，但这不等于已经完成。

## 文件保存在哪里

```text
media/
  .env                         私有部署配置
  state/media.sqlite3          任务、映射、字幕和恢复记录（含 WAL/SHM）
  state/codex-token            模型连接凭据
  state/notifications.jsonl    本地通知记录
  services/qbittorrent/        下载器配置及任务恢复状态
  services/jackett/            索引器、登录信息和内部 API key
  data/downloads/              原始下载与做种文件
  data/media_hub/              规范路径的视频硬链接和字幕
```

默认不接管父项目或其他下载器的任务。硬链接共享视频字节，不等于又复制了一份视频；字幕会单独写入。不要原地编辑硬链接视频，否则做种源文件也会变化。

字幕优先复用/提取中文，再在线搜索、同步，按流程 OCR 或翻译。中文文本候选检查对白覆盖率；来源标签与文件名不能证明语言正确。没有可用素材、额度不足或翻译失败会报告缺失/复核，不能保证每次成功。历史完成任务不会自动重查；重处理不需要重下视频。

## 更新、重启与排错

更新代码后仍运行：

```sh
sh setup.sh
```

它重建 Media 镜像、更新 MCP/worker，并启动未指定 URL 的内置依赖；已有配置和数据保留，外部依赖不初始化。仅重启容器不会加载新代码。本命令不是更新第三方镜像的保证；升级方法和备份见部署文档。更新后重新读取 workflow。

```sh
sh setup.sh status
sh setup.sh logs
sh setup.sh stop
```

停止会暂停 Media 监控及处理，并停止当前选中的内置依赖；外部下载器不受影响，其下载可继续。不删除持久状态。`logs` 只用于本机排错，分享前脱敏。若发生 `submission_unknown`，不能更换请求 key 重复下单。

- [部署与运维：配置表、网络、备份恢复、常见错误](deployment.md)
- [0.3 首版本地验收：测试范围、结果与演示入口](history/platform-acceptance.md)
- [真实榜单、public 中英文搜索、实际下载与双语界面验收](history/live-acceptance.md)
- [Jackett：添加站点、验证搜索、代理与挑战页面](jackett.md)
- [安全检查：已修复问题、默认信任边界、尚存风险](security-review.md)
- [整改后本地功能验收：真实下载、字幕、角色、配额与恢复](history/local-functional-acceptance-20261026.md)
- [正式部署与旧库接管：云端网站/Jackett、本地下载器及已有硬链接](production-cutover-plan.md)
- [Skill](../skills/media-acquire/SKILL.md) · [迁移边界](migration.md) · [历史隔离验收](acceptance.md)
