# 安装 — SubFlow 语幕

三条路径：发布包、Python 源码、Docker。日常使用优先 [桌面客户端](desktop.md)。

## 1. Windows 发布包

从 [Releases](https://github.com/crazymsn/SubFlow/releases/latest) 下载 `SubFlow-Windows-1.2.0.zip`，整夹解压后运行 `SubFlow\SubFlow.exe`。macOS 下载 `SubFlow-macOS-1.2.0.zip`，把 `SubFlow.app` 拖到「应用程序」。

包内已带 FFmpeg。若启动报 Qt / VCRUNTIME 缺失，安装 [VC++ 2015–2022 x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。

## 1b. macOS 发布包

从 Releases 下载 `SubFlow-macOS-1.2.0.zip`，解压后把 `SubFlow.app` 拖到「应用程序」。该包由 GitHub Actions 用 `scripts/build-macos.sh` 从同一仓库源码构建。若 Gatekeeper 拦截，按住 Control 点击后选择打开。

## 2. Python

```bash
python -m pip install -e ".[gui,dev]"
subflow doctor
subflow config set-api-key
subflow models
subflow gui
```

本地识别（本机已有 CUDA 时）：

```bash
python -m pip install -e ".[cuda,gui,dev]"
```

`[cuda]` 会拉取 `openai-whisper` 与 `torch`，体积大，官方 Windows 客户端不会打进包里。

常用命令：

```bash
subflow run demo.mp4 -o demo-中英字幕.mp4
subflow run --url "https://www.youtube.com/watch?v=xxxx" -o out.mp4
subflow run demo.mp4 --no-burn --srt demo.srt
subflow run demo.mp4 --refine --glossary-generate
subflow run demo.mp4 --asr-backend whisperx --whisper-model medium
subflow run demo.mp4 --dub --tts-provider openai --tts-voice alloy
```

兼容旧入口 `bilingual-sub`。

## 3. Docker Compose

```bash
cp .env.example .env
# SUBFLOW_API_KEY=你的key
docker compose build
docker compose run --rm subflow doctor
docker compose run --rm subflow models
docker compose run --rm subflow run /data/in.mp4 -o /data/out.mp4 --model <模型id>
```

输入输出都在 `./data`。Whisper 权重缓存在 named volume `whisper-cache`。

## 从源码打包客户端

```powershell
# Windows
.\scripts\build-windows.ps1
# 产物：dist\SubFlow\SubFlow.exe
```

```bash
# macOS
bash scripts/build-macos.sh
# 产物：dist/SubFlow.app
```

GitHub Actions 工作流 `.github/workflows/release-clients.yml` 在推送 `main` 或 `v*` 标签时打 Win / Mac 包，并上传 artifact。正式对外的 zip 挂在 Release。

## 离线

无网时不能拉翻译模型、不能调用翻译接口；可对已经完成翻译的作业 `--resume-from render` 继续烧录。识别权重若已缓存在本机，断网仍可转写。
