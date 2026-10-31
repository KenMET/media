# 发现页榜单分页

TMDB 今日趋势、本周趋势和历史高分支持上一页、下一页及当前页码显示。
分页使用来源返回的总页数，最多访问 500 页。切换来源、电影／剧集或榜单时回到第一页。
SIMKL 使用其前 100 名榜单，校验有效条目后按每页 20 条展示；无法继续访问榜单之外的内容。

`GET /api/discover` 接收 `page`（1–500，默认 1），返回 `page`、`total_pages`、
`has_next` 及当前页的 `items`。TMDB 各页独立缓存；SIMKL 各页复用同一份来源缓存。
数据源失败时只回退到相应榜单／页的缓存，并保留已有的过期提示。
旧版预览缓存保留在数据库，新版使用独立缓存键以避免混用响应格式。

隔离的浏览器验收（需要 Playwright 和 Chromium）：

```sh
node tests/manual/acceptance_catalog_pagination.cjs
```

此验收模拟所有 API 请求，不连接真实媒体。可通过 `PLAYWRIGHT_MODULE` 指定已有 Playwright 模块。

部署仍使用现有入口：云端网站运行 `sh setup.sh cloud up`；分离部署的 NAS 控制端运行
`sh setup.sh local control`。单机部署使用 `sh setup.sh up`，会涉及 worker，需等待安全检查点。
代码推送不会自动更新其他主机的容器。
