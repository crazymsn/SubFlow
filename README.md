# SubFlow 语幕

**新一代 AI 视频语音识别、自动翻译、字幕生成工具**

深度云创科技出品。本地识别语音，云端翻译成片。拖入视频或粘贴 YouTube / Bilibili 链接，即可得到双语字幕、烧录成片，以及可选配音。

当前版本 **1.2.5**。[GitHub Releases](https://github.com/crazymsn/SubFlow/releases/latest) · [Docker Hub](https://hub.docker.com/r/crazymsn/subflow) · [API 分发站](https://api.meding.site)

![SubFlow 语幕桌面客户端](docs/images/desktop-light.png)

## 能做什么

| 能力 | 说明 |
| --- | --- |
| 语音识别 | 本机 Whisper / WhisperX，不把原片上传到识别服务 |
| 链接入库 | YouTube、Bilibili 一键下载最高清；优先原声音轨，避免英文自动配音 |
| 自动翻译 | [meding](https://api.meding.site) OpenAI 兼容接口；获取模型时自动屏蔽 BAAI / 智源条目 |
| 中英字幕 | 中英 / 英中各 **1 行**，居中叠在安全区内；超长句缩放，不出画 |
| 简繁 | 目标语种为简体时，中文轨一律转为简体（Whisper 默认繁体也会转） |
| 烧录颜色 | 中英字幕颜色可自选；只改颜色会重渲 ASS 并重烧，不重跑识别 |
| 成片导出 | 烧录 MP4，同时写出 SRT / ASS |
| 配音 | OpenAI 云端多语种，或本机 GPT-SoVITS 克隆音色 |
| 三种入口 | Windows / macOS 桌面客户端、Python CLI、Docker 镜像 |

界面提供简体中文、繁体中文、English、日本語、Español、Русский、Français、Deutsch。默认界面为简体中文。

![更多选项与深色主题](docs/images/desktop-more.png)

## 字幕怎么对应

三个控件职责分开，互不覆盖：

| 控件 | 只管 |
| --- | --- |
| 源语种 | 识别 / Whisper 语言 |
| 目标语种 | 配音语种，以及中文轨的简体 / 繁体 |
| 字幕样式 | 画面上出现哪些语言、谁在上谁在下 |

| 字幕样式 | 目标语种 | 画面 |
| --- | --- | --- |
| 中英字幕 | 简体中文 | 简体 1 行在上，英文 1 行在下 |
| 中英字幕 | 繁體中文 | 繁体 1 行在上，英文 1 行在下 |
| 英中字幕 | 简体中文 | 英文 1 行在上，简体 1 行在下 |
| 单语「简体中文」 | — | 只烧简体 1 行 |
| 单语 English | — | 只烧英文 1 行 |

源语种和目标语种都选简体、字幕选中英：中文原声 + 简体/英文字幕，不会自动配成英文。

## 五分钟上手

1. 打开 [Releases](https://github.com/crazymsn/SubFlow/releases/latest)，下载 `SubFlow-Windows-1.2.5.zip` 或 `SubFlow-macOS-1.2.5.zip`。
2. Windows：**整夹解压**，进入 `SubFlow` 目录，双击 `SubFlow.exe`。不要只拷贝 exe。
3. macOS：解压后把 `SubFlow.app` 拖到「应用程序」；若提示未验证开发者，按住 Control 点击后选择打开。
4. 到 [API 分发站](https://api.meding.site) 领取令牌，在客户端保存，再点「获取模型」。
5. 拖入视频，或粘贴链接后下载。
6. 选好源语言、目标语言、字幕样式，点击「开始处理」。

首次识别会按所选 Whisper 模型下载权重。详细步骤见 [桌面客户端](docs/desktop.md)。

## 从源码运行

```bash
# 建议 Python 3.11+
pip install -e ".[gui,dev]"
subflow doctor
subflow config set-api-key
subflow models
subflow gui
```

命令行一次跑完：

```bash
subflow run demo.mp4 -o demo-中英字幕.mp4 --model gpt-4o-mini
subflow run --url "https://www.bilibili.com/video/BVxxxx" -o out.mp4
subflow run demo.mp4 -o out.mp4 --zh-color "#FFD400" --en-color "#F2F2F2"
```

兼容旧命令 `bilingual-sub`。

## Docker

官方镜像：[crazymsn/subflow](https://hub.docker.com/r/crazymsn/subflow)

```bash
cp .env.example .env
# 编辑 .env，填入 SUBFLOW_API_KEY（不要提交 .env）
docker compose pull
docker compose run --rm subflow doctor
docker compose run --rm subflow models
docker compose run --rm subflow run /data/demo.mp4 -o /data/demo-中英字幕.mp4
```

也可以直接拉镜像：

```bash
docker pull crazymsn/subflow:latest
docker run --rm -v "%cd%/data:/data" --env-file .env crazymsn/subflow:latest run /data/demo.mp4 -o /data/out.mp4
```

本机改源码后再打镜像：`docker compose build`。输入输出都在 `./data`。

## 流水线

```
视频 / 链接 → 抽音 → 静音切句 → Whisper / WhisperX
    → 整理字幕 → 术语 → 翻译（可选润色）→ 简繁转换
    → ASS / SRT（中英各 1 行）→ 烧录 MP4 → 可选配音
```

暂停、继续、停止可在桌面客户端操作。同片只换输出路径或只改字幕颜色时，不会重跑识别。

## 文档

| 文档 | 内容 |
| --- | --- |
| [桌面客户端](docs/desktop.md) | 安装、启动、字幕颜色、界面字段 |
| [安装](docs/install.md) | Docker Hub / Python / 从源码打包 |
| [API 令牌](docs/api-key.md) | 本机存储、轮换、多用户隔离 |
| [故障排除](docs/troubleshooting.md) | 识别、翻译、烧录、下载、客户端 |
| [架构](docs/architecture.md) | 模块边界与 JobConfig |
| [meding 契约](docs/api-meding.md) | 翻译 API 的固定地址与错误码 |
| [贡献](CONTRIBUTING.md) | 分支、测试与约束 |

## 系统要求

- Windows 10/11 x64 或 macOS 12+（Apple Silicon）客户端，或 Python 3.11+ / Docker
- FFmpeg 6+（官方 Windows 包已内置 `ffmpeg.exe` / `ffprobe.exe`）
- 识别建议 8 GB 以上内存；`medium` / `large` 更吃内存
- 可选 NVIDIA GPU（`cuda` 额外依赖，不打进官方客户端）
- 用户自备 meding API 令牌

若客户端提示缺少 Qt / VCRUNTIME DLL，安装 [Microsoft Visual C++ 2015–2022 Redistributable (x64)](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。

## 安全

- API 令牌只写本机凭据库，工具不上传、不汇聚、不共享
- 仓库与发布包**不含** API Key、Cookie、`.env`
- 日志自动脱敏，异常栈不含 Authorization
- 识别在本机完成；翻译请求只发字幕文本，不发原片
- Docker 镜像不含令牌；用 `.env` 注入

## License

MIT — 深度云创科技。字幕字体许可见 [LICENSE-fonts.txt](LICENSE-fonts.txt)。
