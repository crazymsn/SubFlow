# 架构 — SubFlow 语幕

产品：**SubFlow 语幕**（深度云创科技）。CLI 入口 `subflow`，桌面入口 `subflow gui` / `SubFlow.exe`，容器入口 `crazymsn/subflow:latest`。

保存 API 令牌后调用 `GET /v1/models` 填充翻译模型。Base URL 固定为 `https://api.meding.site`，只在 `adapters/meding.py` 出现一次。列表会丢掉 BAAI / 智源相关 id。

```
CLI / GUI / Docker
        ↓
   pipeline.run
        ├── ingest          yt-dlp（仅当 source_url 有值；游客失败后读浏览器 Cookie）
        ├── core.audio      抽音、silencedetect
        ├── adapters.whisper / whisperx
        ├── core.cues + glossary / glossary_ai
        ├── core.translate → adapters.meding + secrets
        ├── core.translate_refine   （可选电影级润色）
        ├── core.render     ASS / SRT（subtitle_zh_color / subtitle_en_color）
        ├── core.burn       adapters.ffmpeg
        └── core.dub        OpenAI TTS / GPT-SoVITS
```

桌面层：`gui/app.py` 组窗口；`gui/theme.py` 管颜色与字阶；`gui/widgets/color_chip.py` 是字幕色块；`gui/workers.py` 把流水线丢到后台线程。`core/*` 不得依赖 `cli` / `gui`。

## JobConfig

| 字段 | 说明 |
| --- | --- |
| `input_video` | 输入视频 |
| `source_url` | YouTube / Bilibili 等地址，先 ingest 再识别 |
| `output_video` | 烧录 MP4；`burn=false` 时可空 |
| `output_srt` | 输出 SRT |
| `work_dir` | 工作目录，`auto` = 系统临时目录下的作业夹 |
| `style_preset` | 样式 preset 名 |
| `subtitle_zh_color` / `subtitle_en_color` | 烧录用的中英 HEX 颜色 |
| `whisper_model` | Whisper 模型名 |
| `asr_backend` | `whisper` / `whisperx` |
| `device` | `auto` / `cuda` / `cpu` |
| `source_lang` / `target_lang` | 识别语言与翻译方向 |
| `subtitle_mode` | `bilingual` / `netflix_single` |
| `translate_model` | meding 模型 id |
| `refine_translate` | 电影级润色 |
| `glossary_path` / `glossary_generate` | 术语表 / 从视频抽术语 |
| `burn` | 是否烧录 |
| `enable_dub` / `tts_provider` / `tts_voice` / `tts_endpoint` | 配音 |
| `resume_from` | 从某阶段继续 |
| `preview_minutes` | 只处理前 N 分钟 |

阶段顺序见 `models.STAGES`：`init → ingest → extract → silence → transcribe → build_cues → glossary → translate → fit_subs → render → burn → dub → done`。

只改输出路径：拷贝成品。只改字幕颜色：从 `render` 续跑。

## 扩展点

- **新 preset**：`config/presets/*.yaml`
- **术语**：`--glossary` 或作业配置
- **换翻译后端**：fork 后改 `adapters/meding.py`（官方不开放改 Base URL）

## 依赖规则

- `core/*` 不依赖 `cli` / `gui`
- `adapters/*` 不 import `core/cues`
- `secrets.store` 不写明文 Key 到日志
- 新增外部命令一律走 `adapters/ffmpeg.py`
- 样式按 2560×1600 设计稿，渲染时按实际分辨率缩放字号与 `cn_y` / `en_y`

## 桌面字体

全界面同一套栈：微软雅黑 UI → Segoe UI Variable → Segoe UI → 苹方。字阶只有五档：标签 12、提示/日志 13、控件 14、标题 20、进度 32。勾选、主按钮、色块也走 `type_font()`。
