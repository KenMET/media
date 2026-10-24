# 历史验收与提取记录

本页是历史资料索引，不是当前镜像的重新验收证明。首次配置与当前使用请阅读 [README](../README.md)，本轮检查结果见 [安全检查](security-review.md)。

| 历史资料 | 用途 |
| --- | --- |
| [0.2 隔离验收](history/acceptance-0.2.md) | SQLite、内置下载器/Jackett、LAN 默认方案的原始验收 |
| [0.2 运行收据](history/runtime-receipt-0.2.json) | 当时的镜像和源码哈希，不用于校验当前代码 |
| [0.1 隔离验收](history/acceptance-0.1.md) | 已被默认方案替代的 MySQL/OAuth 验收记录 |
| [0.1 运行收据](history/runtime-receipt-0.1.json) | 旧版镜像和源码哈希 |
| [最初交付目标](history/GOAL.md) | 历史交付范围，不是后台任务调度配置 |
| [提取来源清单](history/source-manifest.json) | 原仓提取路径和源文件哈希；destination 相对 media 根目录，不是相对 history |

这些文件不参与构建或服务运行，集中保存以便迁仓后追溯。不应按旧文档重新配置当前服务。运行配置、任务记录和媒体文件不存放在此历史目录。
