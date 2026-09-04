# Contributing

## 分支策略

- `main` 受保护，功能在 feature 分支开发
- PR 需通过 CI 检查清单

## 本地开发

```bash
pip install -e ".[cuda,gui,dev]"
ruff check src tests
ruff format --check src tests
pytest --cov=bilingual_sub.core --cov-report=term-missing
mypy src/bilingual_sub
```

## PR 检查清单

- [ ] `ruff check` + `ruff format --check`
- [ ] `pytest` 全绿；`core/` 行覆盖率 ≥ 80%
- [ ] 无硬编码用户路径
- [ ] 无 API Key 出现在代码/测试/日志
- [ ] `MEDING_BASE_URL` 仅出现于 `adapters/meding.py`
- [ ] 新增外部命令经 `adapters/ffmpeg.py`

## 架构约束

- `core/*` 不得 import `cli` / `gui`
- `adapters/*` 不得 import `core/cues`
- `secrets.store` 不得写日志明文 Key
