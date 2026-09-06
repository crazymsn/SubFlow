# M1 MacBook Air 自行验收

最终实机测试由用户自行执行。代码和 CI 的检查不代表下面项目已经通过；请记录实际结果。当前 arm64 客户端构建面向 macOS 14 及以上，先在「关于本机」确认系统版本。

## 安装与首次启动

1. 从本次提交对应的 GitHub Actions 构建下载 `SubFlow-macOS-arm64`，解压其中客户端 ZIP，将 `SubFlow.app` 放到「应用程序」。M1 使用 arm64 包。
2. 打开应用。当前构建未做 Apple 公证，如系统拦截，在「系统设置 → 隐私与安全性」允许这次打开。
3. 首次联网等待 Python、推理依赖和模型准备完成。无需预先安装 Python、Homebrew 或 CUDA。启动日志应说明准备进度；下载失败应显示原因，重新启动后可以重试。
4. 记录 macOS 版本、内存容量、客户端版本。首次下载时间和后续推理时间分开记录。

准备一个含清晰中文人声的短视频作为固定测试片，每项使用独立输出目录。先用默认 Whisper 引擎和 `base` 模型完成短片测试，再按实际需要测试 `small` / `medium` 及长视频。这里的模型选择仅用于控制验收规模，不是性能保证。

## 必测场景

| 场景 | 操作 | 通过条件 |
| --- | --- | --- |
| 简体字幕保留原声 | 中文源片，目标简体中文，处理并导出 | 原中文人声保留；不发起本次视频的合成配音；无配音失败或长文件名弹窗 |
| 繁体字幕保留原声 | 同一中文源片，目标繁体中文 | 字幕使用繁体、原声保留；无本次视频的合成配音 |
| Apple GPU 识别 | 查看上述任务工作目录的 `whisper.log` | `MODEL_LOADED device=mps`，末尾成功行也包含 `device=mps`；只看到起始设备不够 |
| 跨语言配音 | 中文源片，目标 English，配置可用翻译接口；使用清晰、文字对应的参考音频 | 完成识别、翻译、英文配音及成片；试听有实际英文人声，时序可接受，不是保留中文音轨或静音 |
| 单行字幕与完整配音 | 使用有较长句子的中文短片，目标 English，选择单行字幕并配音 | 单行字幕保留全部英文译文；配音没有重复整句；检查任务 `report.json` 中的 `subtitle_fit_warnings`，存在记录时对照相应字幕检查阅读速度或显示时长 |
| 配音实际设备 | 跨语言配音前后查询下面的本机接口 | `device` 保持 `mps`、`is_half` 为 `false`；如变成 `cpu`，记录为回退成功，不计 GPU 配音通过 |
| 再次启动 | 退出后重新打开，重复短片 | 使用已准备的依赖和资源，不重复完整安装；功能正常 |
| 试听退出与恢复 | 试听开始后退出客户端，再次打开并试听 | 退出时声音停止，没有遗留播放器；再次试听正常，结束后按钮恢复可用 |
| 任务控制 | 运行短片时暂停、继续、停止，再启动新任务 | 状态恢复正常；停止后能启动下一任务；已有成片和原片保持完整 |

服务随客户端启动属于环境准备；中文同语种任务保留原声，并不要求后台服务必须关闭。跨语言翻译需要用户自己的有效接口配置；接口鉴权失败应作为接口问题记录。

简体、繁体原声场景各用「源语言：中文」和「源语言：自动识别」重复一次。自动识别后查看任务 `report.json`：`detected_spoken` 应为 `zh`、`dubbed` 为 `false`、`tts_provider` 为 `none`。选择单语中文字幕时，`translated` 也应为 `false`；双语字幕仍需要翻译其中的英文行。

## 检查与保存证据

保持客户端运行，在 macOS「终端」执行以下命令。默认本机服务使用 9880 端口；如果你修改过端口，应使用对应的本机地址。

```bash
QA_DIR="$(mktemp -d "$HOME/Desktop/SubFlow-M1-QA.XXXXXX")"
sw_vers > "$QA_DIR/system.txt"
uname -m >> "$QA_DIR/system.txt"
sysctl -n hw.memsize >> "$QA_DIR/system.txt"
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:9880/subflow/runtime > "$QA_DIR/runtime-before.json"
printf '证据目录：%s\n' "$QA_DIR"
```

跨语言配音完成后，在同一个终端窗口执行：

```bash
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:9880/subflow/runtime > "$QA_DIR/runtime-after.json"
if [ -f "$HOME/.config/subflow/gptsovits.log" ]; then
  cp "$HOME/.config/subflow/gptsovits.log" "$QA_DIR/gptsovits.log"
fi
open "$QA_DIR"
```

若请求失败，保留终端错误并检查客户端准备日志，不能把空 JSON 当成功。将每次测试工作目录中的 `whisper.log` 分别复制到证据目录并注明场景。界面进度、成片试听、耗时与是否出现 CPU 回退也一起记录。日志可能包含本机路径或视频文本，分享前检查内容；不需要提供 API 密钥、完整配置或私有视频。

## 单独确认 CPU 可运行

完整退出客户端，在终端启动一次 CPU 配置：

```bash
SUBFLOW_TORCH_BACKEND=cpu SUBFLOW_GPTSOVITS_DEVICE=cpu \
  /Applications/SubFlow.app/Contents/MacOS/SubFlow
```

重复短片识别和跨语言配音，检查 `whisper.log` 和服务接口均报告 `cpu`，成片可正常播放。随后退出该实例，再从「应用程序」正常启动，恢复默认自动选择。CPU 明确选择成功与 GPU 异常时自动回退是两项不同证据；无需人为破坏 GPU 环境来测试自动回退。

若自行配置过 ASR 的明确设备覆盖，CPU 测试时应先恢复 `auto` 或改为 `cpu`。Apple GPU 仅用于原生 arm64 客户端；Mac 上 Linux Docker Compose 的验收使用 CPU。WhisperX 也不作为本次 MPS 识别测试引擎。

可选的源码组件探测命令及其覆盖边界见 [Apple GPU 验收记录](apple-gpu-qa-2026-09-05.md)。无需为上述客户端验收安装开发环境。
