# 测试与手工验收

`test_*.py` 是自动化回归，使用临时 SQLite 和测试目录；`test_*.mjs` 验证中英文界面和请求协调。请在 Linux 环境串行、低优先级运行：

```sh
nice -n 15 python -m unittest discover -s tests -p 'test_*.py'
nice -n 15 node --test --test-concurrency=1 tests/test_i18n.mjs tests/test_ux.mjs
```

`manual/` 不参与自动发现，也不由部署脚本执行。保留这些脚本是为了复验文件安全和部署行为，不能对生产下载器、真实媒体或原数据库直接运行：

| 工具 | 用途 |
| --- | --- |
| `acceptance_sqlite.py` | 一次性数据库和媒体目录内，验证下载、租约、硬链接、字幕；可选真实专用 qBittorrent 和云端准备材料 |
| `acceptance_cloud_tcp.py` | 固定隔离端口上的真实 HTTP/MCP、搜索、榜单与配对，不提交下载 |
| 其他 `acceptance_*.py` | 账号、权限、搜索、下载恢复等历史隔离场景；部分脚本固定了测试端口、账号或日期，运行前逐项核对 |
| `preview_platform.py` | 虚构数据的浏览器 QA 服务，不连接下载器或启动 worker |
| `verify_package.py` | 安装后的包、命令入口和静态资源核验 |
| `verify_cloud_evidence.py` | 读取保留的隔离证据，核对源字节和硬链接 |

手工脚本中有跨文件工具引用时，在项目根目录设置 `PYTHONPATH=tests:tests/manual`。文件/数据库验收还必须使用脚本要求的 `.acceptance` 标记、一次性 state 与 media 挂载。历史结果在 `docs/history/`；历史结果不代替改动后的回归。
