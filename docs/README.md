# SubFlow 语幕文档

本目录的使用指南对应 **1.3.46**。官方发布包见 [GitHub Release](https://github.com/crazymsn/SubFlow/releases/tag/v1.3.46)，项目概览见 [仓库首页](../README.md)。

## 用户指南

| 文档 | 适用场景 |
| --- | --- |
| [桌面客户端](desktop.md) | Windows / Mac 安装，首次处理，字幕和配音设置 |
| [Docker Compose](docker.md) | 拉取镜像，处理视频，持久化，更新及源码构建 |
| [安装与环境](install.md) | 源码运行，CPU / MPS，环境变量，依赖位置，打包 |
| [API 令牌](api-key.md) | 何时需要令牌、实际存储方式及轮换 |
| [故障排除](troubleshooting.md) | 按症状定位安装、下载、处理和导出问题 |
| [M1 MacBook Air 验收](mac-self-test.md) | 在真实 Apple GPU 上确认识别、配音及 CPU 回退 |

## 发布与开发

| 文档 | 内容 |
| --- | --- |
| [1.3.46 发布验收](release-1.3.46.md) | 构建提交、CI、客户端与 Docker 的验证范围 |
| [更新记录](../CHANGELOG.md) | 当前发布改动及历史源码变更 |
| [架构](architecture.md) | 模块、数据流、任务配置与缓存边界 |
| [翻译 API 实现契约](api-meding.md) | 端点、重试、模型筛选与缓存 |
| [贡献指南](../CONTRIBUTING.md) | 开发环境、检查命令、PR 与发布流程 |
| [代码审查进度](code-audit-status.md) | 已检查事项及仍需验证的范围 |

## 历史记录

以下记录保留当时的测试结果，不能作为当前安装步骤或最新通过数量。记录中的旧包和本地临时证据可能已清理；GitHub Releases 及版本标签仅保留 1.3.46。

- [2026-09-05 修复与验收](qa-2026-09-05.md)
- [早期社区包验收](community-qa-2026-09-05.md)
- [Apple GPU 实现与阶段检查](apple-gpu-qa-2026-09-05.md)
- [1.3.34 CPU 媒体验收](cpu-media-qa-1.3.34.md)
