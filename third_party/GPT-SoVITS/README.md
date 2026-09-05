# GPT-SoVITS（SubFlow 内置运行时）

官方仓库：<https://github.com/RVC-Boss/GPT-SoVITS>

语幕把该仓库放在本目录。启动 `SubFlow.exe` / `subflow gui` 会自动执行 `api_v2.py`（`127.0.0.1:9880`），配音不再走 OpenAI `tts-1`。

## 本机还需要

1. 按官方 `install.ps1` / `install.sh` 安装 Python 依赖（conda / 整合包 / `SUBFLOW_GPTSOVITS_PYTHON`）
2. 下载预训练权重到 `GPT_SoVITS/pretrained_models/`（不要提交 `.pth` / `.ckpt`）
3. 可选：设 `SUBFLOW_GPTSOVITS_HOME` 指向已有整合包（含 `runtime/python.exe` 的会被优先发现）

`scripts/setup-gptsovits.ps1` 在本目录缺失 `api_v2.py` 时会再拉一次官方源码。

官方客户端 **不把 Torch 打进 exe**。打包时 `scripts/build-windows.ps1` 会把本目录源码拷到 `dist\SubFlow\GPT-SoVITS`（排除 `.git` / `venv` / 权重）。
