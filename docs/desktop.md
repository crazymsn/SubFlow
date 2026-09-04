# 桌面客户端 — SubFlow 语幕

当前发布包：[`SubFlow-Windows-1.1.0.zip`](https://github.com/crazymsn/SubFlow/releases/latest)

窗口标题为 **深度云创科技**，界面品牌为 **SubFlow 语幕**。

## 安装与启动

1. 从 GitHub Releases 下载 zip，整夹解压。
2. 目录里应同时有 `SubFlow.exe`、`_internal\`、`ffmpeg.exe`、`ffprobe.exe`。
3. **在该文件夹内**双击 `SubFlow.exe`。不要把 exe 单独拷到桌面。

客户端是 PyInstaller onedir 包，exe 只是入口。只拷 exe 会找不到 Qt 与运行库。

macOS 可从源码构建：

```bash
bash scripts/build-macos.sh
# 产物：dist/SubFlow.app
```

Windows 从源码重打：

```powershell
.\scripts\build-windows.ps1
# 产物：dist\SubFlow\SubFlow.exe
```

## 第一次使用

1. 打开 [https://api.meding.site](https://api.meding.site) 领取 API 令牌。
2. 在「API 令牌」粘贴后点「保存令牌」，再点「获取模型」，从列表选翻译模型。
3. 左侧拖入 MP4 / MKV / MOV / WEBM，或右侧粘贴 YouTube / Bilibili 链接后点「下载」。
4. 确认源语言、目标语言、字幕模式、识别引擎、识别模型。
5. 需要烧录成片时勾选「烧录到视频」。
6. 填好输出路径，点「开始处理」。

进度以 `0%`、`7%`、`100%` 这种整数百分比显示。处理日志在窗口底部。

## 主界面字段

| 区域 | 作用 |
| --- | --- |
| 上传视频 | 拖放或点击选择本地文件 |
| 视频链接 | 远程地址入库，下载完成后进入同一条流水线 |
| 源语言 / 目标语言 | 识别语言与翻译方向 |
| 字幕模式 | 中英双语，或单行 Netflix |
| 识别引擎 | Whisper（默认）或 WhisperX（词级更准；未就绪时自动回退） |
| 识别模型 | `tiny` … `large`，越大越准、越慢、越占内存 |
| 烧录到视频 | 把字幕压进 MP4；关闭则只出 SRT / ASS |
| 输出路径 | 成品文件或文件夹；同片只改路径会拷贝已有成品 |

「更多选项」在甲板内部展开，不会盖住开始栏：

| 选项 | 作用 |
| --- | --- |
| 电影级润色 | 翻译后走 reflect / adapt，措辞更稳，更耗配额 |
| 从视频生成术语 | 先抽术语再翻译，专有名词更稳 |
| 术语 | 本机 JSON / YAML 术语表（可选） |
| 配音 | OpenAI（走当前令牌）或 GPT-SoVITS（填本地服务地址） |

开始栏提供开始、暂停、继续、停止。隐藏的「打开文件夹」仍保留给自动化测试，日常界面不占用主按钮位。

## 主题与语言

右上角可切换浅色 / 深色，以及七种界面语言。默认浅色、简体中文。字体统一为微软雅黑 UI 优先，避免控件各用一套西文字体。

## 本机构件

- API 令牌：Windows 凭据管理器，失败时写入 `%APPDATA%\SubFlow\`
- Whisper 权重：本机缓存，按模型名下载
- WhisperX：需要独立 runtime；打包版可按需准备，失败则回退 Whisper
- 官方 Windows 包**不内置** PyTorch / WhisperX / GPT-SoVITS 权重

## 不要做

- 不要只复制 `SubFlow.exe`
- 不要把输出路径写成原片同一文件
- 不要在没保存令牌、没选模型时点开始
- 不要期望无网完成翻译或首次拉模型
