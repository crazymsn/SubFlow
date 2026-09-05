# Apple Silicon GPU 支持与验收记录（1.3.1）

代码实现 Apple M 系列原生客户端的 MPS 自动配置，默认 Whisper 与 GPT-SoVITS 使用 Apple GPU。当前环境没有可用的实体 Apple GPU，因此 GPU 端到端实机验收仍未完成，不能将依赖安装和客户端构建成功当作实际 GPU 推理成功。

## 实现范围

- 原生 macOS arm64 自动安装 Python 3.11 和带 MPS 的 PyTorch / torchaudio 2.5.1；依赖环境与主程序隔离。
- 旧版缓存升级时准备原生识别环境，避免复用 Intel / Rosetta Python。用户显式指定的自定义 Python 保持优先。
- Whisper 权重通过 CPU 加载，处理 MPS 不支持的稀疏对齐缓冲区，再将神经网络迁移到 GPU；标准识别不启用词级时间戳。
- GPT-SoVITS 默认 MPS + float32；不兼容的 STFT 频谱预处理在 CPU 完成，结果回传 GPU。
- 在导入 Torch 前设置不支持算子的 CPU 回退。模型加载、Whisper 推理或非流式配音出现 GPU 错误时记录原因并尝试 CPU；重试失败正常报错，不返回伪造的静音成品。
- 旧版托管 GPT-SoVITS 源码自动更新并保留已下载模型；自定义安装目录不自动覆盖。
- `/subflow/runtime` 返回配音实际设备、精度和 Torch 版本，便于确认是否发生 CPU 回退。

## 验证证据

构建源码：`f5a2e5a48d03ec3bec1d48083cc0a2ea48a019e8`。

最新构建：[GitHub Actions 33970237662](https://github.com/crazymsn/SubFlow/actions/runs/33970237662)，整体成功。Windows、Apple Silicon、Intel Mac 均完成测试、从零准备推理依赖、打包与实际启动检查；Docker 完成构建与 Compose CPU 检查。此次提交 main 生成 Actions 构建产物，没有创建新的 Release。

| 平台 | 构建产物 / 检查结果 |
| --- | --- |
| Apple Silicon（macOS 14+） | [SubFlow-macOS-arm64](https://github.com/crazymsn/SubFlow/actions/runs/33970237662/artifacts/9970744982)；原生 arm64 安装器与内置 FFmpeg / FFprobe 启动成功 |
| Intel Mac（macOS 15+） | [SubFlow-macOS-x64](https://github.com/crazymsn/SubFlow/actions/runs/33970237662/artifacts/9970821762)；构建与启动检查成功 |
| Windows x64 | [SubFlow-Windows-x64](https://github.com/crazymsn/SubFlow/actions/runs/33970237662/artifacts/9970775918)；构建与启动检查成功 |
| Docker / Compose CPU | 镜像构建、CLI 启动和隔离依赖检查成功 |
| Apple GPU 探测 | [apple-gpu-report](https://github.com/crazymsn/SubFlow/actions/runs/33970237662/artifacts/9970725505)；依赖支持 MPS，虚拟机 GPU 不可用，`gpu_verified=false` |

Actions 产物需要登录 GitHub 下载，并受 GitHub 的保留期限约束。

本地完整回归为 **307 项通过、1 项跳过**，核心覆盖率 **84.90%**；Ruff 通过，mypy 检查的 70 个源码文件通过。验证包含设备选择、MPS 稀疏缓冲区加载、CPU 重试、重试失败传播、旧版缓存升级及诊断路径。另已在 Windows CPU 环境实际执行中文语音识别和 GPT-SoVITS 配音，新配音代码生成了可读取的 4.08 秒音频。CPU 实测不能作为 Apple GPU 实测证据。

## 托管 GPU 的限制

GitHub 标准 macOS ARM 虚拟机安装的两套 Torch 环境均报告 `mps_built=true`，但最小 GPU 张量分配失败。探测器因此记录 `gpu_usable=false`、`gpu_verified=false`，不运行后续 GPU 模型检查。GPU 计算阶段发生的错误仍使检查失败。

此现象与 runner-images 仓库记录的 [MPS 分配失败问题](https://github.com/actions/runner-images/issues/11899) 相符。没有通过关闭 MPS 内存上限绕过问题。CI 可验证原生依赖安装、客户端启动与打包，不能在这台虚拟机上完成 GPU 模型验收。

## 实体 Mac 的验收步骤

使用 macOS 14+ 原生 Apple Silicon 客户端，选择默认 Whisper 引擎，完成首次环境和模型下载。确认识别日志出现 `MODEL_LOADED device=mps`，且任务结束记录仍为 `device=mps`。配音请求前后查询本机配音 API 的 `/subflow/runtime`，确认 `device` 为 `mps`、`is_half` 为 `false`。

源码诊断命令：

```bash
python -m pip install -e .
python scripts/check-apple-gpu.py --require-gpu
```

该脚本在自动准备的隔离环境中分别检查实际 GPU 分配、矩阵运算、Whisper 编解码与配音频谱传输，写入 `apple-gpu-report.json`。严格模式在 GPU 不可用时返回失败；它仍不替代完整模型的视频验收。

实际任务还应验证：中文原片输出简体或繁体保留原声；跨语种视频可以完成识别、配音和导出；对生成音频试听，并记录模型、芯片、内存、处理耗时及是否发生 CPU 回退。

## 平台边界

- Apple GPU 走原生 macOS arm64 客户端；Intel Mac 使用 CPU。
- WhisperX / CTranslate2 识别仍使用 CPU，Apple GPU 请用默认 Whisper。
- macOS 上的 Linux Docker Compose 不提供原生 MPS，当前 Compose 使用 CPU；ARM Linux 镜像另行验收。
- 未宣称所有 Apple M 芯片、所有模型或长视频性能均已完成实机测试。客户端当前未做 Apple 开发者公证，首次打开可能需要系统安全设置允许。
