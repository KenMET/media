# Jackett 站点配置

本组合使用独立 Jackett 容器。默认浏览器入口 `http://主机局域网IP:18212`；容器内部端口 `9117`，**在容器里写 localhost 指向该容器本身**。

## 首次添加站点

1. 打开入口，确认是本组合的新 Jackett，不是旧服务的页面。
2. 点击 **Add indexer**，按名称、类型筛选。只添加你实际使用的站点；电影、剧集、动漫站点的覆盖范围不同，不必全部添加。
3. 公共站点也可能需要选择可用地址。私有站点按配置表要求填写你自己的登录、cookie、passkey 等；不要把这些内容或 API key 发到聊天里。
4. 保存，然后逐个 **Test**。失败时先修复本站点，不要用“已有配置文件”当作可用证明。
5. 在 **Manual Search** 只选择刚添加的站点，输入一个确切片名。分别试中文名和原名，例如 `星际穿越`、`Interstellar`，核对标题、年份与类别。
6. 再让助手执行 `media_status` 和 `media_search_releases`。`configured_sites` 是配置数量；`diagnostics` 才能说明这次各站点搜索结果。

Media 通过只读挂载读取 Jackett 的内部 API key，按配置文件逐站点搜索。**不用手填 key、不用复制 Torznab feed、不用给 qBittorrent 安装搜索插件**。通过本组合的 MCP 下载，才会带上任务所有权标签并进入受管理流程；在下载器网页手工添加的任务不会自动被接管。

## 验证什么才算成功

- **Test**：检验该站点的一次测试请求。不能证明任意关键词都被正确应用。
- **Manual Search**：确认你想找的片名能搜到相关结果。
- **Media 搜索**：确认实际站点诊断和筛选后候选。`partial` 表示部分站点失败或未在预算内完成，`failed` 表示未成功查询；都不等于电影没有资源。
- **下载**：搜到不代表可下载。种子可能没有可用做种者，站点也可能要求新的登录状态。

Media 自动查原名和本地化名称、限定媒体类别，过滤已知不匹配的标题/电影年份/画质并去重。缺少年份的电影资源可能以 `year_unconfirmed` 被保守过滤。每站请求设置 5 秒超时，每个片名有 20 秒站点调度预算；超时不是永久禁用，下次搜索会再尝试。

## 网络、代理、挑战页面

资源站不可达时，分别检查服务器/容器 DNS、出口网络、站点地址和登录有效期。在个人电脑浏览器能打开，不代表 Jackett 容器能访问。

若已有合法可用的 HTTP/SOCKS 代理，在 Jackett 的设置中填写容器可访问的代理地址及凭据；不要用宿主机上的 `127.0.0.1` 代表另一个容器或宿主机服务。不要关闭 TLS 证书验证来掩盖连接错误。

遇到 `Challenge detected but FlareSolverr is not configured`：本组合**不包含 FlareSolverr**。可以先选择不依赖该组件且能正常搜索的站点；若确有需要，按官方说明另行部署兼容实例，并让 Jackett 指向可达的实例地址。这会增加资源占用，也不保证每个站点都可通过挑战。I2P/Tor 等专用网络也不是本组合自带的出口。

上述配置入口及能力以 [Jackett 官方说明](https://github.com/Jackett/Jackett#configuration) 为准；其中 [FlareSolverr 配置](https://github.com/Jackett/Jackett#flaresolverr-configuration) 说明了额外依赖。Media 不自动安装代理、解题器或登录站点。

## 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| `configured_sites=0` | 添加并保存至少一个站点，确认打开的是本组合页面 |
| 中文查询返回最新上传列表 | 原名手工搜索对比；Media 会过滤无关结果，不应直接下载 |
| `jackett_timeout` | 查看本站点手工搜索、网络与挑战页面；可先使用其他成功站点 |
| API/查询失败 | 检查 Jackett 日志、配置文件挂载、登录有效期；不要把带 key 的 URL 贴给助手 |
| 搜索成功但下载没速度 | 看 qBittorrent 的连接、做种、tracker 错误和磁盘空间，不是重复提交任务 |
| `indexer_redirect_not_allowed` | 有效 magnet 和同源有限跳转已支持；外部 HTTP 目标仍拒绝，换可用候选或核查来源 |
| 新站点始终不生效 | 配置文件应出现在 `services/jackett/Jackett/Indexers/*.json`；检查是否误操作旧实例 |

重启/重建不会清空站点。不要把 `services/jackett/` 提交到仓库，其中可能有账号、cookie、passkey 和 API key。
