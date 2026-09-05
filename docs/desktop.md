# 桌面客户端 — SubFlow 语幕

当前发布包：[`SubFlow-Windows-1.2.2.zip`](https://github.com/crazymsn/SubFlow/releases/latest) · [`SubFlow-macOS-1.2.2.zip`](https://github.com/crazymsn/SubFlow/releases/latest)

窗口标题为 **深度云创科技**，界面品牌为 **SubFlow 语幕**。

## 安装与启动

1. 从 GitHub Releases 下载 zip，整夹解压。
2. 目录里应同时有 `SubFlow.exe`、`_internal\`、`ffmpeg.exe`、`ffprobe.exe`。
3. **在该文件夹内**双击 `SubFlow.exe`。不要把 exe 单独拷到桌面。

客户端是 PyInstaller onedir 包，exe 只是入口。只拷 exe 会找不到 Qt 与运行库。

macOS 发布包是 GitHub Actions 按同一套源码打出的 `SubFlow.app`（Apple Silicon）。解压 zip 后拖到「应用程序」。首次打开若被拦截，按住 Control 点击图标再选打开。

本机从源码构建：

```bash
bash scripts/build-macos.sh
# 产物：dist/SubFlow.app
```

```powershell
.\scripts\build-windows.ps1
# 产物：dist\SubFlow\SubFlow.exe
```

`dist/` 只在本机生成，不会提交到 Git。官方 Win / Mac 包由 `.github/workflows/release-clients.yml` 在打 `v*` 标签时上传到 Releases。

## 第一次使用

1. 打开 [https://api.meding.site](https://api.meding.site) 领取 API 令牌。令牌只保存在本机，不要写进仓库。
2. 在「API 令牌」粘贴后点「保存令牌」，再点「获取模型」，从列表选翻译模型（BAAI / 智源条目不会出现）。
3. 左侧拖入 MP4 / MKV / MOV / WEBM，或右侧粘贴 YouTube / Bilibili 链接后点「下载」。
4. 确认源语言、目标语言、字幕样式、识别引擎、识别模型。
5. 需要烧录成片时勾选「烧录到视频」。
6. 需要改字幕颜色时，打开「更多选项」，点中文 / 英文字幕色块。
7. 填好输出路径，点「开始处理」。

进度以整数百分比显示。处理日志在窗口底部。

## 三个语种控件

| 控件 | 只管 |
| --- | --- |
| 源语种 | 识别用的语言；`简体中文` / `繁體中文` 都走 Whisper 的 `zh` |
| 目标语种 | 配音语种；中英画面里的中文轨跟它走简体或繁体 |
| 字幕样式 | 画面布局：中英、英中、或单语 |

默认：源语种简体、目标语种简体、字幕样式中英。此时成片是 **中文原声 + 简体 1 行 + 英文 1 行**。

Whisper 中文常输出繁体。目标为简体时，烧录前会把中文轨转成简体。

下载链接时优先原声音轨。中文片不应下成英文自动配音；英语原声片仍下英语原声。

## 自定义字幕烧录颜色

在「更多选项」里有两个色块：

| 控件 | 默认 | 作用 |
| --- | --- | --- |
| 中文字幕颜色 | `#FFFFFF` | 写入 ASS 的中文轨并烧进成片 |
| 英文字幕颜色 | `#F2F2F2` | 写入 ASS 的英文轨并烧进成片 |

点击色块打开系统选色器。颜色保存在本机配置目录，下次启动沿用。

- 只改颜色、不改视频：重渲 ASS 并重烧，**不重跑识别 / 翻译**
- 命令行等价：`--zh-color "#FFD400" --en-color "#E8E8E8"`

## 主界面字段

| 区域 | 作用 |
| --- | --- |
| 上传视频 | 拖放或点击选择本地文件 |
| 视频链接 | 远程地址入库，默认最高清 + 原声音轨 |
| 源语言 / 目标语言 | 识别语言与配音 / 简繁 |
| 字幕样式 | 中英、英中或单语 |
| 识别引擎 | Whisper（默认）或 WhisperX（未就绪时自动回退） |
| 识别模型 | `tiny` … `large` |
| 烧录到视频 | 把字幕压进 MP4；关闭则只出 SRT / ASS |
| 输出路径 | 成品文件或文件夹；同片只改路径会拷贝已有成品 |

「更多选项」在甲板内部展开，不会盖住开始栏：

| 选项 | 作用 |
| --- | --- |
| 字幕颜色 | 勾选后出现中英字幕色块 |
| 配音 | OpenAI（走当前令牌）或 GPT-SoVITS（填本地服务地址） |
| 电影级润色 | 翻译后走 reflect / adapt |

术语表不在桌面端暴露，命令行仍可用 `--glossary` / `--glossary-generate`。

开始栏提供开始、暂停、继续、停止。

## 主题与语言

右上角可切换浅色 / 深色，以及八种界面语言。默认深色、简体中文。

## 本机构件

- API 令牌：Windows 凭据管理器，失败时写入 `%APPDATA%\SubFlow\`
- 下载 Cookie：读 exe 同级、项目根（打包版会向上找）、`%APPDATA%\SubFlow\Cookies` 的 `youtube-cookies.txt` / `bilibili-cookies.txt`。YouTube 必须含 SID 登录态。仓库只收 YouTube / B 站站点 Cookie，不含 API 令牌
- 字幕颜色：`%APPDATA%\SubFlow\`（macOS / Linux 为用户配置目录）
- Whisper 权重：本机缓存
- 官方客户端**不内置** PyTorch / WhisperX / GPT-SoVITS 权重

## 不要做

- 不要只复制 `SubFlow.exe`
- 不要把输出路径写成原片同一文件
- 不要在没保存令牌、没选模型时点开始
- 不要提交 `.env`、Cookie、凭据文件
- 不要复用已经下错过音轨的旧 `source.mp4`，应重新下载
