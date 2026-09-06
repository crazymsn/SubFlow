# 完整配音客户端

适用于 **1.3.60**。桌面完整包内置三种配音模式，以及 Whisper / WhisperX 识别依赖；识别模型按需下载。平台支持见[环境覆盖说明](runtime-coverage.md)。

| 引擎 | 随包内容 | 参考音频 |
| --- | --- | --- |
| Qwen3-TTS 标准音色 | 0.6B CustomVoice + Base、语音 tokenizer、9 个官方预设和 14 个设计音色 | 不需要 |
| Qwen3-TTS 原声克隆 | 0.6B Base 模型、语音 tokenizer | 用户自己的清晰人声，3–10 秒 |
| GPT-SoVITS | 适配源码、v2 配对权重、BERT、HuBERT、G2PW、语言识别和 NLTK 数据 | 用户自己的清晰人声 |

三个引擎指以上三种配音模式，不表示同时预装 GPT-SoVITS 的所有历史权重版本。完整包不包含开发者的 API 令牌、Cookie、个人录音、视频或任务缓存。

包含四套运行环境的完整包体积较大。下载前查看各分卷大小，并同时为解压目录、识别模型、媒体及输出预留空间；不要沿用旧版仅配音环境的体积估算。Mac 体积由各架构依赖决定。

## 使用

完整解压后，Windows 从 `SubFlow/SubFlow.exe` 启动；Mac 使用对应芯片架构的 `SubFlow.app`。不要仅复制 EXE，或删除 `offline` 目录。包内环境不要求用户预装 Python、PyTorch 或 CUDA Toolkit；NVIDIA GPU 仍需要设备自身可用的显卡驱动。

配音不再首次下载模型和运行依赖。首次加载仍会进行本地文件校验和模型加载；速度取决于磁盘、内存和计算设备。标准音色可以直接试听；克隆模式仍需要用户提供参考人声。识别模型按所选 Whisper / WhisperX 型号准备，云端翻译和链接下载仍需要联网，因此“内置配音”不代表整个视频流程完全离线。

Windows 优先可用 NVIDIA CUDA，Apple M 系列原生客户端优先 MPS；没有可用 GPU 时使用 CPU。Windows 的内置 CUDA 版 PyTorch 同时包含 CPU 实现，无显卡设备不会为配音重新下载另一套环境。Intel Mac 使用 CPU。Apple GPU 实机验收由 M1 MacBook Air 用户完成，Windows 测试不能替代 Metal 实机测试。

模型通过内容摘要校验，解压改变文件时间戳不会触发下载。校验缓存与运行日志写到用户目录，不要求对应用目录有写权限。完整包损坏会明确提示重新解压，不会悄悄回退到首次下载流程。

GitHub 单个 Release 附件必须小于 2 GiB，完整包构建使用每卷 1900 MiB 的 7z 分卷。下载同一平台的全部 `.7z.001`、`.7z.002` 等文件，放在同一目录，用支持 7z 分卷的工具从 `.001` 解压。缺少任一卷都无法得到完整客户端。依据：[GitHub 附件限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。

## 构建与验证

Windows：

```powershell
./scripts/build-windows.ps1 -SkipInstall -DistPath dist/full
```

macOS 在对应芯片的原生 Mac 上构建：

```bash
bash scripts/build-macos.sh
```

构建机首次需要联网准备依赖与模型，成功后才生成完整包清单。Windows 发布包使用 CUDA 依赖构建，即使构建机本身没有显卡也可以完成导入检查。`-HardlinkModels` 可减少同一磁盘上组装大文件的额外占用；归档后的包包含完整文件内容，不引用开发机路径。不可在组装完成后原地修改这些模型和二进制文件。

仅开发调试需要的小包可显式使用 Windows `-SourceOnly` 或 Mac `SUBFLOW_SLIM_BUILD=1`，这种包保留首次联网准备行为，不作为完整离线配音包分发。

迁移后真实验收：

```bash
python scripts/check-offline-voices.py /path/to/offline --backend auto --output /path/to/qa-gpu
python scripts/check-offline-voices.py /path/to/offline --backend cpu --output /path/to/qa-cpu
```

该脚本使用空白配置、关闭自动安装、阻断合成服务的外网连接和依赖安装器，并限制 Python 对应用文件的写入；实际合成三段音频并记录模型路径、解释器路径和实际计算设备。GPT-SoVITS 另外检查中、英、日、韩、粤语言资源。生成的中性标准音色用于其余两个引擎的参考音频，验收录音不会进入发布包。`--backend auto` 在无 GPU 的构建机上通过只代表 CPU 通过，应查看报告中的实际设备。

Qwen 模型固定到仓库中的版本清单，按 [官方模型卡](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) 的 Apache-2.0 许可保留归属与许可文本；各运行依赖的许可证保留在包内，GPT-SoVITS 使用其源码附带的许可证。
