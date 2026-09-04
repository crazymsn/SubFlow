# Changelog

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
