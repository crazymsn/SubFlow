# SubFlow 语幕

**新一代 AI 视频语音识别、自动翻译、字幕生成工具**

深度云创科技出品。[Windows 客户端](https://github.com/crazymsn/SubFlow/releases/latest) · [API 分发站](https://api.meding.site) · [MIT License](LICENSE)

本地识别语音，云端翻译成片。拖入视频或粘贴 YouTube / Bilibili 链接，即可得到双语字幕、烧录成片，以及可选配音。

![SubFlow 语幕桌面客户端](docs/images/desktop-light.png)

## 能做什么

| 能力 | 说明 |
| --- | --- |
| 语音识别 | 本机 Whisper / WhisperX，不把原片上传到识别服务 |
| 链接入库 | YouTube、Bilibili 等地址一键下载后再跑流水线 |
| 自动翻译 | [meding](https://api.meding.site) OpenAI 兼容接口，保存令牌后拉取模型列表 |
| 字幕规范 | 中英双语或单行 Netflix 风格；可选电影级润色与术语表 |
| 成片导出 | 烧录 MP4，同时写出 SRT / ASS；输出路径可改而不必重跑 |
| 配音 | OpenAI 云端多语种，或本机 GPT-SoVITS 克隆音色 |
| 三种入口 | Windows 桌面客户端、Python CLI、Docker Compose |

界面提供简体中文、繁体中文、English、日本語、Español、Русский、Français。

![更多选项与深色主题](docs/images/desktop-more.png)

## 五分钟上手（Windows 客户端）

1. 打开 [Releases](https://github.com/crazymsn/SubFlow/releases/latest)，下载 `SubFlow-Windows-1.1.0.zip`。
2. **整夹解压**，进入 `SubFlow` 目录，双击 `SubFlow.exe`。不要只拷贝 exe。
3. 到 [API 分发站](https://api.meding.site) 领取令牌，在客户端保存，再点「获取模型」。
4. 拖入视频，或粘贴链接后下载。
5. 选好源语言、目标语言、识别引擎与翻译模型，点击「开始处理」。

首次识别会按所选 Whisper 模型下载权重，需要本机磁盘与网络。详细步骤见 [桌面客户端](docs/desktop.md)。

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
```

兼容旧命令 `bilingual-sub`。

## Docker Compose

适合服务器或批量处理。把视频放到 `./data`：

```bash
cp .env.example .env
# 编辑 .env，填入 SUBFLOW_API_KEY
docker compose build
docker compose run --rm subflow doctor
docker compose run --rm subflow models
docker compose run --rm subflow run /data/demo.mp4 -o /data/demo-中英字幕.mp4
```

## 流水线

```
视频 / 链接 → 抽音 → 静音切句 → Whisper / WhisperX
    → 整理字幕 → 术语 → 翻译（可选润色）
    → ASS / SRT → 烧录 MP4 → 可选配音
```

暂停、继续、停止可在桌面客户端操作；同片只换输出路径时会直接拷贝成品，不重跑识别。

## 文档

| 文档 | 内容 |
| --- | --- |
| [桌面客户端](docs/desktop.md) | 安装、启动、界面字段、常见误操作 |
| [安装](docs/install.md) | Docker / Python / 从源码打包 |
| [API 令牌](docs/api-key.md) | 本机存储、轮换、多用户隔离 |
| [故障排除](docs/troubleshooting.md) | 识别、翻译、烧录、客户端 |
| [架构](docs/architecture.md) | 模块边界与 JobConfig |
| [meding 契约](docs/api-meding.md) | 翻译 API 的固定地址与错误码 |
| [贡献](CONTRIBUTING.md) | 分支、测试与约束 |

## 系统要求

- Windows 10/11 x64 客户端，或 Python 3.11+ / Docker
- FFmpeg 6+（官方 Windows 包已内置 `ffmpeg.exe` / `ffprobe.exe`）
- 识别建议 8 GB 以上内存；`medium` / `large` 更吃内存
- 可选 NVIDIA GPU（`cuda` 额外依赖，不打进官方客户端）
- 用户自备 meding API 令牌

若客户端提示缺少 Qt / VCRUNTIME DLL，安装 [Microsoft Visual C++ 2015–2022 Redistributable (x64)](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。

## 安全

- API 令牌只写本机凭据库，工具不上传、不汇聚、不共享
- 日志自动脱敏，异常栈不含 Authorization
- 识别在本机完成；翻译请求只发字幕文本，不发原片

## License

MIT — 深度云创科技。字幕字体许可见 [LICENSE-fonts.txt](LICENSE-fonts.txt)。
