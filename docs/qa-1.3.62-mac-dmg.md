# SubFlow 1.3.62 · Mac DMG 交付与验收

日期：2026-09-07。源码直接修复于 `<源码目录>`。证据目录：`~/Downloads/SubFlow-DMG-QA-20260907`。

两种架构的完整 DMG 均通过磁盘映像校验、应用内部链接检查、全部 Mach-O 文件架构检查、深度严格签名及从只读 DMG 中启动的冻结客户端自检。图标已按用户批准使用本地程序精确制作。

## 安装包

| 架构 | 文件 | 大小 | 检查的原生二进制数 | 最低 macOS |
| --- | --- | --- | --- | --- |
| arm64 | SubFlow-1.3.62-Apple-M-arm64.dmg | 6.62 GiB | 1489 | 14.0 |
| x86_64 | SubFlow-1.3.62-Intel-x86_64.dmg | 6.98 GiB | 1373 | 14.0 |

两个包分别支持 Apple M 与 Intel；安装时只选择与芯片对应的一包。均含离线配音模型与四套独立运行环境。Apple M 使用 MPS/CPU，Intel 使用 CPU。打开 DMG 后拖入 Applications，复制完成后推出映像，从“应用程序”启动。需要为完整应用预留约 12–15 GB 空间。

安装包采用本地临时签名，未做 Apple 公证。具体首次打开步骤见同目录《安装与Cookies说明.md》。SHA-256 在 `release/SHA256SUMS`，字节大小及架构记录在 `release/delivery-manifest.json`。

本轮未自动替换现有 `/Applications/SubFlow.app`，当前安装版本为 1.3.61；退出旧客户端后再拖入新版安装。

## 本轮修复

- 图标：从用户原始 Sub.png 提取品牌图形与文字，制作透明圆角底板、适当留白、平滑边缘及轻微阴影；16/32 逻辑尺寸使用云形简化版；生成完整 16–1024 像素 ICNS，并同步 Qt 窗口图标。两个包的 PNG、ICNS 与源码逐字节一致。见 `artwork/icon-sizes.png`、`icon-checks.json`、`bundle-source-assets.json`。
- Cookies：修复 Netscape 文件中 `#HttpOnly_` 行被误当作注释的问题，避免有效 YouTube/Bilibili 登录状态被忽略；增加格式回归。当前客户端自动读取 `~/.config/subflow/Cookies/youtube-cookies.txt` 与 `bilibili-cookies.txt`，不将 Cookie 字符串填写到 API Key 输入框。
- 构建：明确目标架构并校验 Python、FFmpeg、ffprobe、uv 与所有原生依赖；Intel 使用独立 x86_64 Python 和 CPU PyTorch 2.2.2，Apple M 保留 arm64/MPS 环境；运行环境不依赖源码目录或已删除的 Intel 构建缓存。
- DMG：提供 Applications 拖拽入口、安装背景和 Cookies 说明。移除会给已签名应用增加 FinderInfo 的隐藏扩展名操作，避免签名失效；压缩前、压缩后实际挂载均验签；未通过验收的文件保留 `.unverified.dmg` 名称，只有通过后才成为正式交付文件。
- 大型离线应用首次启动会触发 macOS XProtect 扫描。验收脚本允许 900 秒等待，并支持对已生成映像恢复完整验证，无需重新压缩；未关闭系统安全检查。

## 本轮验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| Cookies、Mac 回归、代理与构建后端 | 32 passed | `regressions.log` |
| 下载及控制流程 | 73 passed | `download-regressions.log` |
| DMG 架构识别 | 4 passed | `dmg-architecture-tests.log` |
| 当前 SDK 在线翻译 | 真实请求成功，gpt-4o-mini | `translation-current-sdk.json` |
| Intel 四套随包运行环境 | 全部通过，包括张量、识别编解码、长音频卷积与 CTranslate2 | `intel-components/report.json` |
| Intel Whisper small 真实识别 | 正确识别测试句，禁止网络访问 | `intel-asr-inference.json` |
| Intel 三种配音内容 | 独立 Whisper small 转写与测试台词一致 | `intel-voice-content.json` |
| 非系统绝对动态库依赖 | 两种架构共 2,862 个二进制检查通过，未发现构建机路径依赖 | `native-dependency-audit.json` |
| 两种 DMG 完整性、架构、链接及签名 | 全部通过 | `dmg-arm64-verified/report.json`、`dmg-intel-final/report.json` |
| 两种只读挂载应用的冻结自检 | `ok=true`，脱离源码目录运行 | 两个 DMG 验证目录的 `mounted-smoke.json` |

上述三组专项测试共 109 项，未把上一版全套测试数量计入本轮。Intel 识别结果：**Hello, how can I help you today? It is nice to meet you.**。

Intel 真实配音使用空白用户配置、禁外网、禁自动安装、模型目录只读，均生成非静音 WAV：

| 引擎 | 音频长度 | 含启动与加载耗时 |
| --- | --- | --- |
| qwen-native | 4.56 秒 | 210.19 秒 |
| qwen-clone | 4.48 秒 | 159.80 秒 |
| gptsovits | 8.62 秒 | 160.85 秒 |

证据：`intel-voices-warm/report.json`、对应引擎日志及 WAV。耗时包含 Rosetta、冷启动和并行构建影响，不用于宣称 Intel 实机性能或实时合成能力。

## 验证边界与保留记录

- 物理设备为 Apple M1、8 GB、macOS 14.5；Intel 包在本机通过 Rosetta 执行 x86_64 代码，尚未做 Intel 物理电脑验收。
- 上一版 1.3.61 已在 M1 完成真实识别、在线翻译、三种配音、双语字幕和视频导出；详细记录在源码 `docs/qa-1.3.61-m1.md`。1.3.62 复用这些推理修复，本轮侧重新图标、Cookies、Intel 环境与实际 DMG，不把前一版视频结果称为本轮重新执行的全流程结果。
- 新版 GUI 已完成冻结程序自动自检；本轮桌面自动控制工具超时，未将人工逐项点击标为通过。未宣称所有真实视频、会员视频、全部语种音色及长任务都已验收。
- 首次 Rosetta Qwen 环境检查超过 180 秒，原始日志为 `intel-voices.log`；四套独立组件预热完成后使用同一未修改应用复测。Apple M 首次从 DMG 启动遇到 XProtect 扫描，原 300 秒限时不足；保留 `dmg-arm64-final.log`、`arm-dmg-startup-sample.txt` 和系统日志。最终交付以延长等待后的完整验证结果为准。
- 早期 DMG 发现 FinderInfo 破坏签名，曾尝试影子映像修复并遇到磁盘空间不足；失败文件已清理，诊断日志保留。最终包由修正后的流程生成。
- 语音组件检查器的 `product_acceptance=pending_manual_tests` 是其固定职责说明：组件检查不代表全部人工验收。此报告列出了实际执行范围。
- 用户 README 经原始 SHA-256 校验未改动，原联系图片、Windows 产物和原始源码/应用备份保留。相对用户原始源码的语义差异在 `repair-changes.patch`，忽略既有 CRLF 差异。API 凭据未写入源码或分发包。

Cookies 的完整导出步骤及官方参考链接见 `docs/mac-install-cookies.md` 和随 DMG 附带的说明文件。
