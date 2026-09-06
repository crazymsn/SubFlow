# SubFlow 语幕文档

使用指南对应 **1.3.60**。从 [最新 Release](https://github.com/crazymsn/SubFlow/releases/latest) 下载完整客户端，Docker 使用 `crazymsn/subflow:latest`。本次变化与验证边界见 [1.3.60 发布说明](release-1.3.60.md)。

## 用户指南

| 文档 | 适用场景 |
| --- | --- |
| [桌面客户端](desktop.md) | Windows / Mac 安装，首次处理，字幕和配音设置 |
| [客户端环境与设备支持](runtime-coverage.md) | 完整包依赖、芯片与 GPU 覆盖、WhisperX 修复、翻译继续 |
| [Qwen 音色与设备](voices.md) | 23 种官方 / 设计音色、八语种男女声、跨语种试听、CUDA / Apple GPU / CPU 选择 |
| [Docker Compose](docker.md) | 拉取镜像，处理视频，持久化，更新及源码构建 |
| [安装与环境](install.md) | 源码运行，CPU / MPS，环境变量，依赖位置，打包 |
| [API 令牌](api-key.md) | 何时需要令牌、实际存储方式及轮换 |
| [故障排除](troubleshooting.md) | 按症状定位安装、下载、处理和导出问题 |
| [Mac 实机验收手册](mac-self-test.md) | M1 / Intel 详细步骤、四套环境、八语种、GPU / CPU、翻译恢复与证据模板 |

## 发布与开发

| 文档 | 内容 |
| --- | --- |
| [1.3.54 本地验收](qa-1.3.54.md) | WhisperX GPU / CPU 识别、随包环境、翻译断点与界面验证 |
| [1.3.53 本地验收](qa-1.3.53.md) | 新音色、GPU / CPU 合成、常显设置及清理范围 |
| [1.3.60 发布说明](release-1.3.60.md) | 构建提交、CI、客户端与 Docker 的验证范围 |
| [1.3.60 发布验收](qa-1.3.60.md) | 翻译失败恢复、Mac 打包修复、三平台离线合成与镜像校验 |
| [1.3.48 本地质量验证](quality-qa-1.3.48.md) | 固定字号、自然语速与实际视频验收 |
| [1.3.49 音色与布局验证](quality-qa-1.3.49.md) | 标准音色与克隆对比、单行字幕、GPU 实测及验证边界 |
| [更新记录](../CHANGELOG.md) | 当前发布改动及历史源码变更 |
| [架构](architecture.md) | 模块、数据流、任务配置与缓存边界 |
| [翻译 API 实现契约](api-meding.md) | 端点、重试、模型筛选与缓存 |
| [贡献指南](../CONTRIBUTING.md) | 开发环境、检查命令、PR 与发布流程 |
| [代码审查进度](code-audit-status.md) | 已检查事项及仍需验证的范围 |

## 历史记录

以下记录保留当时的测试结果，不能作为当前安装步骤或最新通过数量。记录中的旧包和本地临时证据可能已清理；旧 Release 清理后请通过最新发布页下载。

- [2026-09-05 修复与验收](qa-2026-09-05.md)
- [早期社区包验收](community-qa-2026-09-05.md)
- [Apple GPU 实现与阶段检查](apple-gpu-qa-2026-09-05.md)
- [1.3.34 CPU 媒体验收](cpu-media-qa-1.3.34.md)
