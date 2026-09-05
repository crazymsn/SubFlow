# 安装 SubFlow 1.3.2

## Windows / macOS 客户端

从 [Releases](https://github.com/crazymsn/SubFlow/releases) 下载已发布版本；main 分支的最新构建位于 [Actions](https://github.com/crazymsn/SubFlow/actions/workflows/release-clients.yml) 的 Artifacts。

- Windows x64：`SubFlow-Windows-x64.zip`，整夹解压并运行 `SubFlow/SubFlow.exe`。
- Apple Silicon：`SubFlow-macOS-arm64.zip`。
- Intel Mac：`SubFlow-macOS-x64.zip`。

Mac 解压后将 SubFlow.app 放入应用程序目录。当前构建没有 Apple 开发者公证，首次可能需要在系统安全设置允许打开。支持范围以构建所用 macOS 为准（Apple Silicon 14+、Intel 15+）。Windows 建议 Windows 10/11 x64。

客户端内置 FFmpeg 和 uv 安装器。首次启动自动准备用户私有的 Python 3.11、匹配设备的推理依赖及 GPT-SoVITS 模型，首次识别下载 Whisper 权重。无需用户预装 Python、CUDA、Git 或编译器；首次需要联网。请预留约 15–20 GB 空间（下载缓存和模型各占空间）。断网前应完成所需模型准备；翻译接口仍需网络。

无独立显卡也能运行。CPU 建议先用 tiny/base/small 和短片确认速度，较大模型与长视频可能耗时较长。GPU 为可选项；默认环境不会安装 CUDA 驱动。

## Apple M 系列 GPU

下载原生 `SubFlow-macOS-arm64.zip`，不要使用 Intel 包或 Rosetta 启动。客户端会自动安装原生 arm64 Python 和带 MPS 的 PyTorch / torchaudio，默认让 Whisper 识别与 GPT-SoVITS 配音使用 Apple GPU，无需安装 CUDA。MPS 使用 float32；频谱预处理中的不兼容运算在 CPU 完成，神经网络仍在 GPU 执行。

首次安装及旧版缓存升级自动完成。GPU 不可用时回退 CPU；Whisper 或非流式配音遇到 GPU 运算失败时会记录原因并重试 CPU。日志中的 `device=mps` 及本地配音 API `/subflow/runtime` 可查看实际设备，避免把回退 CPU 当成 GPU 验收。

WhisperX / CTranslate2 不支持 MPS，选择它时识别会使用 CPU；需要 Apple GPU 请使用默认 Whisper 引擎。Mac 上的 Linux Docker 容器不提供原生 MPS，本项目 Compose 保持 CPU 模式。Apple GPU 加速请使用原生客户端。

源码用户可运行 `subflow run in.mp4 --device mps`。依赖及 GPU 运算检查：

```bash
python scripts/check-apple-gpu.py --require-gpu
```

脚本检查两套环境的 MPS 编译支持、实际 GPU 可用性、Whisper 编解码和配音频谱路径，结果写入 `apple-gpu-report.json`。无 GPU 的 CI 虚拟机只验证依赖，不计为 GPU 实机通过。该检查也不替代实际视频的完整性能验收。

## Docker Compose

安装 Docker 和 Compose 后，在仓库根目录执行：

```bash
cp .env.example .env
# 需要翻译时在 .env 设置 SUBFLOW_API_KEY
mkdir -p data
docker compose build
docker compose run --rm subflow doctor
docker compose run --rm subflow run /data/in.mp4 -o /data/out.mp4
```

Compose 构建当前源码的 CPU 镜像，镜像内已安装 FFmpeg、识别及配音依赖。输入输出放入 `./data`。首次配音自动下载模型；Whisper、GPT-SoVITS、语言数据和下载缓存分别持久化在命名卷。不要执行 `docker compose down -v`，除非确实需要删除这些缓存。CLI 任务结束后容器退出是正常行为；Docker 入口不是桌面 GUI。

可在 `.env` 设置 `HF_ENDPOINT` 指向可访问且可信的兼容镜像。不要将 API Key、Cookie 或 `.env` 提交到 GitHub。默认验收平台为 Linux x86_64 CPU；ARM Linux 依赖可用性另行验证。

## 源码运行

源码开发需要 Python 3.11+ 和 PATH 中的 FFmpeg：

```bash
python -m pip install -e ".[gui,dev]"
subflow gui
# 可提前准备环境
python scripts/prepare-runtime.py asr
python scripts/prepare-runtime.py gptsovits
```

主程序、Whisper、GPT-SoVITS、可选 WhisperX 使用隔离环境，避免依赖互相覆盖。WhisperX 不可用时可回退标准 Whisper。

## 自动安装设置

| 环境变量 | 用途 |
| --- | --- |
| SUBFLOW_AUTO_INSTALL=0 | 禁止自动安装；须提前准备完整运行环境 |
| SUBFLOW_RUNTIME_DIR | Python、依赖和安装日志缓存目录 |
| SUBFLOW_GPTSOVITS_HOME | GPT-SoVITS 源码、模型及语言数据目录 |
| SUBFLOW_TORCH_BACKEND | 原生 Apple Silicon 默认 mps，其余默认 cpu；可设 cpu 禁用自动 GPU，Win/Linux x64 可选 cuda |
| SUBFLOW_GPTSOVITS_DEVICE | 可设 mps / cpu / cuda，默认跟随平台的推理后端 |
| SUBFLOW_SOVITS_AUTOSTART=0 | 禁用桌面启动时配音预热；需要配音时仍会按需准备 |

安装日志位于 `SUBFLOW_RUNTIME_DIR` 下的 `install-*.log`。默认 Windows 依赖在 `%APPDATA%/SubFlow/managed`，GPT 模型在 `%LOCALAPPDATA%/SubFlow/GPT-SoVITS`；Mac 依赖在 `~/.config/subflow/managed`，GPT 模型在 `~/.local/share/subflow/GPT-SoVITS`。下载失败可重试，已完成的缓存会保留。

## 构建客户端

```powershell
# Windows 社区包：用户首次自动安装
./scripts/build-windows.ps1 -SourceOnly
# 全离线 GPT 配音包：先用 setup/install 脚本准备完整依赖与模型
./scripts/build-windows.ps1
```

```bash
# macOS 社区包（构建机需 brew install ffmpeg-full）
bash scripts/build-macos.sh
```

推送 main 自动运行 Windows x64、macOS arm64/x64 的测试、对应 CPU/MPS 环境安装、打包与真实启动检查，以及 Docker 构建检查。Apple GPU 探测报告单独记录依赖是否支持 MPS、GPU 是否可分配内存以及计算检查结果；托管虚拟机不能使用 GPU 时不会标记为 GPU 验收通过。真实 Mac 的严格验收应运行 `python scripts/check-apple-gpu.py --require-gpu`，再进行实际视频识别和配音。推送 v* 标签且所有检查成功后自动上传 ZIP 到 Releases。社区包不携带用户配置、API Key、Cookie 或预下载的模型权重。
