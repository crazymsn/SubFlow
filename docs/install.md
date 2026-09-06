# 安装与运行环境

1.3.52 起，桌面构建脚本默认预装全部三个配音引擎的模型和运行环境；构建机负责首次下载，用户无需为配音再下载。完整包的空间需求、CPU/GPU 回退、分卷发布及离线验收见[完整配音包指南](offline-voices.md)。

[返回文档索引](README.md) · 适用于 **SubFlow 语幕 1.3.60**

## Windows / macOS 客户端

从 [1.3.60 Release](https://github.com/crazymsn/SubFlow/releases/tag/v1.3.60) 下载正式客户端。下载、校验和第一次处理见 [桌面指南](desktop.md)。Actions 中的开发工件不等同于新的正式发布。

- Windows x64：`SubFlow-Windows-x64.7z.*`，整夹解压并运行 `SubFlow/SubFlow.exe`。
- Apple Silicon：`SubFlow-macOS-arm64.7z.*`。
- Intel Mac：`SubFlow-macOS-x64.7z.*`。

Mac 解压后将 SubFlow.app 放入应用程序目录。当前构建没有 Apple 开发者公证，首次可能需要在系统安全设置允许打开。支持范围以构建所用 macOS 为准（Apple Silicon 14+、Intel 15+）。Windows 建议 Windows 10/11 x64。

完整客户端内置 FFmpeg、三种配音模式的模型和四套 Python 运行环境。配音不需要首次下载；识别与对齐模型按需准备，翻译仍需联网。下载同一平台全部分卷并从 `.001` 解压，为客户端、压缩包、识别模型与媒体另留足够空间。

无独立显卡也能运行。CPU 建议先用 tiny/base/small 和短片确认速度，较大模型与长视频可能耗时较长。GPU 为可选项；默认环境不会安装 CUDA 驱动。

## Apple M 系列 GPU

下载原生 `SubFlow-macOS-arm64.7z.*`，不要使用 Intel 包或 Rosetta 启动。完整客户端已内置原生 arm64 Python 和带 MPS 的 PyTorch / torchaudio，默认让 Whisper 识别、Qwen 和 GPT-SoVITS 配音优先使用 Apple GPU，无需安装 CUDA。MPS 使用 float32；频谱预处理中的不兼容运算在 CPU 完成，神经网络仍在 GPU 执行。

源码 / 精简包首次安装及旧版缓存升级自动完成；完整包优先使用随包环境。GPU 不可用时回退 CPU；Whisper 或非流式配音遇到 GPU 运算失败时会记录原因并重试 CPU。日志中的 `device=mps` 及本地配音 API `/subflow/runtime` 可查看实际设备，避免把回退 CPU 当成 GPU 验收。

默认自动 MPS 配音使用项目源码和受管理的原生解释器。新建服务前检查缓存环境，旧 venv 或电脑上的其他 GPT-SoVITS 不会代替它；环境检查或修复失败会显示错误。显式设置 `SUBFLOW_GPTSOVITS_HOME` / `SUBFLOW_GPTSOVITS_PYTHON`，或关闭自动安装时，仍按手动整合包设置处理。已经运行的兼容 API 服务仍可连接，实际计算设备需查看服务报告。

默认自动 MPS 识别也在每次任务前核验受管理环境，使用外部识别进程，避免主程序已有的 Whisper 或旧缓存绕过原生环境检查。识别解释器可用 `SUBFLOW_PYTHON` 显式指定，也兼容 `SUBFLOW_WHISPER_PYTHON`；前者非空时优先。显式路径无效或不能导入 Whisper 时会报错，需修正或清除该设置后再使用自动环境。

WhisperX / CTranslate2 不支持 MPS，选择它时识别会使用 CPU；需要 Apple GPU 请使用默认 Whisper 引擎。Mac 上的 Linux Docker 容器不提供原生 MPS，本项目 Compose 保持 CPU 模式。Apple GPU 加速请使用原生客户端。

源码用户可运行 `subflow run in.mp4 --device mps`。依赖及 GPU 运算检查：

```bash
python scripts/check-apple-gpu.py --require-gpu
```

脚本检查两套环境的 MPS 编译支持、实际 GPU 可用性、Whisper 编解码和配音频谱路径，结果写入 `apple-gpu-report.json`。无 GPU 的 CI 虚拟机只验证依赖，不计为 GPU 实机通过。该检查也不替代实际视频的完整性能验收。

## Docker Compose

默认使用 `crazymsn/subflow:latest`，支持 Linux amd64 / arm64 CPU。宿主机只需 Docker 和 Compose，首次模型下载后复用持久化卷。完整部署、PowerShell 命令、无令牌中文示例、模型卷、更新与源码镜像构建见 [Docker 指南](docker.md)。

## 源码运行

源码开发需要 Python 3.11+、Git 和 PATH 中支持字幕滤镜的 FFmpeg 6+。客户端用户不需要执行以下开发步骤。

```bash
git clone https://github.com/crazymsn/SubFlow.git
cd SubFlow
python -m venv .venv
```

Windows PowerShell 激活 `.\.venv\Scripts\Activate.ps1`；macOS / Linux 激活 `source .venv/bin/activate`。之后在仓库根目录执行：

```bash
python -m pip install -e ".[gui,dev]"
subflow gui
# 可提前准备环境
python scripts/prepare-runtime.py asr
python scripts/prepare-runtime.py gptsovits
python scripts/prepare-runtime.py qwentts
```

`qwentts` 准备 Qwen3-TTS 的独立依赖环境，模型按所选模式在首次配音时自动下载并校验，每个模型约 2.5 GB。标准音色（默认）的缓存目录为受管理环境根目录下的 `qwen3-native-0.6b`，服务地址为 `http://127.0.0.1:19882`，可通过 `SUBFLOW_QWEN_NATIVE_URL` 指定已启动的兼容标准音色服务。原声克隆的缓存目录为 `qwen3-tts-0.6b`，服务地址为 `http://127.0.0.1:9881`，对应变量为 `SUBFLOW_QWEN_TTS_URL`。两者共用独立依赖环境，模型和音频缓存分开。

环境遵循 `SUBFLOW_TORCH_BACKEND=auto/cuda/mps/cpu`；自动优先 CUDA / Apple MPS，无可用 GPU 时使用 CPU。CPU 可运行但速度取决于硬件和文本长度，Qwen3-TTS 路径尚未完成 Apple M1 实机验收。GPT-SoVITS 的地址配置单独保留。CLI 可用 `--tts-provider qwen3-native --tts-voice Aiden` 选择标准音色，或用 `qwen3` 选择克隆模式。

主程序、Whisper、GPT-SoVITS、可选 WhisperX 使用隔离环境，避免依赖互相覆盖。WhisperX 不可用时可回退标准 Whisper。

可用 `python scripts/prepare-runtime.py gptsovits --backend cpu` 显式准备 CPU 环境，或在支持的平台选择 `cuda` / `mps`。省略 `--backend` 时沿用 `SUBFLOW_TORCH_BACKEND` 和平台默认值；该参数只决定本次准备，不会改变后续客户端的设备设置。`--skip-models` 仅用于 GPT-SoVITS，跳过模型与语言资源下载。

以下旧 PowerShell 命令仍可使用，现均调用同一安装流程，不再各自创建另一套环境。运行它们的 Python 是已安装 SubFlow 源码依赖的 Python 3.11+；推理用的 Python 3.11 由安装器另行准备，因此主程序使用 Python 3.13 也可以。参数 `-Python` 可指定该主程序解释器，`-Device cpu/cuda/mps` 可显式选择本次安装后端，默认沿用应用配置。

| 兼容入口 | 当前行为 |
| --- | --- |
| `scripts/install-gptsovits-runtime.ps1` | 准备配音源码、依赖和校验后的资源；`-SkipWeights` 跳过模型及语言资源 |
| `scripts/setup-gptsovits.ps1` | 使用本项目随附、已适配的源码，准备依赖，暂不下载资源；不再克隆上游最新分支 |
| `scripts/download-gptsovits-weights.ps1` | 先准备所需源码和依赖，再下载并校验模型、语言资源；不能仅凭目录非空判为完成 |
| `scripts/bootstrap-whisperx.ps1` | 在客户端识别的 managed 位置准备固定版本 WhisperX 环境 |

环境和模型默认位置与客户端一致，见下表后的路径说明。已有手动整合包及 `SUBFLOW_GPTSOVITS_HOME` / `SUBFLOW_GPTSOVITS_PYTHON` 覆盖仍需由使用者明确管理；准备 managed 环境不会修改这些覆盖，也不会覆盖仓库内已有的 venv。

## 自动安装设置

当前源码与本地修复客户端默认使用 `auto`：Windows / Linux x64 检测可用的 NVIDIA CUDA 驱动后安装 CUDA 版 PyTorch；Apple Silicon 原生客户端安装 MPS 环境；其他设备使用 CPU。CUDA 环境独立于旧 CPU 环境，已有配音模型继续复用。驱动需要由系统正确安装，无须另装 CUDA Toolkit。完整包已预装目标平台依赖，以上自动安装规则主要适用于源码与精简包。

Windows 的 GPU 加速目前指 NVIDIA CUDA；AMD / Intel 显卡使用 CPU。GPU 内存不足或算子不兼容时，标准 Whisper 和非流式 GPT-SoVITS 会记录错误并重试 CPU。Mac 的 WhisperX 和 Docker 仍使用 CPU；Apple GPU 请用原生客户端的标准 Whisper。

| 环境变量 | 用途 |
| --- | --- |
| SUBFLOW_AUTO_INSTALL=0 | 禁止自动安装；须提前准备完整运行环境 |
| SUBFLOW_RUNTIME_DIR | Python、依赖和安装日志缓存目录 |
| SUBFLOW_GPTSOVITS_HOME | GPT-SoVITS 源码、模型及语言数据目录 |
| SUBFLOW_TORCH_BACKEND | 默认 auto：可用 NVIDIA CUDA → cuda，Apple Silicon → mps，其余 → cpu；设 cpu 可禁用自动 GPU |
| SUBFLOW_GPTSOVITS_DEVICE | auto / mps / cpu / cuda，默认跟随自动选择的推理后端 |
| SUBFLOW_SOVITS_AUTOSTART=0 | 禁用桌面启动时配音预热；需要配音时仍会按需准备 |
| SUBFLOW_GPTSOVITS_TIMEOUT | 配音请求超时秒数，默认 1800；使用正数 |
| SUBFLOW_PYTHON / SUBFLOW_WHISPER_PYTHON | 显式选择识别解释器，前者非空时优先；无效路径会报错 |
| SUBFLOW_GPTSOVITS_PYTHON | 显式选择配音解释器，适用于自行管理的环境 |

安装日志位于 `SUBFLOW_RUNTIME_DIR` 下的 `install-*.log`。默认 Windows 依赖在 `%APPDATA%/SubFlow/managed`，GPT 模型在 `%LOCALAPPDATA%/SubFlow/GPT-SoVITS`；Mac 依赖在 `~/.config/subflow/managed`，GPT 模型在 `~/.local/share/subflow/GPT-SoVITS`。下载失败可重试，已完成的缓存会保留。

## 构建客户端

构建在对应操作系统与目标架构上执行。先按源码步骤准备主环境与 FFmpeg，再安装打包依赖：

```bash
python -m pip install -e ".[gui,dev,packaging]"
```

```powershell
# Windows 完整包：收集三种配音模式和四套运行环境
./scripts/build-windows.ps1
```

当前完整包构建会准备并收集 Qwen 标准/设计音色、Qwen 原声克隆、GPT-SoVITS 模型，以及 Qwen、GPT-SoVITS、Whisper、WhisperX 四套运行环境。识别模型按需下载；网络翻译仍需服务连接。`-SourceOnly` 仅用于不内置环境和模型的 Windows 开发包，不能作为离线完整包发布。

```bash
# macOS 原生完整包（构建机需 Python 3.11+、brew install ffmpeg-full）
bash scripts/build-macos.sh
```

Mac 构建脚本创建隔离的构建环境，要求构建机、Python 和目标架构一致，禁止通过 Rosetta 生成 arm64 包。Apple M 包使用支持 MPS/CPU 的环境，Intel 包使用 CPU 环境；WhisperX 的 CTranslate2 在 Mac 使用 CPU。

`release-clients.yml` 由手动运行或推送 `v*` 标签触发，检查 Windows x64、macOS arm64/x64 客户端及 Docker。普通推送 main 不触发这个发布流程。成功的标签发布上传完整包的 `.7z.*` 分卷，须下载同一平台全部分卷后解压。完整包携带分发所需模型，但不能携带用户配置、API Key 或 Cookie。

构建成功与托管虚拟机上的组件检查不代表真实 Apple GPU 验收通过。请按 [Mac 实机验收文档](mac-self-test.md) 在 M1 等真实设备运行内置环境检查、实际视频识别及三种配音模式，并保留设备信息和报告。

## 开发与验收

源码检查及 PR 流程见 [贡献指南](../CONTRIBUTING.md)。当前发布结果见 [1.3.60 验收](release-1.3.60.md)，真实 Apple GPU 检查按 [M1 清单](mac-self-test.md) 执行。仅文档更新不会改变既有客户端包或版本标签。
