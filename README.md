# SubFlow

**深度云创科技**出品。输入中文视频 → 本地 Whisper 识别 → [meding.site](https://api.meding.site) 翻译 → 烧录双语 MP4 + 外挂 SRT/ASS。

填入 API Key 后自动拉取模型列表，可任选其一。

```
video.mp4 → extract → Whisper → cues → translate → ASS/SRT → burn → out.mp4
```

## 三种使用方式

### 1. Docker Compose（推荐服务器 / 开箱引擎）

```bash
cp .env.example .env
# 编辑 .env，填入 SUBFLOW_API_KEY
docker compose build
docker compose run --rm subflow models
docker compose run --rm subflow run /data/demo.mp4 -o /data/demo-中英字幕.mp4
```

把视频放到 `./data`。详见 [docs/install.md](docs/install.md)。

### 2. 桌面客户端（Windows / macOS）

```powershell
# Windows
.\scripts\build-windows.ps1
# 产物：dist\SubFlow\SubFlow.exe

# macOS
bash scripts/build-macos.sh
# 产物：dist/SubFlow.app
```

GitHub Actions 工作流 `.github/workflows/release-clients.yml` 可同时打 Win / Mac 包。

打开 **SubFlow**，保存 API 令牌 → 点击「获取模型」→ 从下拉列表选择 → 拖入视频 → 开始处理。

### 3. Python CLI

```bash
pip install -e ".[cuda,gui,dev]"
subflow config set-api-key    # 保存后打印模型列表
subflow models
subflow config set-model <id>
subflow gui
subflow run demo.mp4
```

兼容旧命令 `bilingual-sub`。

## 系统要求

- Python 3.11+ 或 Docker
- FFmpeg 6+（客户端构建脚本会尝试打进包内）
- 可选 NVIDIA GPU
- 用户自备 meding API Key（只存本机 / 容器环境变量）

## 文档

- [安装](docs/install.md)
- [API Key](docs/api-key.md)
- [故障排除](docs/troubleshooting.md)
- [架构](docs/architecture.md)

## License

MIT — 深度云创科技。字体见 [LICENSE-fonts.txt](LICENSE-fonts.txt)。
