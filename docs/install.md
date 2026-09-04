# 安装 — 语幕 SubFlow

## Docker Compose

```bash
cp .env.example .env
# SUBFLOW_API_KEY=你的key
docker compose build
docker compose run --rm subflow doctor
docker compose run --rm subflow models
```

输入输出都在 `./data`：

```bash
docker compose run --rm subflow run /data/in.mp4 -o /data/out.mp4 --model <模型id>
```

Whisper 权重缓存在 named volume `whisper-cache`。

## Python

```bash
pip install -e ".[cuda,gui,dev]"
subflow doctor
```

## 桌面客户端

- Windows：`scripts/build-windows.ps1` → `dist/SubFlow/SubFlow.exe`
- macOS：`scripts/build-macos.sh` → `dist/SubFlow.app`

客户端自带 GUI。识别引擎优先用本机 Whisper；也可用同一仓库的 Docker Compose 做批量处理。

## 离线

无网时不能拉模型、不能翻译；可对已翻译作业 `--resume-from render`。
