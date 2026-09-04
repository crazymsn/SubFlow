# 架构

## 模块图

产品：**语幕 SubFlow**（深度云创科技）。CLI 入口 `subflow`。

保存 API Key 后调用 `GET /v1/models` 填充可选翻译模型。

```
CLI / GUI / Docker → pipeline.run
  ├── core.audio      (extract, silencedetect)
  ├── adapters.whisper
  ├── core.cues + glossary
  ├── core.translate → adapters.meding + secrets
  ├── core.render
  └── core.burn → adapters.ffmpeg
```

## JobConfig 字段

| 字段 | 说明 |
|------|------|
| `input_video` | 输入视频 |
| `output_video` | 烧录 MP4（`burn=false` 时可空） |
| `output_srt` | 输出 SRT |
| `work_dir` | 工作目录，`auto` = `%TEMP%/bilingual-sub/<id>` |
| `style_preset` | 样式 preset 名 |
| `whisper_model` | Whisper 模型 |
| `device` | `auto` / `cuda` / `cpu` |
| `burn` | 是否烧录 |
| `resume_from` | 从某阶段继续 |
| `preview_minutes` | 仅处理前 N 分钟 |

## 扩展点

- **新 preset**：`config/presets/*.yaml`
- **glossary**：`--glossary` 或项目 `bilingual-sub.yaml`
- **替换翻译后端**：fork 并改 `adapters/meding.py`（官方不支持改 Base URL）

## 依赖规则

- `core/*` 不依赖 `cli` / `gui`
- `MEDING_BASE_URL` 硬编码于 `adapters/meding.py` 一处
- 样式按 2560×1600 设计，渲染时按实际分辨率缩放字号与 `cn_y`/`en_y`，任意宽高比视频字幕都在画面内
