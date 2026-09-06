# 桌面客户端

[文档索引](README.md) · SubFlow 语幕 1.3.60

## 下载与安装

从 [最新 Release](https://github.com/crazymsn/SubFlow/releases/latest) 下载同一平台全部 `.7z.*` 分卷和 `SHA256SUMS`。

| 平台 | 分卷前缀 | 启动方式 |
| --- | --- | --- |
| Windows 10/11 x64 | `SubFlow-Windows-x64.7z` | 从 `.001` 完整解压，运行 `SubFlow/SubFlow.exe` |
| Apple M，macOS 14+ | `SubFlow-macOS-arm64.7z` | 解压，将 `SubFlow.app` 放入「应用程序」 |
| Intel Mac，macOS 15+ | `SubFlow-macOS-x64.7z` | 解压，将 `SubFlow.app` 放入「应用程序」 |

所有分卷放在同一目录，使用支持 7z 分卷的工具从 `.001` 解压。缺卷会导致解压失败。Windows 可用 `Get-FileHash .\SubFlow-Windows-x64.7z.* -Algorithm SHA256` 逐卷对照摘要；Mac 可用 `shasum -a 256 SubFlow-macOS-arm64.7z.*`。

保留 Windows 的 `_internal`、`offline`、FFmpeg 和 EXE；不要将新旧版本混装。Apple M 使用原生 arm64 包，不通过 Rosetta 运行 Intel 包。Mac 包为本地签名，未做 Apple 开发者公证；确认下载来源后，在系统「隐私与安全性」按提示允许打开。

## 环境与设备

完整包内置三种配音模式的模型和四套 Python 环境，配音无需首次下载。首次准备仍包括本地文件校验和模型加载。识别模型、对齐模型按需下载，翻译与链接下载需联网。

Windows 优先 NVIDIA GPU，无可用 CUDA 时使用 CPU；Apple M 的 Whisper、Qwen 和 GPT-SoVITS 优先 MPS，Intel Mac 使用 CPU。Mac WhisperX 使用 CPU。显卡驱动由系统提供，不需额外安装 CUDA Toolkit。详见[环境覆盖](runtime-coverage.md)和[完整包指南](offline-voices.md)。

## 界面与任务

![1.3.60 深色工作区](images/workspace-dark.png)

1. **视频素材**：拖入本地视频，或粘贴视频链接下载。
2. **字幕与语言**：设置源语种、目标语种、字幕样式、烧录与颜色。每种语言最多一行，固定字号和位置；过长句子完整分页。
3. **配音与音色**：跨语种选择音色并试听。标准音色无需参考录音；克隆模式可选择清晰的人声，并填写与录音对应的逐字稿。试听语种随目标语种变化。
4. **语音识别与翻译**：始终展开，选择 Whisper / WhisperX、识别模型，保存自己的 API 令牌并获取翻译模型。
5. 指定新输出文件名，点击「开始处理」。任务区显示当前步骤、进度与日志；暂停、继续、停止和输出栏保持可见。

中文源片选择简体 / 繁体目标始终保留原声；中英 / 英中字幕仍需翻译英文行。中文单语字幕无需翻译令牌。默认 Qwen 提供 23 个官方 / 设计音色，来源与性别见[音色说明](voices.md)。

配音按完整语句生成，先测量时长，再借用停顿并适配时间。短语音保留原速；密集台词可能需要较明显加速，1.25 倍不再是导致任务失败的硬上限。参考录音应清晰、单人、少背景声；语音自然度也受模型、语言和文本影响。

## 继续失败的翻译

翻译失败或未完成时，保留当前视频、输出和工作目录，修正令牌、网络或翻译模型后点击「继续」。缓存校验通过时复用已有识别，从翻译阶段恢复；更换视频或影响上游处理的设置可能需要重新识别。不要删除作业文件，也不要让多个任务写同一输出。

## 配置与升级

字幕颜色、主题和语言保存到本机。API 令牌通过系统凭据库或用户私有配置保存，见[令牌指南](api-key.md)。站点 Cookie 可放在客户端附近或用户配置目录的 `Cookies/`，使用 Netscape 格式和本人登录态；示例文件不含登录凭据。

升级前退出客户端，将新包完整解压到独立目录。用户配置保存在用户目录；确认新版本能启动后再处理旧目录。问题处理见[故障排除](troubleshooting.md)，Apple M / Intel 实机检查见 [Mac 验收手册](mac-self-test.md)。
