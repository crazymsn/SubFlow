# 贡献 SubFlow 语幕

感谢帮助改进字幕、配音和跨平台体验。当前发布为 **1.3.60**；先阅读 [架构](docs/architecture.md) 和 [已知验收边界](docs/release-1.3.60.md)，问题反馈使用 [Issues](https://github.com/crazymsn/SubFlow/issues)。

## 开发环境

推荐 Python 3.11，并安装支持字幕滤镜的 FFmpeg 6+。克隆后创建并激活独立虚拟环境，步骤见 [安装指南](docs/install.md)，然后：

```bash
python -m pip install -e ".[gui,dev]"
ruff check src tests scripts
python -m pytest -q
```

pytest 默认检查 `bilingual_sub.core` 覆盖率，门槛为 80%。不要通过降低门槛、跳过有效用例或替换实现为桩来掩盖失败。可先运行与修改相关的用例，再完成发布流程要求的检查。

类型检查可补充使用 `mypy src/bilingual_sub --ignore-missing-imports`；应使用与开发环境相符的 Python 类型版本并说明检查范围。当前发布工作流要求 Ruff 与 pytest，通过这些检查不代表真实设备性能或所有模型路径均通过。

## 修改与验证

在功能分支提交 PR，清楚说明问题触发条件、修复后的行为和验证证据。保持改动集中，避免在修复过程中重排无关文件。

- 语种规则：中文原片输出简体 / 繁体目标应保留原声；中英字幕仍需翻译英文行。
- 路径与缓存：验证输入不会被覆盖，取消或异常不会提交不完整结果，并考虑多任务占用。
- 外部进程：复用已有生命周期、取消和输出捕获机制，不能遗留测试启动的服务。
- UI：检查窗口初始化、常驻的语音识别与翻译设置、配音和任务控制；需要真实交互时补充实机检查。
- Apple GPU：区分 MPS 编译支持、实际计算、CPU 回退和完整视频验收。
- GPT-SoVITS：按变更范围运行 `python scripts/check-sovits-audio.py`，需要实际模型时说明设备和权重准备情况。

## 测试数据与仓库内容

回归用例优先使用合成输入，临时媒体写入 pytest `tmp_path`。有效测试代码属于项目内容；真实视频、私人转写、参考音频、临时日志和本机安装环境不提交到仓库。

`build/`、`dist/` 和运行缓存属于本机产物。清理前核实用途，保留当前客户端、模型、词典和依赖；GPT-SoVITS 的 `TEMP/ja` 可能存放运行词典。目录链接应只处理链接本身，不能递归清理目标。

API Key、Cookie、`.env` 和凭据文件不得出现在提交、测试样本、日志或发布包中。环境配置用占位值，报告分享前检查敏感内容。

## 构建与发布

工作流定义在 [.github/workflows/release-clients.yml](.github/workflows/release-clients.yml)：

1. Windows x64、Mac arm64 / x64 分别运行测试、准备推理环境、构建并检查客户端。
2. Linux amd64 / arm64 原生构建 Docker，检查 CLI、运行环境、音频及宿主机绑定目录读写。
3. 所需检查通过后合并并发布 Docker 多架构标签；版本标签构建可发布客户端 `.7z.*` 分卷。

Docker Hub 凭据通过 GitHub Actions Secrets 提供：`DOCKERHUB_USERNAME`、`DOCKERHUB_TOKEN`。密钥不写入工作流或文档。

若客户端验收已经通过、只有 Release 上传中断，先重跑失败的发布任务。也可手动运行 [Recover client publication](.github/workflows/publish-clients.yml)，填写原构建的 `source_run` 和版本 `tag`。它核对标签对应的提交、包版本和三平台验收，复用原工作流附件；逐一上传分卷，跳过哈希一致的已有文件，仅清理草稿中的未完成上传，拒绝覆盖内容冲突的文件。全部文件的大小和 SHA-256 校验通过后才公开 Release。原附件保留三天，过期后需要重新构建；不要移动已发布标签。

完整 Windows 包使用 `scripts/build-windows.ps1`，Mac 使用 `scripts/build-macos.sh`。完整包内置三种配音模式的模型，以及四套可迁移的识别/配音环境；所选识别模型按需下载。`-SourceOnly` 仅构建需要首次联网安装环境的 Windows 开发包。推理环境放在独立的 `offline` 目录，不混入 Qt 的 `_internal`。Mac 构建成功后按 [实机验收手册](docs/mac-self-test.md) 检查真实设备与完整视频流程。

仅改文档且无需构建时，可在提交信息中使用 `[skip ci]` 避免重复客户端和镜像发布；先检查 Markdown 链接、示例参数、版本和事实。不要移动已发布的版本标签来覆盖相同版本的二进制内容。

完整打包步骤见 [安装指南](docs/install.md)。项目代码使用 MIT；修改第三方代码时保留对应许可与来源说明。
