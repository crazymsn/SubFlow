# 1.3.55 本地修复与验收记录

> 历史记录：此文件保留当时的结果和版本状态，不代表当前安装包。最新使用说明见[文档索引](README.md)。

日期：2026-09-06。执行环境：Windows x64、RTX 3060 Laptop 6 GB；测试主环境 Python 3.13.13，内置推理环境 Python 3.11.15 / PyTorch 2.5.1+cu124。

本轮完成 Windows 侧代码回归、真实 CUDA 配音、客户端打包与清理后自检。**没有在 Mac 实机运行，也没有构建新 Mac 安装包**；Mac 的最终验收请按 [详细手册](mac-self-test.md) 在 M1 / Intel 分别完成。自动测试通过不能证明所有未知问题已经不存在。

## 本轮修复

- Mac 构建使用隔离 venv，拒绝 Rosetta 和 Python/系统架构不一致；Apple M 完整包要求 MPS/CPU 原生环境，Intel 要求 CPU 环境。
- 复用离线环境时校验系统、架构和四套运行环境，拒绝缺少 Whisper / WhisperX 的旧包被当成新完整包。
- 补齐 fat64 Mach-O 文件签名识别。实际 Apple 签名、启动和模型推理仍需原生 Mac 验证。
- 新增随包 `mac_acceptance.py`，保存四套环境及代表性计算检查结果；明确区分组件通过、GPU 通过和待人工完成的产品验收。
- 严格 GPU 合成检查不再把 CPU 回退当成 GPU 成功。
- 加强任务线程的 Qt 所有权与退出等待；移除 WhisperX 未使用的旧解释器辅助函数。
- 修复测试中的 Qt 延迟释放对象残留，统一 QApplication 生命周期并清理测试窗口；原先“试听测试后执行恢复测试”可稳定触发的崩溃已消除。
- 删除过期测试对“折叠设置”按钮的引用，保留当前常驻设置的功能测试；打包排除开发环境生成的 bootstrap 字节码缓存。
- 同步 Mac 手册、安装指南、贡献指南及环境说明，纠正旧的 SourceOnly 完整包说明和发布流程说明。

## 回归结果

```text
1525 passed, 3 skipped, 3 warnings in 286.92s
bilingual_sub.core coverage: 92.18%（门槛 80%）
Ruff: All checks passed
```

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -p pytest_cov --tb=short -q -rs --durations=10 -o faulthandler_timeout=120
python -m ruff check src tests scripts
```

三项初始跳过中，视频时长探测随后使用用户已提供的本地 MP4 **补测通过**，只读访问原视频。因此共验证 **1526 个不同用例**，剩余两项为 Windows 不支持相应只读目标替换操作的条件跳过，不能计为通过。三个警告为测试依赖的弃用提示，没有隐藏测试失败。

回归覆盖路径保护、音频/字幕缓存、故障恢复、翻译续跑、任务取消和子进程回收、字幕布局、八语种界面以及配音路由。音色自然度与真实 Mac 性能仍需人工实测。

## 真实内置环境与 GPU 配音

四套内置解释器均执行了 CPU 组件检查：Whisper 小型编码器/解码器、WhisperX CTranslate2 CPU、Qwen 依赖与 SDPA、GPT-SoVITS 频谱计算。该结果来自 Windows，不是 Mac GPU 验收。

使用正式目录 `dist/SubFlow/offline`，在空用户缓存、禁止自动安装并阻止外网连接的条件下执行：

```text
python scripts/check-offline-voices.py dist/SubFlow/offline --backend cuda --require-gpu --output <新的临时验收目录>
```

| 配音模式 | 实际设备 | 输出音频时长 | 含启动的本轮耗时 |
| --- | --- | --- | --- |
| Qwen 标准音色 | cuda:0 | 4.08 秒 | 62.20 秒 |
| Qwen 原声克隆 | cuda:0 | 4.24 秒 | 53.79 秒 |
| GPT-SoVITS | cuda | 3.94 秒 | 42.38 秒 |

三项均返回有效、非静音 PCM 音频，并在合成后核实设备。耗时是本机本次观测，不是其他设备的性能承诺。该项未重复全部设计音色的人工听感评估。

## 客户端与清理

- 原目录 `dist/SubFlow` 已更新为 **1.3.55**，更新三个客户端文件；沿用已经验收的四套运行环境和三种配音模式模型。离线 payload 清单仍记录其原组装版本 1.3.54，客户端代码版本为 1.3.55。
- 暂存包和原路径自检通过，检查实际 Qt 界面、八语种路由、错误弹窗、FFmpeg / ffprobe / uv 与独立下载进程。清理完成后再次在原路径执行自检。
- 删除约 **1.17 GiB** 的构建目录、1.3.54 / 1.3.55 暂存包及源码缓存；`dist` 最终只保留正式 `SubFlow` 目录。
- 删除 **8,028,058,870 字节（约 7.48 GiB）** 的临时设计模型、未完成下载、已确认的试听测试输出与临时截图/配置目录。
- 本轮合计处理约 **8.65 GiB 的文件内容**。部分文件使用硬链接，该数值不等于保证释放的物理磁盘空间。
- 清理前后检查正式 EXE、模型清单、FFmpeg、ffprobe 和用户配置哈希，均未因清理改变。保留在用模型、语言词典、23 种产品音色资源、有效回归测试源码、原视频、用户配置、Cookies 和回滚备份；未清理其他项目的共享临时目录。
- 原客户端被替换的文件保存在本机临时目录 `subflow-before-1.3.55`。混有回滚备份或已交付视频的旧临时目录保留，避免把用户产物误删。

原目录 EXE SHA-256：

```text
26dfc50ad40ff614b1fa1ac32d9ffc66a816c97007ffbbcdf6b1db259bdf2857
```

没有推送 GitHub、发布 Docker 或替换正式 1.3.46 附件。Mac 的签名、MPS 真实模型推理、Intel CPU、八语种听感及完整视频验收仍待实机结果。
