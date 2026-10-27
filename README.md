# Media

通过网页或 MCP 搜索媒体、选择资源并提交下载；后台完成文件校验、规范命名、硬链接入库和字幕处理。项目独立运行，不依赖父仓的 `apps` 包。

## 服务分工

| 云端 | NAS / 本地 |
| --- | --- |
| 网页、MCP、TMDB/SIMKL 榜单与搜索、Jackett、种子获取 | 控制 API、下载器、worker、AI 处理、媒体和任务数据库 |

云端通过已有 FRP 的本机映射端口连接 NAS；NAS 不需要云端地址。反向代理、证书和 FRP 继续由现有服务管理。

## 两端部署

需要 Linux、Docker 与 Compose、本地磁盘，以及可用的模型服务和匹配的凭据文件。

1. **NAS**：复制统一的 [.env.example](.env.example) 为 `.env`，填写 local / NAS 分组，核对控制端口、下载器、媒体目录、模型地址与凭据文件，然后执行 `sh setup.sh local`。
2. **FRP**：例如将 NAS `127.0.0.1:18213` 转发到云端仅本机可达的 `127.0.0.1:28213`。
3. **云端**：同样复制 [.env.example](.env.example) 为该主机的 `.env`，填写 cloud 分组，核对网站/MCP/映射端口、TMDB key 与已有 Jackett 地址，然后执行 `sh setup.sh cloud`。
4. **反代**：网站指向本机 `18214`，可选 `/mcp` 指向本机 `18210`。创建网站管理员后使用；云端 MCP 使用可撤销的用户令牌。

已有 `.env` 不要覆盖。内部凭据首次自动配对，不需要手工填写 token 或重复配置域名。默认值和 Docker 反代条件项见[两端部署说明](docs/split-deployment.md)。同机先测试见[本地测试](docs/platform-testing.md)。

已有 qBittorrent / Jackett 地址非空就复用；留空才在其所属部署端启动内置服务。云端 Jackett 固定持久化到 `/root/container_cache/jackett/config` 和 `downloads`。

`TMDB_API_KEY` 在 cloud 配置；OpenSubtitles、SubDL、ASSRT 的可选字幕 key 在 NAS 模板中配置，留空跳过对应来源。网页目前不编辑这些部署凭据。

## 数据与安全

- `MEDIA_DATA_DIR` 下的 `downloads`、`media_hub` 分别保存源文件和媒体硬链接；硬链接目录须与下载目录位于同一文件系统，且下载器与 worker 的容器内路径一致。
- NAS 的用户、任务和恢复记录默认在 `./state`，云端缓存与搜索快照默认在 `./state-cloud`。容器重建保留绑定目录；换部署目录时不要丢弃原状态。
- 不自动接管下载器的其他任务。`submission_unknown` 必须按原任务核对，不换 key 重复下单；重试不提供删除能力。
- 旧 MySQL 和已有媒体须按[正式接管方案](docs/production-cutover-plan.md)迁移，启动命令不会自动导入。不要将隔离测试状态当作生产数据库。
- 私有 `.env`、凭据和运行目录不提交 Git。个人 LAN 免认证的[传统单机模式](docs/standalone.md)仍支持，不应转发到公网。

## 日常命令

```sh
sh setup.sh local status
sh setup.sh local logs
sh setup.sh local stop

sh setup.sh cloud status
sh setup.sh cloud logs
sh setup.sh cloud stop
```

更新代码后再次执行对应的 `sh setup.sh local` 或 `sh setup.sh cloud`；仅重启容器不会加载新代码。部署入口只有 `setup.sh`。

两端构建文件统一命名：本地使用 `compose.local.yml`、`Dockerfile.local`，云端使用 `compose.cloud.yml`、`Dockerfile.cloud`。不带分组的传统单机入口仍使用 local 文件。

## 目录与文档

```text
src/media_mcp/     运行源码和网页资源
tests/            自动化回归
tests/manual/     隔离环境的手工验收工具
docs/             当前部署、使用、迁移与安全说明
docs/history/     历史报告和提取记录
skills/           MCP 使用流程
```

- [部署与运维](docs/deployment.md) · [Jackett 站点配置](docs/jackett.md)
- [测试说明](tests/README.md) · [历史验收索引](docs/acceptance.md)
- [安全边界](docs/security-review.md) · [迁移边界](docs/migration.md)
- [AI 使用流程](skills/media-acquire/SKILL.md)
