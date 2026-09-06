# 架构与处理边界

[返回文档索引](README.md) · 对应 **1.3.46**

SubFlow 提供 CLI、Qt 桌面和 Docker CLI 三种入口，共用任务模型及处理流水线。翻译使用固定 meding 端点，识别和默认配音在本机独立环境运行。

## 数据流

```text
CLI / GUI / Docker CLI
        ↓
JobConfig → pipeline.run
        ├── 链接入库：adapters.ytdlp
        ├── 抽音与静音检测：core.audio → adapters.ffmpeg
        ├── 识别：core.asr → Whisper / WhisperX worker
        ├── 字幕整理：core.cues、core.langs
        ├── 术语与翻译：core.glossary*、core.translate → adapters.meding
        ├── 可选润色：core.translate_refine
        ├── 时长与布局：core.netflix、core.render → ASS / SRT
        ├── 烧录：core.burn → FFmpeg
        └── 可选配音：core.dub → GPT-SoVITS → 混音与成片
```

阶段顺序由 [models.py](../src/bilingual_sub/models.py) 的 `STAGES` 定义，是否实际执行由输入、字幕模式、语种、配音设置及恢复状态决定。中文源片输出中文简繁目标会跳过合成配音；双语字幕仍可执行英文翻译。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| [cli/main.py](../src/bilingual_sub/cli/main.py) | 参数校验、配置、环境检查、分步命令及退出码 |
| [gui/app.py](../src/bilingual_sub/gui/app.py)、[gui/workers.py](../src/bilingual_sub/gui/workers.py) | 窗口、后台任务和进度交互 |
| [pipeline.py](../src/bilingual_sub/pipeline.py) | 阶段调度、恢复、产物提交与结果报告 |
| [core/control.py](../src/bilingual_sub/core/control.py) | 暂停、继续、取消与进程等待 |
| [core/output_guard.py](../src/bilingual_sub/core/output_guard.py)、[core/resource_claims.py](../src/bilingual_sub/core/resource_claims.py) | 输入保护与跨任务文件占用 |
| [core/cache_records.py](../src/bilingual_sub/core/cache_records.py)、[core/persistence.py](../src/bilingual_sub/core/persistence.py) | 产物身份、持久化与恢复校验 |
| [adapters/runtime_bootstrap.py](../src/bilingual_sub/adapters/runtime_bootstrap.py) | 独立 Python、依赖安装、版本检查和安装锁 |
| [adapters/tts/gptsovits_runtime.py](../src/bilingual_sub/adapters/tts/gptsovits_runtime.py) | GPT-SoVITS 环境、模型和服务生命周期 |
| [secrets/store.py](../src/bilingual_sub/secrets/store.py) | 环境变量、系统凭据库与文件备用存储 |

主程序、ASR、可选 WhisperX、GPT-SoVITS 环境分别管理，避免将所有 Torch 依赖加载进 Qt 主进程。桌面社区包附带安装器和适配源码，首次联网准备环境；Docker 在构建时准备依赖，模型按需下载。

## 关键任务配置

完整定义见 [JobConfig](../src/bilingual_sub/models.py)，命令参数见 `subflow run --help`。

| 字段 | 作用 |
| --- | --- |
| `input_video` / `source_url` | 本地视频或下载来源 |
| `output_video` / `output_srt` | 输出成品与字幕 |
| `work_dir` | 任务状态、中间文件和日志目录 |
| `asr_backend` / `whisper_model` | Whisper / WhisperX 及识别模型 |
| `device` | `auto` / `cpu` / `cuda` / `mps` |
| `source_lang` / `target_lang` | 识别语言与配音目标 / 中文简繁 |
| `subtitle_mode` | 中英、英中、单语等布局 |
| `translate_model` / `refine_translate` | 翻译模型及可选润色 |
| `glossary_path` / `glossary_generate` | 术语来源 |
| `subtitle_zh_color` / `subtitle_en_color` | 中文字幕与英文字幕颜色 |
| `burn` / `enable_dub` | 烧录和配音请求，仍受语种规则约束 |
| `tts_provider` / `tts_endpoint` | 配音提供方与服务地址 |
| `tts_ref_audio` / `tts_prompt_text` / `tts_prompt_lang` | 参考音频、对应文本与语言 |
| `resume_from` / `preview_minutes` | 恢复阶段与预览范围 |

## 文件安全与恢复

输入视频、术语表、参考音频和输出参与路径检查及跨进程占用登记。Mac 对大小写及 Unicode 组合形式采取保守冲突检查；自定义部署需让共享文件的任务使用一致路径映射和登记目录。

作业状态、字幕、报告和成片提交需要协调；取消或失败不能把不完整文件标记为成功。缓存验证包含处理设置、修订和相关产物内容，不能只凭文件名、大小或时间戳复用结果。

通过校验时，只改输出位置可复制已有成品，只改字幕颜色可从渲染开始；配置、媒体、参考音频或配音模型身份变化会使对应缓存失效。

## 设备与服务边界

Apple Silicon 默认配置 MPS；CPU 回退记录实际设备。WhisperX 不支持 MPS，Docker 保持 Linux CPU。GPU 可用性需实际运算确认，不能只凭 PyTorch 编译标记认定成功。

客户端启动配音服务是预热行为，任务是否配音由流水线决定。默认服务是本机 GPT-SoVITS，客户端管理自己启动的进程；自定义外部服务需保证参考音频路径可达。CPU 取消请求不等于已经中断所有正在执行的模型运算，模型释放与下一请求受服务锁约束。

## 开发约束

- 核心处理不依赖 CLI / GUI 界面。
- 外部命令使用已有的受管理进程、取消和输出捕获机制；FFmpeg 命令通过对应适配器运行。
- 字幕样式使用 [config/presets](../config/presets)，桌面颜色与字号使用 [gui/theme.py](../src/bilingual_sub/gui/theme.py)。
- 翻译端点常量集中在 [adapters/meding.py](../src/bilingual_sub/adapters/meding.py)，鉴权与缓存行为见 [API 契约](api-meding.md)。
- 第三方 GPT-SoVITS 适配与许可资料留在 [third_party/GPT-SoVITS](../third_party/GPT-SoVITS)。

检查与提交流程见 [贡献指南](../CONTRIBUTING.md)。
