# SubFlow 语幕 1.3.46 发布验收

[返回文档索引](README.md) · 发布日期：2026-09-06

## 可下载产物

[GitHub Release](https://github.com/crazymsn/SubFlow/releases/tag/v1.3.46) 提供：

| 文件 | 用途 |
| --- | --- |
| `SubFlow-Windows-x64.zip` | Windows 10/11 x64 客户端 |
| `SubFlow-macOS-arm64.zip` | Apple Silicon，macOS 14+ |
| `SubFlow-macOS-x64.zip` | Intel Mac，macOS 15+ |
| `SHA256SUMS` | 三个 ZIP 的 SHA-256 校验值 |

客户端构建源码提交为 [84925365](https://github.com/crazymsn/SubFlow/commit/84925365f7b8b7512e912895d3e82a846efc0380)，`v1.3.46` 指向此提交。后续仅文档更新不会改变该版本客户端内容。GitHub Releases 和版本标签目前仅保留 1.3.46，源码提交与历史变更记录保留用于追溯。

ZIP 已检查归档完整性、对应平台入口及版本，发布后的 GitHub 资产摘要与校验文件核对一致。社区包通过首次联网安装准备推理依赖及模型，不能按完全离线安装包使用。

## 自动检查

[本次完整工作流](https://github.com/crazymsn/SubFlow/actions/runs/34005160660) 结论为成功：

| 平台 / 作业 | 结果及范围 |
| --- | --- |
| Windows x64 | 1292 项测试通过、3 项跳过；依赖准备、打包和冻结客户端检查通过 |
| macOS arm64 | 1289 项通过、6 项跳过；依赖准备、打包和客户端检查通过 |
| macOS x64 | 1289 项通过、6 项跳过；依赖准备、打包和客户端检查通过 |
| Linux 进程生命周期 | 通过 |
| Docker amd64 / arm64 | 原生构建、CLI、依赖、音频及绑定目录读写检查通过 |
| Docker 发布 | 多架构标签合并并推送成功 |

上述 main 分支工作流的标签发布作业按条件跳过；客户端 Release 使用同一成功运行的产物发布。相同提交的重复标签构建已取消，不应将其当作另一轮验收失败。

本地 Windows 完整构建另行检查了冻结客户端启动、中文简繁免配音规则、CPU Torch 运算和携带模型的配音服务加载。该本机完整包与 GitHub 首次安装模式不同。

## Docker 发布

[Docker Hub](https://hub.docker.com/r/crazymsn/subflow) 的 `1.3.46` 和发布时的 `latest` 包含 Linux `amd64`、`arm64`，使用 CPU。发布时多架构 manifest 摘要：

```text
sha256:299c459119eb31fd114b90bbb2ab2110ae60630bd887f13de5c1a9e18e31d1bb
```

`latest` 可随未来发布变化，需要稳定部署时使用版本标签或摘要。首次识别 / 配音仍可能下载模型，配置和权重保存在 Compose 命名卷；详见 [部署指南](docker.md)。

## 已验证范围与限制

- 自动测试通过不等于完整项目不存在缺陷，也不代替用户对成片、字幕准确度及配音自然度的试听审看。
- Apple 托管构建机支持安装 MPS 依赖，但实际 GPU 分配失败，报告为 `gpu_usable=false`、`gpu_verified=false`。没有将其计为 Apple GPU 实机推理通过。
- M1 MacBook Air 的完整识别、配音和性能验收尚待实机执行，步骤见 [M1 清单](mac-self-test.md)。
- Docker 验收使用 Linux CPU，不宣称在 Docker 内支持 Apple MPS。
- 更多历史修复及未完成范围见 [代码审查进度](code-audit-status.md)。
