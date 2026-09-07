# SubFlow 1.3.61 · M1 修复与验收

日期：2026-09-07。直接修复用户源码 `<源码目录>`，并安装到 `/Applications/SubFlow.app`。这是 1.3.61 本地验收的历史记录；后续发布状态见 1.3.65 Mac 发布说明。

**结论：已修复本轮确认的问题，M1 核心识别、在线翻译、三种配音、字幕及视频导出实测通过。四卷交付包已完整重新解压，273 条内部链接、深度严格签名和脱离源码目录的应用自检全部通过。人工桌面点击因 Mac 锁屏未完成，不标为通过。**

## 实测环境

Apple M1、8 GB 内存、macOS 14.5 (23F79)，原生 arm64，无 Rosetta。随包 Python 3.11.15、PyTorch 2.5.1，构建使用 PySide6 6.11.2、PyInstaller 6.22.2；FFmpeg 9.0.1、uv 0.11.8、7-Zip 26.03。

证据目录：`~/Downloads/SubFlow-fix-QA-20260907`；旧版对照目录：`~/Downloads/SubFlow-M1-QA-20260906`。下文证据文件相对本轮目录。

## 修复内容

| 问题 | 影响与处理 |
| --- | --- |
| Mac 框架链接在打包时丢失 | 旧版解压后签名失效。7z 打包使用 `-snl` 保留链接，CI 对实际解压产物重新验签并自检。 |
| 7-Zip 默认忽略应用内部的父目录及间接链接 | 默认解压忽略 132 条；`-snld` 仍忽略 18 条间接链接。对已校验的包使用 `-snld20` 完整还原。新增链接检查器，在打包前和解压后禁止绝对、越界、悬空与循环链接。 |
| 完整包找不到 GPT-SoVITS | 冻结程序从离线清单定位模型，不再依赖构建机源码目录。 |
| 自检错误导致 QThread 销毁崩溃 | 先记录原始错误，再协作退出并等待线程，避免 abort 134 掩盖原因。 |
| Qwen MPS 分组注意力原生崩溃 | 在 MPS 使用 eager attention；CPU/CUDA 保持原路径。 |
| 旧 macOS 长音频卷积超过 65536 维度 | Qwen 和 GPT 的音频卷积使用完整感受野分块，转置卷积保留重叠与偏置，不截短解码上下文。 |
| Qwen 官方音色出现额外开头音节 | 模型与声码器保留 MPS，仅在当前官方音色请求内将随机抽样放到 CPU，保持温度和 top-k 分布；结束/异常时恢复原函数。三条真实台词复查完整准确。 |
| ONNX Runtime 退出阶段偶发崩溃 | 原生崩溃栈指向遥测上传线程。初始化前设置 `ORT_DISABLE_TELEMETRY=1`；修复后四套环境 CPU/MPS 检查均正常退出。 |
| 复用完整包携带旧推理源码 | 复用模型/解释器时刷新 GPT vendor 源码和摘要，避免改写原包硬链接。 |
| 系统代理与本地地址处理 | 翻译 SDK 读取 macOS 系统代理，保留显式环境设置与绕过规则；本地回环媒体请求直连。 |
| 中文源码目录和构建环境 | 构建启用 UTF-8，校验 Python 版本及架构，支持独立构建环境、离线包复用和产物目录。 |
| Mac 图标 | 使用用户提供的 Sub.png 原图，生成 16–1024 像素 ICNS，同步应用/Dock/窗口图标。 |

注意力与卷积限制参考 [PyTorch #149132](https://github.com/pytorch/pytorch/issues/149132)、[#134416](https://github.com/pytorch/pytorch/issues/134416)、[#152278](https://github.com/pytorch/pytorch/issues/152278)。遥测开关参考 [ONNX Runtime 官方说明](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md)。修复判定以本机复现和复测为依据。

Qwen 的状态接口现在分别报告模型与抽样设备：官方音色为 `device=mps`、`sampling_device=cpu`。克隆/设计音色和 CPU/CUDA 路径不受该抽样调整影响。贪心解码和另一种文本输入排列的试验未通过要求，未加入产品。

## 验收结果

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 全套自动测试 | 1,585 passed，14 skipped；667.05 秒；覆盖率显示 92% | `full-tests-final.log`、`full-tests-final.xml` |
| 最后新增的抽样、模型请求与运行环境回归 | 57 passed | `final-sampling-regressions.log` |
| 归档链接专项回归 | 5 passed，覆盖合法框架链接、绝对/越界/悬空/循环链接 | `archive-links-regressions.log` |
| 最终静态检查 | 本项目 22 个修改的 Python 文件通过 Ruff，24 个 Python 文件语法通过；Shell 与 CI YAML 通过；vendor 的既有 59 条 lint 提示未增加 | `final-static-checks.json`、`final-ruff.log` |
| GPT 真正长音频 Generator 数值对照 | 原实现触发 65536 限制；修复后 MPS 生成 80,000 采样点，与 CPU 最大误差 1.2666e-7 | `gpt-generator-mps.json` |
| 在线模型列表及真实翻译 | gpt-4o-mini 请求成功，示例翻译 4.56 秒 | `api-translation-restored.json` |
| Qwen 官方 Aiden 最终抽样方案 | MPS 模型、CPU 抽样，4.24 秒音频，生成耗时 93.72 秒；small 转写与测试句一致 | `qwen-sampler-cpu/report.json`、`qwen-cpu-sampling-content.json` |
| Qwen 原声克隆 | 真实 MPS 合成 4.16 秒音频，含启动/加载 590.60 秒 | `voices-mps-fixed3/qwen-clone-report.json` |
| GPT-SoVITS 单段长句 | 真实 MPS 合成 10.18 秒音频，含启动/加载 332.71 秒；自动回查完整句子 | `final-long-gpt/gptsovits-report.json`、`final-voice-content.json` |
| 离线与模型目录隔离 | 三种配音实测使用空白配置、禁外网、禁自动安装、离线目录禁止写入 | `voices-mps-fixed2.log`、`voices-mps-fixed3.log`、`final-long-gpt.log` |
| 四套 CPU 环境 | 全部通过并正常退出 | `telemetry-fixed-components-cpu/report.json` |
| 四套 Apple M 环境 | 全部通过；Whisper/Qwen/GPT 为 MPS，WhisperX 为 CPU | `telemetry-fixed-components-mps/report.json` |
| 最终冻结客户端自检 | 安装目录独立启动通过；8 语种路由、24 音色选项、960×640 布局、M1 检测、内置工具、错误弹窗与下载工作进程 | `final-installed-smoke.json` |
| 最终安装签名与代码一致性 | 深度严格签名通过；Qwen、GPT、随包检查工具和模型清单摘要与源码一致 | `installed-final-codesign.log`、`installed-final-source-check.json` |
| 最终图标 | ICNS 与构建图标一致；应用内 PNG 与用户原图逐字节一致 | `installed-icon-check.json`、`mac-icon-preview.png` |
| 最终 14 秒视频全流程 | 3 条字幕、0 缺译、0 适配警告；3 次配音成功；MPS 模型加载有日志 | `final-e2e/work/report.json`、`final-e2e/qwen-service.log` |
| 最终配音内容核对 | 三个原始配音片段逐一用 Whisper small 回查，均对应台词，无额外开头内容 | `final-e2e-audio-content.json` |
| 视频编码和画面 | 1280×720，H.264/AAC，音视频均 14 秒；抽帧中英文各一行，无出界或重叠 | `final-e2e/ffprobe.json`、`final-e2e/frame-11.png` |
| 4 卷压缩包完整性 | 通过；总计 6,663,488,723 字节 | `archive-test-final.log` |
| 4 卷实际重新解压 | `-snld20` 全量解压成功，107,704 文件、9,125 目录；273 条符号链接全部有效且位于应用内部 | `extract-final-snld20.log`、`extracted-final-links.log` |
| 解压后签名与启动 | 深度严格签名通过；在源码目录外启动实际解压的应用，`ok=true` | `extracted-final-codesign.log`、`extracted-final-smoke.json` |
| 解压后图标及修复代码 | 用户 PNG、ICNS、Qwen MPS 修复和验收工具与最终安装应用一致 | `extracted-final-assets.json` |
| 交付摘要 | 四卷 SHA-256 与大小已记录，最终交付检查通过 | `release/SHA256SUMS`、`release/archive-manifest.json`、`final-delivery-checks.json` |

14 项跳过原因：8 项需 PowerShell、5 项为 Windows 安装器、1 项需额外的时长探针输入环境变量；本轮另已对真实成片做 ffprobe 时长校验。新增回归与全套测试有重叠，不将数量相加。

首次 14 秒全流程在真实联网情况下完成翻译（2 次 API 请求）；最终复测复用同文本的翻译缓存（0 次 API 请求、4 次缓存命中），重新识别、配音和导出。初版对照成片在 `source-e2e`，**最终成片以 `final-e2e/SubFlow-验收成片.mp4` 为准**。

最终成片 SHA-256：`c88ab11ebd99a468e1cadd1ec71606bc03552fccbbf330d58e19d4c322dd750c`。

## 性能与实际边界

- 本机 Qwen 仍需要数十秒至数分钟生成一句，不承诺实时配音。部分测试与构建并发，计时包含冷启动与加载。
- 最终流水线墙钟时间 3,126.14 秒，其中系统多次休眠；`power-events.txt` 有系统记录。该数字不能作为连续运行性能成绩。
- 中文输入为本机合成的测试人声。Whisper small 把专名“语幕”识别为“与木”，翻译因此出现 “Mu software”。保留了原始结果；真实录音、专名和口音仍需校对。
- 自动转写是内容检查，不等同于人工听感。八语种路由和资源完整性已检查，未逐一对所有男女音色做母语听感评分。
- 未把 Intel 实机、Windows 安装器、WhisperX 真实长任务、全部 GUI 暂停/恢复组合标为实机通过。图形界面已完成自动自检；桌面点击控制在设备休眠期间多次超时，最终工具明确报告 Mac 锁屏，未补做人工点击验收。
- 本地临时签名的完整性检查通过；此版本未做 Apple 公证。

## 安装、交付与回退

- 当前应用：`/Applications/SubFlow.app`。
- 源码：`<源码目录>`。
- 完整分卷：本证据目录的 `release/SubFlow-macos-arm64-1.3.61.7z.001` 至 `.004`，必须放在同一目录。保留所有卷后从 `.001` 解压。步骤见 `release/使用说明.md`，逐卷摘要为 `release/SHA256SUMS`，大小与摘要清单为 `release/archive-manifest.json`。
- 原 1.3.60 应用保存在 `SubFlow-1.3.60.app.backup`；修复前源码为 `source-before.tar.gz`，文件摘要为 `source-before.json`。
- 用户原有 README 修改、未跟踪的联系图片及 Windows 产物均保留。`repair-changes.patch` 是相对用户原始源码的语义差异，忽略原有 CRLF 差异；PNG 二进制直接保存在源码中。
- API 凭据保存在用户凭据存储中，未写入源码、验收报告或分发包。

复现步骤见源码 `docs/mac-self-test.md`。随包 `mac_acceptance.py` 的 `product_acceptance=pending_manual_tests` 表示它只负责组件检查，并非整个产品的人工验收结论。
