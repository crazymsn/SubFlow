# SubFlow 语幕

本地语音识别、字幕翻译、视频烧录与可选音色克隆配音。支持 Windows、macOS 和 Docker，无独立显卡也可运行。

**当前发布：1.3.46** · [下载客户端](https://github.com/crazymsn/SubFlow/releases/tag/v1.3.46) · [Docker Hub](https://hub.docker.com/r/crazymsn/subflow) · [使用文档](docs/README.md) · [更新记录](CHANGELOG.md)

![SubFlow 语幕桌面客户端](docs/images/desktop-light.png)

## 选择运行方式

| 设备 / 场景 | 下载或部署 | 推理设备 |
| --- | --- | --- |
| Windows 10/11 x64 | [Windows 客户端](https://github.com/crazymsn/SubFlow/releases/download/v1.3.46/SubFlow-Windows-x64.zip) | 默认 CPU |
| Apple M 系列，macOS 14+ | [Mac arm64 客户端](https://github.com/crazymsn/SubFlow/releases/download/v1.3.46/SubFlow-macOS-arm64.zip) | 默认尝试 Apple GPU（MPS），不可用时回退 CPU |
| Intel Mac，macOS 15+ | [Mac x64 客户端](https://github.com/crazymsn/SubFlow/releases/download/v1.3.46/SubFlow-macOS-x64.zip) | CPU |
| Linux / NAS / Docker Desktop | [Docker Compose 指南](docs/docker.md) | amd64 / arm64 CPU |
| 源码开发 | [安装与构建](docs/install.md) | CPU；可按设备配置 MPS / CUDA |

GitHub 客户端附带 FFmpeg、uv 安装器与适配后的 GPT-SoVITS 源码。首次使用会联网准备独立 Python 3.11、推理依赖和模型，无需预装 Python、Git、CUDA 或编译器。建议预留约 15–20 GB 磁盘空间、16 GB 内存；资源占用随模型和视频长度变化。首次下载完成后复用缓存，云端翻译仍需联网。

Apple GPU 仅用于原生 arm64 客户端。WhisperX 与 Mac 上的 Docker 使用 CPU。当前发布的构建和自动检查已通过，Apple GPU 完整实机验收仍待完成，见 [M1 测试清单](docs/mac-self-test.md) 和 [1.3.46 验收范围](docs/release-1.3.46.md)。

## 第一次处理视频

1. 下载对应架构的 ZIP 并完整解压。Windows 运行 `SubFlow/SubFlow.exe`，保留整个文件夹；Mac 将 `SubFlow.app` 放入「应用程序」。首次系统拦截的处理见 [桌面指南](docs/desktop.md)。
2. 联网启动并等待环境准备完成。无显卡或内存较少时，先选 Whisper `tiny` / `base`，用短片确认运行速度。
3. 拖入视频，或粘贴 YouTube / Bilibili 链接后下载。
4. 设置源语言、目标语言和字幕样式。需要翻译时，在客户端保存自己的 [meding API 令牌](docs/api-key.md)，获取并选择可用模型。
5. 指定新的输出路径，点击「开始处理」。可导出 SRT / ASS，或烧录成 MP4。

**中文源视频 → 简体中文或繁体中文目标：始终保留原声，不进行本次视频的合成配音。** 简繁转换只改变字幕文字。后台配音服务随客户端启动属于环境准备，不代表视频一定会配音。

| 想要的结果 | 目标语言 / 字幕样式 | 是否需要翻译令牌 | 声音 |
| --- | --- | --- | --- |
| 中文原片 + 简体字幕 | 简体中文 / 单语简体中文 | 否 | 中文原声 |
| 中文原片 + 繁体字幕 | 繁体中文 / 单语繁体中文 | 否 | 中文原声 |
| 中文原片 + 中英双语字幕 | 简体或繁体中文 / 中英或英中 | 是，英文行需要翻译 | 中文原声 |
| 中文原片 + 英文配音 | English / 需要的字幕样式，并开启配音 | 是 | GPT-SoVITS 合成英文音轨 |

字幕样式决定画面语言和顺序，源语言用于识别，目标语言用于配音及中文简繁选择。默认中英字幕仍需翻译英文行；“保留原声”不等于“不需要字幕翻译”。

## 主要功能

- **本地识别**：Whisper / 可选 WhisperX，语音识别无需把原片上传到翻译服务。
- **链接下载**：支持 YouTube、Bilibili，优先选择原声音轨；受登录、地区和站点限制的链接可能需要自己的 Cookie。
- **字幕处理**：翻译、可选润色、中文简繁、中英 / 英中 / 单语布局、字幕颜色和 ASS / SRT 导出。
- **视频导出**：烧录字幕，支持任务暂停、继续、停止；满足缓存校验时复用已有结果。
- **本地配音**：内置适配后的 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)，跨语种配音可使用自选参考音频。
- **桌面界面**：浅色 / 深色主题，简体中文、繁体中文、English、日本語、Español、Русский、Français、Deutsch。

![更多选项与深色主题](docs/images/desktop-more.png)

## Docker 快速开始

安装 Docker 与 Compose，将本仓库下载或克隆到本机，在仓库根目录执行：

```bash
cp .env.example .env
mkdir -p data
docker compose pull
docker compose run --rm subflow doctor
```

Windows PowerShell 用 `Copy-Item .env.example .env` 和 `New-Item -ItemType Directory -Force data` 代替前两行。已有 `.env` 时继续使用原文件。把中文视频放入 `data/input.mp4`，先运行无需翻译令牌的 CPU 示例：

```bash
docker compose run --rm subflow run /data/input.mp4 -o /data/output.mp4 --source-lang zh --target-lang zh --subtitle-mode single:zh --whisper-model base --device cpu
```

输出在宿主机 `data/`。需要双语翻译时先在 `.env` 配置 `SUBFLOW_API_KEY`，再查看模型并运行：

```bash
docker compose run --rm subflow models
docker compose run --rm subflow run /data/input.mp4 -o /data/output-bilingual.mp4 --whisper-model base
```

默认镜像为 `crazymsn/subflow:1.3.46`。任务完成后容器退出是正常行为，Docker 提供 CLI，不提供桌面或 Web 界面。模型和配置存入持久化卷；升级、目录映射、超时、源码构建见 [Docker 指南](docs/docker.md)。

## 源码快速开始

开发机需 Python 3.11+、Git 和支持字幕滤镜的 FFmpeg。先使用独立虚拟环境：

```bash
git clone https://github.com/crazymsn/SubFlow.git
cd SubFlow
python -m venv .venv
```

Windows PowerShell 执行 `.\.venv\Scripts\Activate.ps1`；macOS / Linux 执行 `source .venv/bin/activate`，然后：

```bash
python -m pip install -e ".[gui,dev]"
subflow gui
```

命令行中文单语示例：

```bash
subflow run input.mp4 -o output.mp4 --source-lang zh --target-lang zh --subtitle-mode single:zh --whisper-model base
```

自动环境配置、Apple MPS、可选 CUDA 及打包步骤见 [安装指南](docs/install.md)。旧入口 `bilingual-sub` 仍兼容。

## 文档与反馈

| 需要了解 | 文档 |
| --- | --- |
| 安装客户端、界面设置与配音规则 | [桌面客户端](docs/desktop.md) |
| Docker 部署、持久化与更新 | [Docker Compose](docs/docker.md) |
| 源码运行、依赖目录与客户端构建 | [安装指南](docs/install.md) |
| 令牌存储、删除和轮换 | [API 令牌](docs/api-key.md) |
| 下载失败、CPU / MPS、配音与导出问题 | [故障排除](docs/troubleshooting.md) |
| 发布检查结果与未完成的实机验证 | [1.3.46 验收记录](docs/release-1.3.46.md) |
| 架构、贡献与历史技术记录 | [文档索引](docs/README.md) · [贡献指南](CONTRIBUTING.md) |

反馈问题请提交 [GitHub Issue](https://github.com/crazymsn/SubFlow/issues)，提供版本、操作系统、芯片 / 内存、复现步骤和脱敏后的错误信息。不要提交 API 密钥、登录 Cookie、私有视频或完整凭据文件。

## 数据与许可

识别和默认内置配音在本机执行；翻译会通过 HTTPS 向 meding 发送字幕、提示词和所用术语，并携带令牌鉴权。密钥优先存入系统凭据库，不可用时回退本地受限权限的 JSON 文件，该文件不是加密保险库。详见 [API 与数据说明](docs/api-key.md)。

SubFlow 采用 [MIT License](LICENSE)。第三方组件和模型分别遵循各自许可，参见 [NOTICE](NOTICE)、[GPT-SoVITS 随附说明](third_party/GPT-SoVITS/README.md) 与 [字体许可](LICENSE-fonts.txt)。
