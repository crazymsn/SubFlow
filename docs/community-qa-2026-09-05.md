# 社区版本验收（2026-09-05）

> 历史记录：此文件保留当时的结果和版本状态，不代表当前安装包。最新使用说明见[文档索引](README.md)。

> 历史技术记录：下文描述当时的版本和验证范围，旧安装包及本地临时证据可能已清理。当前安装请使用 [1.3.46 指南](README.md)，最新发布检查见 [1.3.46 验收记录](release-1.3.46.md)。

## 分发方式

SubFlow 1.3.0 桌面包自带 FFmpeg、uv 和 GPT-SoVITS 源码。用户首次运行时在私有目录安装 Python 3.11 与隔离的 CPU 推理环境并下载模型；后续复用缓存。Windows x64、Apple Silicon Mac、Intel Mac 分别构建。Docker Compose 从源码构建 CPU 镜像，模型以命名卷持久化。

无独立显卡的设备可以识别、配音、烧录视频；速度取决于 CPU、内存和模型大小。首次需要网络，翻译接口需要用户自己的令牌。Mac 当前使用临时签名，没有 Apple 开发者公证。

## 本机实际验证

- 完整测试：284 项通过，1 项跳过；核心覆盖率 84.89%。Ruff 与 mypy 检查通过。
- 空白缓存目录：uv 自动下载 Python 3.11，建立独立 Whisper / GPT-SoVITS CPU 环境。
- GPT 模型和语言资源：从固定 Hugging Face 仓库版本下载；一次中途超时成功续传恢复。
- CPU 中文识别：真实中文测试视频得到两段识别结果。
- CPU 英文配音：新环境生成 3.10 秒非空音频。
- CPU 中文配音：新环境生成 4.44 秒非空音频，覆盖纯 Python 中文分词回退。
- 社区 Windows 包：真实启动检查通过；内置 FFmpeg、ffprobe、uv 都可以执行。
- 关闭开发用 Python 的 PATH、清空推理依赖目录后：实际客户端自行安装 Python 和 CPU 依赖，122.29 秒后服务就绪，生成 2.82 秒音频。此项复用已经下载的模型；模型首次下载由前项独立验证。
- 中文原片 → 简体／繁体：保留原声的端到端验收及回归测试见 [原验收记录](qa-2026-09-05.md)。
- 73 段真实 FFmpeg 混音覆盖跨批重叠、时间轴定位和尾部静音；1200 个长路径测试覆盖 Windows 命令长度问题。

## 跨平台验证发现并修复

1. FFmpeg 9 移除了旧滤镜脚本参数：根据版本选择新的文件参数，旧版 Docker FFmpeg 保持兼容。
2. Homebrew 默认 FFmpeg 不带字幕渲染：Mac 构建使用含 libass 的 ffmpeg-full，并由 PyInstaller 收集动态库。
3. Mac 手工应用布局找不到 Python：改为标准 PyInstaller BUNDLE；GPT-SoVITS 源码放在 Resources。
4. Intel Mac 的最新版 Numba/LLVM 缺少兼容轮子：固定到 Numba 0.61.2 / llvmlite 0.44.0。
5. Windows CI 编码与测试失败被后续命令覆盖：设置 UTF-8，并将测试和 lint 拆为独立步骤。

## GitHub 最终结果

验证代码提交：`0e3b5ae1340d8f8df1570322a1101d3a91ed8848`。

[Actions 33968799087](https://github.com/crazymsn/SubFlow/actions/runs/33968799087) 全部构建成功：

| 平台 | 结果 | 下载 |
| --- | --- | --- |
| Windows x64 | 测试、CPU 环境安装、打包、真实启动全部通过 | [Windows 安装包](https://github.com/crazymsn/SubFlow/actions/runs/33968799087/artifacts/9970393050) |
| macOS Apple Silicon | 测试、CPU 环境安装、打包、真实启动全部通过 | [Mac arm64 安装包](https://github.com/crazymsn/SubFlow/actions/runs/33968799087/artifacts/9970325320) |
| macOS Intel | 测试、CPU 环境安装、打包、真实启动全部通过 | [Mac x64 安装包](https://github.com/crazymsn/SubFlow/actions/runs/33968799087/artifacts/9970395343) |
| Docker Linux x64 | CPU 镜像构建、Compose 启动、两套推理环境检查全部通过 | 从本仓库执行 docker compose build |

三份客户端的打包后检查均返回 `ok: true`，验证了内置 FFmpeg 9.0.1、ffprobe 和 uv 0.11.8。此轮产物位于 Actions（下载需登录 GitHub，按工件保留期提供），没有额外创建 Release 标签。CPU 音频生成的实测在 Windows 完成；Mac 和 Docker 本轮验证范围为测试、依赖安装与启动，不将其描述为已完成所有设备上的长视频性能验收。

固定数值依赖后再次实测：CPU 中文识别成功，中文配音生成 4.48 秒音频。
