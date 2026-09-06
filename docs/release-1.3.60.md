# SubFlow 语幕 1.3.60

## 下载完整客户端

提供 Windows x64、macOS arm64（Apple M 系列）和 macOS x64（Intel）三种完整包。下载所需平台的**全部** `SubFlow-平台.7z.*` 分卷，放入同一文件夹，使用支持 7z 分卷的工具从 `.001` 解压。`SHA256SUMS` 提供逐卷校验值。

- Windows 10/11 x64：运行 `SubFlow/SubFlow.exe`，保留完整目录。
- Apple M，macOS 14+：使用 arm64 包；Intel Mac，macOS 15+：使用 x64 包。将 `SubFlow.app` 放入应用程序目录。Mac 包未做 Apple 开发者公证。
- 全部客户端内置 Qwen 标准音色、Qwen 原声克隆、GPT-SoVITS v2 的模型与依赖，以及 Whisper / WhisperX 运行环境。配音模型无需首次下载；识别及对齐模型按需下载。

## 本次更新

- 默认 Qwen3-TTS 配音，23 个男声 / 女声音色，覆盖八个目标语种；试听内容和语种跟随目标设置。
- Windows 优先可用 NVIDIA GPU，Apple M 原生引擎优先 MPS；无可用 GPU 时使用 CPU。Intel Mac、Mac WhisperX 和 Docker 使用 CPU。
- 中文源片输出简体 / 繁体目标保留原声。字幕每种语言最多一行，固定字号与位置，长句保留全文分页。
- 合成后依据实际时长规划时间，借用停顿、限制起点偏移；不再因超过 1.25 倍加速直接终止配音。密集内容仍可能较快。
- 移除翻译硬截断，润色失败时保留译文。翻译失败可在任务栏或错误弹窗继续，允许更换翻译模型 / 令牌；重试失败后入口仍保留，缓存有效时无需重新识别。WhisperX 显存不足先降低批次再考虑 CPU。
- 顶栏保留 SubFlow 语幕，居中公司超链接，无橙色框；统一控件尺寸、编号与标题对齐。语音识别与翻译始终展开。
- 配音显示步骤、句数和耗时；准备阶段不再固定提示首次下载。更新错误弹窗、完整包说明和当前界面截图。
- 固定 Qwen 音频编译依赖的兼容版本，避免 Intel Mac 冷安装时意外编译 LLVM。

## Docker

`crazymsn/subflow:latest` 和 `crazymsn/subflow:1.3.60` 面向 Linux amd64 / arm64 CPU。镜像内置四套推理依赖；模型按需下载并缓存到 Compose 命名卷。Docker 是命令行工具，不提供桌面或 Web 界面。使用仓库的 `docker-compose.yml`，执行 `docker compose pull` 后运行任务。

## 验证范围

三平台回归测试、客户端自检、三种内置配音模式的离线实际合成和分卷校验均已通过。Docker 两架构完成 CLI、依赖、音频和目录读写检查，多架构标签及代码修订已核对。正式发布的 16 个分卷 SHA-256 全部与校验文件一致，详见[发布验收记录](https://github.com/crazymsn/SubFlow/blob/main/docs/qa-1.3.60.md)。

本机此前已验证 RTX 3060 Laptop CUDA 识别与配音，记录见 [Windows GPU 验收](https://github.com/crazymsn/SubFlow/blob/main/docs/qa-1.3.59.md)；本次发布包通过云端启动和 CPU 离线合成检查。完整视频的语音听感、不同设备性能与 Apple M1 GPU 实机验收仍需实际检查，不能用 CI CPU 通过代替。Mac 用户按 [Mac 实机验收手册](https://github.com/crazymsn/SubFlow/blob/main/docs/mac-self-test.md)执行。

GitHub 现仅保留 `v1.3.60` Release 与版本标签，Git 提交历史保留。API 令牌不进入代码、客户端或 Docker 镜像。
