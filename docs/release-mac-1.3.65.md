# SubFlow 1.3.65 · macOS

[下载 Mac 客户端](https://github.com/crazymsn/SubFlow/releases/tag/mac-v1.3.65) · [安装及 Cookies](mac-install-cookies.md) · [详细验收](qa-1.3.65-mac-startup.md)

本次发布 macOS 客户端及其源码。Windows 客户端和 Docker 镜像继续使用原有 1.3.60 发布，不将其标为本次验收版本。

## 选择安装包

| 电脑 | 文件前缀 | 推理方式 | 系统 |
| --- | --- | --- | --- |
| Apple M 系列 | `SubFlow-1.3.65-Apple-M-arm64.dmg` | MPS / CPU | macOS 14+ |
| Intel Mac | `SubFlow-1.3.65-Intel-x86_64.dmg` | CPU | macOS 14+ |

两个完整客户端均包含离线配音模型和四套运行环境。GitHub 单文件必须小于 2 GiB，因此每个 DMG 按原始字节拆为四卷 `.001`–`.004`，每卷最多 1900 MiB。它们不是 7z 压缩包。

1. 下载对应芯片的全部四卷，以及 `SHA256SUMS` 和 `Merge-SubFlow-DMG.command`，放在同一文件夹；无须下载另一种芯片的四卷。
2. 打开“终端”，输入 `bash `，将 `Merge-SubFlow-DMG.command` 拖到终端，再补上 ` arm64`（Apple M）或 ` x86_64`（Intel），按回车。脚本会自动使用它所在的下载文件夹。
3. 脚本校验各卷、合并、校验完整 DMG；已有不同内容的 DMG 会保留，不会被覆盖。合并需额外约 7–8 GB 空间，安装应用另需约 12–15 GB。
4. 打开生成的 DMG，将 `SubFlow.app` 拖到 Applications。复制完成后推出映像，从“应用程序”启动。升级前退出旧客户端。

也可在下载目录执行以下命令之一：

```bash
bash Merge-SubFlow-DMG.command arm64
bash Merge-SubFlow-DMG.command x86_64
```

| 完整 DMG | 字节数 | SHA-256 |
| --- | ---: | --- |
| Apple M | 7113685593 | `58a5dc9653c155a01fd7af032f4525633b67b3f4a02cc7ead5e3464ef020d85e` |
| Intel | 7534633656 | `f38c61ffc212bd69d58287edf0a96d8da8037547acc5c2615744eb533b671e85` |

## 修复及验证

- 优化 Mac 圆角、透明边缘、留白及完整 ICNS 尺寸，小尺寸使用简化图形。
- 修复 Mac 启动读取 API Key 时的钥匙串密码弹窗；显式保存、清除密钥仍遵循系统授权。
- 内置 Node.js / EJS，并将随包 FFmpeg 路径传给下载器，修复 Finder 启动后的下载与音视频合并。
- 正确读取 Netscape Cookies 的 `#HttpOnly_` 行，提供 Mac 路径与纯文本提示。
- 修复 MPS 注意力、长音频卷积、Qwen 抽样，以及离线运行环境和应用内部链接打包问题。
- 1.3.65 的 180 项专项回归通过。两架构 DMG 均完成只读挂载启动、原生架构、内部链接、深度严格签名，以及冻结程序的 4K 分离音视频下载合并验证。
- Apple M 在物理 M1 上实测。Intel 在同一 M1 上通过 Rosetta 执行 x86_64 程序，尚未在物理 Intel Mac 上验收。1.3.61 的识别、翻译、配音和导出，以及 1.3.63 的真实 YouTube 下载属于前版结果，具体范围见验收文档。

客户端使用本地临时签名，未做 Apple 公证。首次系统安全检查仍由 macOS 决定；这是与启动读取钥匙串不同的授权。API Key 和真实 Cookies 不随源码或客户端发布。

## 从源码构建

使用 macOS、目标架构 Python 3.11+、FFmpeg/ffprobe 和 Node.js 22+；Node.js 发行目录须保留其 `LICENSE`。运行 `bash scripts/build-macos.sh` 生成应用。构建依赖隔离在 `build/macos-build-env`，模型和运行环境默认完整打包。Intel 使用 x86_64 Python；在 Rosetta 下构建时显式设置 `SUBFLOW_TARGET_ARCH=x86_64`。

运行 `python scripts/build-dmg.py --help` 查看 DMG 构建与只读挂载验收参数。模型体积较大，建议为完整构建预留至少 40 GB 可用空间。`scripts/merge-macos-dmg.sh` 是发布附件合并脚本的源码。

本次使用 `mac-v1.3.65` 标签，避免触发面向 Windows、Mac 和 Docker 的 `v*` 全平台发布流程。原有全平台 Latest 发布保持不变。

GitHub 拒绝了本次令牌对 Actions 工作流的修改，因此现有 `.github/workflows/release-clients.yml` 保持原样。Node.js 准备、Mac 链接保留及解压后自检的工作流改动保存在 [补丁](patches/mac-release-workflow.patch) 中；具备工作流写入权限的维护者可用 `git apply docs/patches/mac-release-workflow.patch` 应用。上述本地 Mac 构建脚本及已验收客户端不依赖该补丁。
