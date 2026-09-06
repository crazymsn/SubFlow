# Qwen 配音音色与设备

适用于 **1.3.60**。菜单提供自动选择、9 个官方预设和 14 个 SubFlow 设计音色，共 **23 个音色（12 男声、11 女声）**。

## 模型选择

2026 年 9 月 6 日核查：[Qwen 官方开放权重列表](https://huggingface.co/Qwen?search_models=TTS) 和 [官方代码仓库](https://github.com/QwenLM/Qwen3-TTS) 仍列出 Qwen3-TTS 0.6B / 1.7B 系列。较新的 [Qwen-Audio-3.0-TTS 技术报告](https://arxiv.org/abs/2607.23938) 已发布，但本次未找到对应的官方公开权重与本地推理发布包。因此保留可离线部署的 Qwen3-TTS，不用云端 API 冒充新版开源模型。

官方 CustomVoice 的 0.6B 和 1.7B 都只有 9 个预设说话人。换成更大的 CustomVoice 并不会自动增加音色。项目使用官方推荐的 [Voice Design then Clone](https://github.com/QwenLM/Qwen3-TTS#voice-design-then-clone) 流程：构建时用 1.7B VoiceDesign 生成独立参考音频，客户端用已有的 0.6B Base 合成后续语音。VoiceDesign 大模型不需要随客户端分发或在首次使用时下载。

## 官方预设

| 音色 | 性别 | 原生语种 / 风格 |
| --- | --- | --- |
| Aiden | 男声 | 英语，美式风格 |
| Ryan | 男声 | 英语，节奏感较强 |
| Uncle_Fu | 男声 | 中文，成熟低沉 |
| Dylan | 男声 | 中文，北京风格 |
| Eric | 男声 | 中文，四川风格 |
| Serena | 女声 | 中文，温柔 |
| Vivian | 女声 | 中文，明亮 |
| Ono_Anna | 女声 | 日语，轻快 |
| Sohee | 女声 | 韩语，温暖 |

性别与原生语种依据 [Qwen 官方音色表](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice#supported-speakers)。它们支持模型覆盖的其他语言；跨语种后的口音、节奏仍需试听确认。

## SubFlow 设计音色

| 目标语种 | 新增男声 | 新增女声 | 设计发音目标 |
| --- | --- | --- | --- |
| 简体中文 / 繁体中文 | SubFlow 中文男声 | SubFlow 中文女声 | 普通话 |
| 英语 | SubFlow 英语男声 | SubFlow 英语女声 | 通用美式英语 |
| 日语 | SubFlow 日语男声 | SubFlow 日语女声 | 标准日语 |
| 西班牙语 | SubFlow 西班牙语男声 | SubFlow 西班牙语女声 | 欧洲西班牙语 |
| 法语 | SubFlow 法语男声 | SubFlow 法语女声 | 标准法国法语 |
| 德语 | SubFlow 德语男声 | SubFlow 德语女声 | 标准德语 |
| 俄语 | SubFlow 俄语男声 | SubFlow 俄语女声 | 标准俄语 |

以上是独立合成的设计音色，并非真实人物录音，也不是 Qwen 官方命名预设。界面明确标注“设计音色”，性别和发音目标来自生成描述；实际听感需通过试听判断。简繁中文共用普通话声音，因此七种口语覆盖八种字幕目标。

菜单按目标语言优先排列，同时保留手动选择。自动模式：中文 Serena、英语 Aiden、日语 Ono_Anna；西班牙语、法语、德语、俄语使用对应的 SubFlow 设计女声。试听文本跟随目标语种，用户可自行修改。中文源片选择简体或繁体目标时默认保留原声。

参考音频、逐字参考文本、模型 revision、生成描述和 SHA-256 记录在 `src/bilingual_sub/_data/bootstrap/voices/voices.json`。这些 WAV 是运行必需的产品资源，不能作为测试音频清理。开发者可用 `scripts/build-voice-bank.py` 在已准备的 Qwen 环境中重新生成；修改音频后必须同步更新清单。

## 设备与离线运行

- Windows 优先 NVIDIA CUDA；没有可用 CUDA GPU 时使用 CPU。
- Apple M 系列 Mac 优先 MPS；不可用时使用 CPU。M1 实机验收仍由用户完成。
- 标准预设和设计音色切换时，先释放旧模型再加载另一模型，避免同时占用两份显存。
- GPU 显存或算子错误才触发 CPU 回退；音频损坏、缺文件等错误不会误触发 CPU 重载。
- 服务状态显示实际推理设备。显式设置 `SUBFLOW_TORCH_BACKEND=cpu` 可以强制 CPU。
- 完整包内置 CustomVoice、Base 和 GPT-SoVITS v2 及其运行环境。设计音色不会引入新的首次下载；精简版仍需准备 CustomVoice 和 Base。

验收记录见 [1.3.53 本地验收](qa-1.3.53.md)。本次发布范围见 [1.3.60 发布说明](release-1.3.60.md)。
