# 故障排除 — SubFlow 语幕

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 双击 exe 报找不到 Qt / DLL | 只复制了 exe，或缺少 VC++ 运行库 | 整夹启动；安装 [VC++ 2015–2022 x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) |
| 启动即 WinError 127 | 包内误带了外来 ICU DLL | 官方构建脚本会删掉 `_internal/icu*.dll`；请用 Releases 包或重新 `build-windows.ps1` |
| 点开始提示「请先选择视频」 | 未拖入文件且未完成链接下载 | 拖入视频，或粘贴链接后先点「下载」 |
| 提示需要令牌 / 模型 | 未保存 Key 或未拉取列表 | 保存令牌后点「获取模型」并选中一项 |
| 列表里没有 BAAI 模型 | 产品会屏蔽 BAAI / 智源条目 | 属预期，换其它翻译模型 |
| YouTube 提示登录 / 不是机器人 | 游客客户端被拦 | 用 Firefox 或 Edge 登录 youtube.com 后再点下载；Chrome 正在运行时可能读不到 Cookie |
| B 站 412 / 风控 | 访客请求被拦 | 用已登录的浏览器打开 bilibili.com 后再试 |
| 输出路径不能和原片相同 | 会覆盖源文件 | 换一个文件名或文件夹 |
| 改了颜色却重跑识别 | 同时还改了视频或其它会失效缓存的项 | 只改色块、不换片时才会从 render 续跑 |
| 识别很慢 / 内存暴涨 | `large` 模型 + CPU | 改用 `small` / `medium`，或装 CUDA 后走源码 `[cuda]` |
| 日志出现回退 Whisper | 本机没有可用的 WhisperX runtime | 属预期；要词级对齐需单独准备 WhisperX |
| 字幕不显示 | fontsdir 错误或字体缺失 | 检查 `fonts/`；运行 `subflow doctor` |
| 烧录失败（中文路径） | ffmpeg subtitles 滤镜怕非 ASCII | 工具会拷到 ASCII 工作目录再烧 |
| 音画时长变短 | 误改帧率 | 本工具禁止改 fps，音频 `-c:a copy` |
| 英文空白 | 翻译 API 失败 | 看作业 `report.json` 的 `missing_en_samples` |
| 字幕太小 / 太大 | preset 不匹配分辨率 | `--preset no-plate-large` 或改 yaml；字号按帧高缩放 |
| 字幕出画 | 旧版写死 2560×1600 坐标 | 升级后已按画面缩放，换 preset 即可 |
| doctor 报 whisper 缺失 | 未装识别依赖 | `pip install -e ".[cuda]"` 或 `docker pull crazymsn/subflow:latest` |
| 401 | Key 无效或未配置 | `subflow config set-api-key`；Docker 检查 `.env` |
| 429 / 5xx | 配额或服务端抖动 | 客户端会按 1s / 2s / 4s 重试三次 |
| 无音轨 | 视频没有音频 | 工具报错退出，需有语音轨 |
| 无网不能翻译 | 翻译走 meding | 可对已译作业 `--resume-from render` |
| `docker compose` 仍本地构建 | 本机没有 `crazymsn/subflow:latest` | 先 `docker compose pull`，或保留 `pull_policy: missing` 后的首次构建 |

## 退出码

| Code | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 输入错误 |
| 2 | 环境不满足 |
| 3 | API 令牌问题 |
| 4 | 处理中断 |
| 5 | 部分成功（存在 missing_en） |
