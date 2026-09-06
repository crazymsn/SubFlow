# 1.3.34 真实 CPU 媒体验收

> 历史记录：此文件保留当时的结果和版本状态，不代表当前安装包。最新使用说明见[文档索引](README.md)。

> 历史技术记录：下文描述当时的版本和验证范围，旧安装包及本地临时证据可能已清理。当前安装请使用 [1.3.46 指南](README.md)，最新发布检查见 [1.3.46 验收记录](release-1.3.46.md)。

日期：2026-09-06。受测提交：`381f174f59234b82791bae60f86a0d719ad6e2d6`。本次在 Windows 上运行该提交的源码和项目内 GPT-SoVITS，使用已准备的独立 CPU 推理环境；没有重新冷安装，也没有以此替代冻结客户端或 Apple GPU 的实机验收。

ASR 与 GPT-SoVITS 环境均为 Python 3.11、PyTorch / torchaudio `2.5.1+cpu`，实际检查 `torch.version.cuda` 为 null。测试显式选择 CPU，关闭自动安装，通过独立端口启动本次配音服务。测试仅清理本次拥有的服务进程。

## 中文保留原声

输入为 4.12 秒、640 × 360 的中文语音 MP4，使用真实 Whisper tiny 识别。分别选择匹配的单行简体、单行繁体字幕模式，保留 `enable_dub=True` 和 GPT-SoVITS 选择，以验证遗留配音开关不会让同语种任务合成配音。将翻译和配音入口替换为一旦调用即失败的断言；识别、静音检测、字幕生成、烧录和恢复均实际执行。

| 检查 | 简体中文 | 繁体中文 |
| --- | --- | --- |
| 有效字幕段数 | 2 | 2 |
| 翻译调用次数 | 0 | 0 |
| 配音状态 | false | false |
| 与原声音轨的归一化波形相关值 | 0.9999783 | 0.9999783 |
| 解码音频 RMS 幅度比 | 0.9994110 | 0.9994110 |
| 解码音频时长差 | 0 秒 | 0 秒 |
| 完成阶段恢复 | 无重新识别 / 烧录 | 无重新识别 / 烧录 |

音轨比较使用单声道 16 kHz PCM；通过阈值为相关值大于 0.97、幅度比在 0.85–1.15、时长差小于 0.05 秒。烧录会重新编码 AAC，因此不要求音频字节相同。简繁文字分别通过 OpenCC 对应转换的不变性检查。恢复到新输出位置后，MP4 摘要与首次产物相同。

tiny 的首句识别存在文字误差，本记录只验收处理路径和简繁转换，不将这些结果认定为字幕准确率达标或人工试听通过。

## 纯 CPU 配音、混音和缓存

服务约 11 秒后就绪，运行接口报告 `device=cpu`、`is_half=false`、`torch_version=2.5.1+cpu`。以现有参考音频和固定英文文本 `Hello, welcome to SubFlow.` 实际调用 GPT-SoVITS，再通过 `dub_cues` 生成视频。

| 检查 | 实测结果 |
| --- | --- |
| 相同输入连续两次运行的合成调用数 | 1，第二次复用缓存 |
| 成片视频时长 | 4.12 秒 |
| 解码配音时长 | 4.1386875 秒 |
| 解码 PCM RMS | 726.4232，非静音 |
| 配音与原音频摘要 | 不同 |
| 原始视频摘要 | 保持不变 |
| 测试服务退出码 / 剩余所有权记录 | 0 / 0 |

已观察到的服务父子进程均在清理后退出。这里实际执行了合成和混音，但英文使用固定测试文本，没有调用外部翻译接口；非静音和摘要变化不能代替人工核对发音、音色和节奏。

## 构建与可下载客户端

[GitHub Actions 33992811131](https://github.com/crazymsn/SubFlow/actions/runs/33992811131) 的受测提交与上文一致，Windows、Apple Silicon、Intel Mac 和 Docker 四项作业全部成功。publish 跳过，本次为 Actions 构建产物，不是已发布的 Release；产物受 GitHub 保留期限约束，下载可能要求登录。

- [Windows x64](https://github.com/crazymsn/SubFlow/actions/runs/33992811131/artifacts/9977281344)
- [Mac arm64（M1 / M 系列）](https://github.com/crazymsn/SubFlow/actions/runs/33992811131/artifacts/9977205362)
- [Mac Intel](https://github.com/crazymsn/SubFlow/actions/runs/33992811131/artifacts/9977268776)

M1 MacBook Air 的最终 GPU、内存、速度及试听测试由用户自行执行，步骤见 [Mac 实机清单](mac-self-test.md)。Mac 上的 Linux Docker Compose 使用 CPU，不以 arm64 构建成功作为容器支持 Apple GPU 的证据。

## 本地证据

以下路径相对于本次工作区，属于忽略的本地验收产物，未随本记录上传到 GitHub：

- `.verify/current-media-acceptance.py`：验收脚本，包含本机解释器和参考媒体路径。
- `.verify/current-media-1.3.34-validated-run.log`：完整成功运行日志。
- `.verify/current-media-1.3.34-validated/acceptance.json`：机器可读结果。
- 同目录的 `zh.mp4`、`zh-Hant.mp4`、`english-dubbed.mp4`：可播放成片；`server.log`：独立配音服务日志。

SHA-256：

| 文件 | 摘要 |
| --- | --- |
| 输入 `chinese-source.mp4` | `e1a29675bd6800718f9ba070915465d496894d7b9d08c738cd4745eb527f6515` |
| 验收脚本 | `7def06b334c6d1b93098695a7dd4ec2c1139c74eb1d1bb0c1b6c29299f658704` |
| 成功结果 JSON | `b1e3d5da9caededb3bdcc30104431ad8a6f4ec173a5610bb6c09ad00c731b70c` |

前两次尝试分别使用了过严的 AAC 解码摘要相等断言，以及与目标繁体不一致的显式简体字幕模式；修正测试配置和原声判据后，从新工作目录完整运行成功。没有因此修改产品代码。本次仅补充验收记录，不变更版本号；此前全量回归为 979 项通过、1 项跳过，核心覆盖率 91.31%。
