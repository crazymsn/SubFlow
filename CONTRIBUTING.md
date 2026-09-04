# 贡献 — SubFlow 语幕

## 分支

- `main` 为发布分支
- 功能在 feature 分支开发，PR 需通过 CI

## 本地

```bash
pip install -e ".[gui,dev]"
ruff check src tests
ruff format --check src tests
pytest tests/unit --cov=bilingual_sub.core --cov-report=term-missing -o addopts=
mypy src/bilingual_sub
```

`.verify/` 是本机截图与冒烟产物，不要提交。

## PR 检查清单

- [ ] `ruff check` + `ruff format --check`
- [ ] 相关单测通过；`core/` 行覆盖率门槛保持 80%（不要为过线改门槛）
- [ ] 无硬编码用户路径
- [ ] 无 API 令牌出现在代码 / 测试 / 日志
- [ ] `MEDING_BASE_URL` 仅出现于 `adapters/meding.py`
- [ ] 新增外部命令经 `adapters/ffmpeg.py`
- [ ] 桌面改动后核验开始栏不被更多选项挡住，进度仍是 `0%` 这种整数

## 架构约束

- `core/*` 不得 import `cli` / `gui`
- `adapters/*` 不得 import `core/cues`
- `secrets.store` 不得写日志明文 Key
- 官方 Windows spec **不要**打进 torch / whisperx / GPT-SoVITS
- 控件颜色与字号走 `gui/theme.py`，不要在组件里写死另一套字体
