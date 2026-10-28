# local / cloud 命名统一验收 · 2026-10-28

## 实现

- Compose、命令入口、状态标识和启动/健康检查区分 `local-control`、`local-worker`、`local-mcp` 与 `cloud-web`、`cloud-mcp`。
- 模板按所属端与职责分类。cloud 网站、FRP 映射、MCP、NAS 媒体宿主机目录和状态目录使用明确前缀；旧变量和命令别名仍可兼容。
- `setup.sh` 先构建镜像，再仅迁移相同 Compose project、相同实际工作目录下的旧应用容器。Compose project 标识和依赖服务保持稳定，不移除卷。
- MCP 的新命令显式选择 local/cloud 角色，避免统一模板中另一端的变量改变入口职责；通用 `media-mcp` 保留原有自动选择逻辑。

## 隔离验证

144 项 Python 回归通过，覆盖 canonical/legacy 优先级、实际监听参数、显式角色、原私有配置保留、匹配目录的旧服务迁移及跨目录容器不受影响。通过 Docker Compose 分别渲染 local/cloud 与旧/新配置四个组合，确认服务键、端口、命令和媒体宿主机挂载路径。渲染结果仅输出已选检查字段，没有输出完整环境或凭据。

## NAS 部署证据

通过唯一部署入口 `sh setup.sh local` 完成迁移，退出码 0。当前应用容器为：

- `media-standalone-local-control-1`：healthy。
- `media-standalone-local-worker-1`：healthy。

旧 `web` / `worker` 应用容器已迁移。控制 API 仍监听原端口 8109，真实 HTTP 健康响应的服务名为 `media-local-control`。媒体挂载仍为 `/data -> /data`，状态目录仍为原 `state -> /state`。新进程读取 807 条媒体映射、2,879 项索引，媒体首批查询返回 100 条。已安装五个角色命令；已安装的控制 API、MCP 和配置模块 SHA256 与工作副本一致。

本地私有 `.env` 仅将可明确归属的变量改名，原值保持不变；迁移前已备份私有配置与 SQLite，更新前没有活动 acquisition。未提交 `.env`、运行状态、凭据或备份。

云端运行环境本次未重建；云端服务定义、入口、端口配置和兼容渲染已完成验证。云端更新代码后执行 `sh setup.sh cloud` 才会迁移运行中的旧服务名，不能将本次 NAS 部署当成云端已部署证明。
