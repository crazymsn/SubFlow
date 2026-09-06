# Docker Compose 部署

[返回文档索引](README.md) · 适用于 **1.3.60**

官方镜像：[crazymsn/subflow](https://hub.docker.com/r/crazymsn/subflow)。支持 Linux `amd64` / `arm64`，均使用 CPU；无需显卡。Mac 的 Docker 运行 Linux 容器，Apple GPU 请使用原生 arm64 客户端。

## 1. 准备部署目录

宿主机需要可用的 Docker Engine / Docker Desktop 和 Compose v2。获取仓库：

```bash
git clone https://github.com/crazymsn/SubFlow.git
cd SubFlow
```

也可从 GitHub 下载源码 ZIP 并解压。只使用镜像时，目录内有 [docker-compose.yml](../docker-compose.yml)、[.env.example](../.env.example) 和 `data/` 即可，无需安装 Python 或下载客户端。

macOS / Linux：

```bash
cp .env.example .env
mkdir -p data
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force data
```

已有 `.env` 时继续使用原文件。只有需要字幕翻译时才必须填写 `SUBFLOW_API_KEY`。默认字幕样式是中英双语，包含英文翻译；中文单语示例无需令牌。

## 2. 拉取并检查

```bash
docker compose pull
docker compose run --rm subflow doctor
```

Compose 默认使用 `crazymsn/subflow:latest`，Docker 自动选择本机架构。镜像包含 FFmpeg，以及 Whisper、WhisperX、Qwen、GPT-SoVITS 四套推理依赖；首次使用对应识别或配音模型时仍需下载权重。`doctor` 检查环境，部分识别路径会尝试加载 tiny 模型并触发下载，但不代表已完成视频推理或配音验收。

## 3. 处理视频

把输入文件放在宿主机 `data/input.mp4`。容器内用 `/data/input.mp4`，不要直接填写 Windows 盘符路径。

中文单语字幕，保留原声：

```bash
docker compose run --rm subflow run /data/input.mp4 -o /data/output.mp4 --source-lang zh --target-lang zh --subtitle-mode single:zh --whisper-model base --device cpu
```

繁体中文将目标改为 `--target-lang zh-Hant`，样式改为 `--subtitle-mode single:zh-Hant`。源语言仍可使用 `zh`。

需要中英字幕时，先配置令牌，再查看可用翻译模型：

```bash
docker compose run --rm subflow models
docker compose run --rm subflow run /data/input.mp4 -o /data/output-bilingual.mp4 --whisper-model base
```

可在 `.env` 设置 `SUBFLOW_TRANSLATE_MODEL`，或传入 `--translate-model` 指定模型列表中的 ID。`--whisper-model` 选择本地识别模型，与翻译模型不同。

需要跨语种配音时，例如中文转英文，增加 `--target-lang en --dub --tts-provider qwen3-native --tts-voice Aiden`。首轮需准备 Qwen 模型，CPU 合成可能耗时较长。中文转简体或繁体始终保留原声，`--dub` 不覆盖此规则。

成品保存在宿主机 `data/`；输入输出必须使用不同文件名。每次命令创建一个任务容器，完成后自动删除容器，保留数据和命名卷。无需执行 `docker compose up -d`，也无需公开 9880 配音端口。

## 配置项

在 `.env` 设置后，对新启动的任务生效：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `SUBFLOW_IMAGE` | `crazymsn/subflow:latest` | 默认跟随最新发布；稳定部署可固定为 `1.3.60` |
| `SUBFLOW_API_KEY` | 空 | 翻译鉴权；不写入镜像 |
| `SUBFLOW_TRANSLATE_MODEL` | 空 | 翻译模型 ID |
| `SUBFLOW_CPU_THREADS` | `4` | OpenMP / MKL 线程数，并非容器 CPU 硬配额 |
| `SUBFLOW_GPTSOVITS_TIMEOUT` | `1800` | 配音请求等待秒数，应为正数 |
| `HF_ENDPOINT` | `https://huggingface.co` | 模型下载端点 |

启动前可用 `docker compose config --quiet` 检查配置。不要把展开的完整 Compose 配置贴到公开 Issue，其中可能含环境变量密钥。

## 数据与缓存

| 容器路径 | 持久化方式 | 内容 |
| --- | --- | --- |
| `/data` | 宿主机 `./data` | 输入、成品和显式保存在其中的工作目录 |
| `/root/.cache/whisper` | `whisper-cache` | Whisper 模型 |
| `/root/.cache/bilingual-sub` | `subflow-cache` | 翻译缓存、任务占用登记等 |
| `/root/.cache/huggingface` | `huggingface-cache` | 模型下载缓存 |
| `/opt/GPT-SoVITS/GPT_SoVITS/pretrained_models` | `sovits-models` | 配音模型 |
| `/opt/GPT-SoVITS/GPT_SoVITS/text/G2PWModel` | `sovits-g2pw` | 中文语言模型 |
| `/opt/GPT-SoVITS/nltk_data`、`/opt/GPT-SoVITS/TEMP` | `sovits-nltk`、`sovits-language-cache` | 语言资源及词典 |
| `/opt/subflow/runtime/qwen3-native-0.6b`、`/opt/subflow/runtime/qwen3-tts-0.6b` | `qwen-native-models`、`qwen-models` | Qwen 标准音色和克隆权重 |
| `/root/.config/subflow` | `subflow-config` | 用户配置和交互保存的凭据 |

卷名实际带 Compose 项目前缀。更换部署目录或项目名可能创建另一套卷，从而重新下载模型。正常升级保留这些卷；`docker compose down -v` 会删除命名卷，不能作为日常更新命令。

若翻译失败，保留工作目录并在修复配置后增加 `--resume-from translate` 重跑同一任务，缓存有效时复用识别。若需要断点恢复，使用 `--work-dir /data/work-job1` 为任务保留独立工作目录；容器临时文件系统会随 `--rm` 删除。同一项目共用文件占用登记，多个任务不要写同一输出。自定义跨项目共享数据时，还需共享 `SUBFLOW_LOCK_DIR`、保持相同容器路径映射，并使用支持文件锁的存储。

默认启用进程回收、60 秒退出宽限、1 GB 共享内存和日志轮转。容器以 root 运行，去掉默认能力后仅保留写入宿主机绑定目录所需的 `DAC_OVERRIDE`；NAS 的只读挂载、ACL 或 NFS root squash 仍可能阻止写入。处理权限问题应检查该数据目录和存储配置。

## 更新与源码构建

更新时修改 `.env` 中的镜像标签，再执行 `docker compose pull`。正在运行的任务继续使用原镜像，新任务使用拉取后的镜像。当前版本验收信息见 [发布记录](release-1.3.60.md)。

从源码构建需要完整仓库，使用额外的覆盖文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build
docker compose -f docker-compose.yml -f docker-compose.build.yml run --rm subflow doctor
```

后续运行源码镜像也需保留两个 `-f` 参数。该覆盖文件使用本地构建策略；常规部署只使用主 Compose 文件即可。多阶段 Dockerfile 将编译工具留在构建阶段，最终镜像保留运行所需文件。

更多问题见 [故障排除](troubleshooting.md)。
