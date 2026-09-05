# Changelog

## 1.2.5 — 2026-09-05

- 配音音色旁可试听；样句跟目标语种，与字幕样式无关
- 目标语种为 English 时按目标语种配音，不再因 ASR 误判成英文而留下中文原声
- 配音失败会报错，不再静默交出原声成片
- 导出文件名跟随字幕样式：英中为 `-英中字幕`，中英为 `-中英字幕`

## 1.2.4 — 2026-09-05

- YouTube 站点罐只要有 `SID` / `__Secure-3PSID` / `LOGIN_INFO` 即视为已登录，不再因缺少旧版 SID 族而跳过
- 更新仓库内 `Cookies/youtube-cookies.txt` 与 `Cookies/bilibili-cookies.txt`（仅 YouTube/Google 与 B 站域名）

## 1.2.3 — 2026-09-05

- 打包版会沿 `dist/SubFlow` 向上查找项目 `Cookies\`，B 站登录 Cookie 不再只认 exe 同级目录
- 拒绝只有访客字段的 `youtube-cookies.txt`；YouTube 启用 node/deno JS runtime
- Chrome 未运行时可用调试端口读取登录 Cookie；Chrome 127+ v20 加密库不再假装能直接读
- 下载失败时回传真实原因（机器人检测 / 412），不再一律报「无法下载最高清」

## 1.2.2 — 2026-09-05

- 中英 / 英中字幕每种语言最多 1 行；超长句缩放进安全框，不再折成多行
- 目标语种为简体时，中文轨强制转简体（修复 Whisper 默认繁体）
- YouTube / Bilibili 下载优先原声音轨，避免英文自动配音
- 源语种、目标语种、字幕样式职责拆开，互不覆盖
- 重写 README 与桌面 / 安装 / 架构 / 故障排除文档
- OpenCC 纳入主依赖，随 Win / Mac 客户端打包

## 1.2.1 — 2026-09-04

- Docker 官方镜像：`crazymsn/subflow:latest`（`docker-compose.yml` 默认拉取 Hub）
- 文档重写：字幕烧录颜色、浏览器 Cookie 兜底、BAAI 过滤、Win / Mac 发布包
- 自定义字幕颜色（桌面色块 + CLI `--zh-color` / `--en-color`）已随 1.2.0 落地，本版一并写进文档

## 1.2.0 — 2026-09-04

- 视频下载：游客失败后读取本机已安装浏览器登录 Cookie（Firefox / Edge / Safari / Chrome）
- 获取模型时屏蔽 BAAI / 智源相关条目
- 自定义字幕中英颜色；只改颜色时重渲 ASS 并重烧，不重跑识别
- GitHub Actions 按源码同时构建 Windows zip 与 macOS `.app` zip

## 1.1.0 — 2026-09-04

- 对外文案定为：SubFlow 语幕，新一代 AI 视频语音识别、自动翻译、字幕生成工具
- 重写 README 与 docs（桌面客户端、安装、令牌、故障排除、架构）
- 桌面客户端：浅色/深色纸面主题、统一微软雅黑 UI 字阶、开始栏输出路径
- 更多选项在甲板内展开，不再挡住开始栏
- 同视频只改输出路径时拷贝成品，不重跑流水线
- 勾选与按钮悬停使用同一套灯丝橙
- 发布 Windows onedir 客户端到 GitHub Releases

## 1.0.0 — 2026-09-04

- 产品名：语幕 SubFlow（深度云创科技）
- CLI：`subflow`（兼容 `bilingual-sub`）
- 保存 API 令牌后自动拉取模型列表
- Docker Compose 一键引擎
- Whisper / WhisperX、静音切句、meding 翻译、无底板烧录
- 七种界面语言；可选润色、术语、配音
- Win / Mac 客户端构建脚本与 Actions 工作流
