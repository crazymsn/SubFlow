# 客户端环境与设备支持

适用于 **1.3.60** 完整包。环境与真实设备验收步骤见 [Mac 实机手册](mac-self-test.md)。

| 平台 | 内置推理环境 | 默认设备 | 本轮验证范围 |
| --- | --- | --- | --- |
| Windows x64，NVIDIA GPU | Python 3.11、Whisper、WhisperX、Qwen3-TTS、GPT-SoVITS、CUDA 版 PyTorch | 可用 CUDA GPU 优先 | 本地 RTX 3060 Laptop |
| Windows x64，无受支持的 GPU | 同一 Windows 包；CUDA 版 PyTorch 包含 CPU 实现 | CPU | 隐藏 CUDA 后执行 CPU 验证，未使用另一台无显卡电脑 |
| Apple M 系列 | 原生 arm64 Python、上述识别和配音环境、MPS 版 PyTorch | Whisper、Qwen3-TTS、GPT-SoVITS 优先 MPS | 已配置构建与检测，尚待 M1 MacBook Air 实机验收 |
| Intel Mac | 原生 x64 Python、上述识别和配音环境 | CPU | 已配置构建，尚未进行本轮实机验收 |

WhisperX 使用 CTranslate2，不支持 Apple MPS，在 Mac 上运行于 CPU。使用 Apple GPU 识别时请选择 Whisper。Windows 加速后端为 NVIDIA CUDA；AMD / Intel 显卡按 CPU 路径处理。显卡驱动属于操作系统环境，不随客户端替换。

完整包包含 FFmpeg、ffprobe，以及 Qwen 标准音色、Qwen 原声克隆、GPT-SoVITS 的环境和模型。用户无需另外安装 Python、pip 或 CUDA Toolkit。必须整体解压并保留 `offline` 和 `_internal`，不能只复制 EXE。

**识别环境与识别模型不同。** Whisper / WhisperX 的 Python 依赖已纳入完整包构建；所选识别模型和 WhisperX 各语言对齐模型按需下载并缓存，没有预装全部型号的权重。云端翻译和视频链接下载仍需联网。显式构建的精简包 保留首次联网安装行为。

## 界面与翻译恢复

1.3.56 恢复左侧“SubFlow 语幕”品牌与窗口标题，“深度云创科技”独立放在顶栏中央，可点击打开 [导航站](https://nav.meding.site)，采用一致的标题字体。任务开始前保留任务标题、等待状态、0% 和进度条，仅在下方日志框内显示硬件检测结果和显卡 / Apple M 芯片型号；开始后日志框切换为正常任务日志。该提示只描述硬件，不代表本次推理实际使用的设备。

“继续”有两种用途：暂停时恢复当前任务；翻译失败或结果缺译时，在工作线程退出后重试原任务的翻译。重试使用原工作目录、识别结果、断句结果及成功的翻译缓存，按原设置继续生成字幕与配音。接口令牌有误时可修正令牌再继续。

恢复会验证原视频和中间文件，文件修改、丢失或损坏时拒绝复用。按钮恢复针对当前客户端会话；关闭客户端后的任务恢复仍使用已有命令行恢复入口。

## WhisperX 修复

旧客户端只给依赖导入 12 秒；本机冷启动实际约 17 秒，健康环境因此被误判。新检查允许最多 90 秒并支持取消，成功确认的解释器由本次识别复用。缺少 WhisperX 时显示回退到 Whisper 的提示。

同时修复视频任务将配音引擎写死为 GPT-SoVITS 的问题。选择 SubFlow 设计音色时保留 Qwen 引擎和所选音色。识别引擎与配音音色是独立设置。
