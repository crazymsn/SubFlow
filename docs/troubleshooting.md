# 故障排除

| 现象 | 原因 | 处理 |
|------|------|------|
| 字幕不显示 | fontsdir 错误或字体缺失 | 检查 `fonts/` 目录；运行 `doctor` |
| 烧录失败（中文路径） | ffmpeg subtitles 滤镜路径问题 | 工具会自动 copy 到 ASCII workdir |
| 音画时长变短 | 误设 fps 滤镜 | 本工具禁止改帧率，保持 `-c:a copy` |
| 英文空白 | API 失败 | 查看 `report.json` 的 `missing_en_samples` |
| 字幕太小/太大 | preset 不匹配 | `--preset no-plate-large` 或编辑 yaml |
| doctor 报 whisper 缺失 | 未装 cuda 可选依赖 | `pip install bilingual-sub[cuda]` |
| 401 / API key | Key 无效或未配置 | `bilingual-sub config set-api-key` |
| 字幕出画 / 只在 2560×1600 正常 | 旧版写死坐标 | 已按帧高缩放；换 preset 或升级版本 |
| 无音轨 | 视频没有音频 | 工具会报错退出，需有语音轨 |

## 退出码

| Code | 含义 |
|------|------|
| 0 | 成功 |
| 1 | 输入错误 |
| 2 | 环境不满足 |
| 3 | API Key 问题 |
| 4 | 处理中断 |
| 5 | 部分成功（有 missing_en） |
