# Mac 实机验收手册

[返回文档索引](README.md) · 1.3.61 本地修复构建（尚未发布到 GitHub） · Apple M / Intel

本手册重点面向你的 **M1 MacBook Air**，也提供 Intel Mac 的 CPU 分支。Windows 测试、源码测试、CI 成功都不能替代 Mac 实机验收。请按本手册记录实际结果；尚未执行的项目填“未测”，不要填“通过”。

## 1. 先确认拿到的是哪个版本

- 使用 1.3.61 完整 Mac 包及随包工具 `mac_acceptance.py`，不要使用旧版本验证本轮修复。
- M1 / M2 / M3 等 Apple M 设备使用 **arm64** 包；Intel 使用 **x64** 包。M1 不要使用 Intel 包或 Rosetta 启动。
- 完整包包含三个配音模式的模型、四套独立 Python 环境、FFmpeg 和 ffprobe。最终使用者无需安装 Python、Homebrew、pip 或 CUDA Toolkit。
- Whisper / WhisperX 所选识别模型和各语种对齐模型仍会按需下载；云端翻译需要网络与有效令牌。不要把“配音模型内置”理解为所有功能都可离线。
- 2026-09-07 已在 M1 / macOS 14.5 构建本地 1.3.61 arm64 完整包；实测范围、证据和剩余限制见 [本轮验收记录](qa-1.3.61-m1.md)。此版本尚未上传 GitHub；已有 Windows 包不能复制到 Mac 执行。

## 2. 测试前准备

1. 在“关于本机”记录芯片、内存、macOS 版本；插上电源。先关闭占用大量内存的软件，每次只跑一个任务。
2. 将完整 `SubFlow.app` 放到 `/Applications`。不能只复制内部可执行文件，也不要删掉 `Contents/Resources/offline`。
3. 完整分卷包必须收齐同平台所有 `.7z.001`、`.002` 等文件，再从 `.001` 解压。缺卷或解压报错时先解决包完整性问题。
4. 首次被系统拦截时，在“系统设置 → 隐私与安全性”允许打开可信来源的这份应用。不要关闭整机安全检查，也不需要 `sudo` 运行客户端。
5. 准备一段 **20–40 秒、清晰中文人声** 的测试视频，包含至少一个长句和一段停顿；另备一段 3–5 分钟的视频。每次导出使用新文件名，保留原片。
6. 另备一段你有权使用的 5–10 秒清晰参考人声及准确文字。仅克隆模式需要；Qwen 标准/设计音色不需要用户参考音频。
7. M1 Air 8 GB 先用 `tiny` / `base` 识别和短句试听；通过后再测试更大识别模型与长视频。记录交换空间和内存压力，不设未经实测的速度承诺。

在 macOS“终端”创建本次证据目录。后续命令在同一个终端窗口执行：

```bash
APP="/Applications/SubFlow.app"
QA_DIR="$(mktemp -d "$HOME/Desktop/SubFlow-Mac-QA.XXXXXX")"
sw_vers > "$QA_DIR/system.txt"
uname -m >> "$QA_DIR/system.txt"
sysctl -n hw.memsize >> "$QA_DIR/system.txt"
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$APP/Contents/Info.plist"
file "$APP/Contents/MacOS/SubFlow"
codesign --verify --deep --strict --verbose=2 "$APP" 2> "$QA_DIR/codesign.txt"
```

通过条件：应用架构与本机一致，当前 macOS 不低于 `LSMinimumSystemVersion`；签名完整性检查退出码为 0。最低系统版本以实际包的 Info.plist 为准，不仅看下载文件名。临时签名完整不等于 Apple 公证完成。签名失败先保留错误信息，不要直接修改包内文件来跳过检查。

## 3. 随包环境与计算检查

先退出 SubFlow。这一步不下载模型、不调用翻译接口、不改用户配置，也不执行真实配音；它检查包中四套解释器及代表性计算操作，包括不等头数注意力和超过 65536 采样点的音频卷积。

```bash
QA_PY="$APP/Contents/Resources/offline/runtimes/qwentts/bin/python3"
QA_SCRIPT="$APP/Contents/Resources/bilingual_sub/_data/bootstrap/mac_acceptance.py"
test -x "$QA_PY" && test -f "$QA_SCRIPT"
"$QA_PY" -I -B "$QA_SCRIPT" --app "$APP" --device auto --output "$QA_DIR/environment-auto"
```

如果 `test` 失败或提示文件不存在，当前不是包含检查工具的新完整包；不要转而随意选择系统 Python，也不要把旧包测试记为新版通过。

检查 `$QA_DIR/environment-auto/report.json`：

| 项目 | Apple M 系列要求 | Intel Mac 要求 |
| --- | --- | --- |
| `ok` | `true` | `true` |
| `gpu_components_verified` | `true` | `false`，这是正常结果 |
| 四项 `runtimes[].ok` | 都为 `true` | 都为 `true` |
| Whisper / Qwen / GPT-SoVITS `device` | `mps` | `cpu` |
| WhisperX `device` | `cpu` | `cpu` |
| 解释器 `machine` | `arm64` | `x86_64` |

任一检查失败，工具退出码为 1，并保留报告和对应日志。该报告中的 `product_acceptance` 始终为 `pending_manual_tests`：小型张量检查通过不代表真实模型、成片或音色听感已经通过。

Apple M 再执行一次 CPU 环境检查，输出到另一个新目录：

```bash
"$QA_PY" -I -B "$QA_SCRIPT" --app "$APP" --device cpu --output "$QA_DIR/environment-cpu"
```

应 `ok=true`、各引擎 `device=cpu`、`gpu_components_verified=false`。工具拒绝覆盖已有证据目录，重试时请换一个新目录名。

## 4. 打开客户端与界面检查

| 编号 | 操作 | 通过条件 |
| --- | --- | --- |
| UI-01 | 从应用程序启动 | 正常出现窗口，无依赖缺失弹窗；配音准备不要求重新下载全部模型 |
| UI-02 | 检查并点击顶栏“深度云创科技” | 1.3.56 左侧保留“SubFlow 语幕”，公司标题在顶栏中央；点击打开 `https://nav.meding.site`，字体一致且无乱码 |
| UI-03 | 不开始任务 | 1.3.56 保留等待状态、0% 和进度条；仅日志框内显示硬件检测及实际型号，M1 应显示 Apple M1。开始任务后框内切换为任务日志 |
| UI-04 | 查看“语音识别与翻译” | 设置始终展开，令牌、模型和识别选项可操作 |
| UI-05 | 调整到较小窗口，切换深浅主题和界面语言 | 设置可滚动，开始/暂停/继续/停止按钮可见，文字不重叠 |
| UI-06 | 切换八个目标语种 | 默认参考文本和试听文本跟随目标语种翻译；音色标注男女声、官方/设计来源 |

待机“检测到 GPU”只是硬件提示，不能单独作为 GPU 推理通过的证据。

## 5. 真实识别与中文原声

每项使用新输出名，在图形界面执行。短片完成后播放成片、查看字幕和任务工作目录的日志。

| 编号 | 设置与操作 | 必须满足 |
| --- | --- | --- |
| ASR-01 | 源：简体中文；目标：简体中文；单语中文字幕；Whisper `base` | 完成识别、字幕与导出；中文原声保留；不合成配音 |
| ASR-02 | 同片，目标改繁体中文；单语中文字幕 | 原声保留，字幕为繁体；没有配音失败弹窗 |
| ASR-03 | 源语言改自动识别，分别重复以上两项 | 报告检测语音为 `zh`，仍保留原声 |
| ASR-04 | Apple M 上检查 `whisper.log` | 加载行与最终成功行均报告 `device=mps`；只看到起始行不算通过 |
| ASR-05 | 改用 WhisperX，首次联网准备选定模型 | 完成识别，不能因十几秒冷启动误报不可用；Mac 实际设备为 CPU |
| ASR-06 | 再次处理同类短片 | 复用已有环境/模型缓存，不重复安装完整 Python 环境 |

WhisperX 使用 CTranslate2，**不支持 Apple MPS**。Apple GPU 识别请选择 Whisper。中文双语字幕仍需要翻译英文行；验证“不需要翻译令牌”时必须使用单语中文字幕。

## 6. 三种配音模式与八语种试听

先测试 Qwen 标准音色，然后克隆，最后 GPT-SoVITS；逐个切换，避免把其他服务的状态当作当前引擎。

| 编号 | 场景 | 通过条件 |
| --- | --- | --- |
| TTS-01 | Qwen 标准音色，English，官方 Aiden / Serena 等 | 有清晰英文人声，句子与默认试听内容对应；无截断、杂音或长时间静音 |
| TTS-02 | 选择法语 `SubFlow_fr_male` / `SubFlow_fr_female` | 两个音色都可试听，男女声标注正确；真实视频任务也保留所选音色 |
| TTS-03 | 按下表逐一切换目标语种并试听 | 文本、发音语言、音色来源标记正确；记录音调、语速与流畅度 |
| TTS-04 | Qwen 原声克隆，加载有权使用的参考音频与准确文字 | 成功生成目标语音，无“参考音频不存在”；试听后移动/删除用户临时参考文件时给出明确错误，不崩溃 |
| TTS-05 | GPT-SoVITS，用同一参考音频和准确文字 | 成功试听中/英文；如果界面按目标语种切换实际引擎，记录实际引擎，不能算 GPT 原生支持该语种 |
| TTS-06 | 官方音色 → 设计音色 → 官方音色 | 三次均可播放，服务没有沿用错误模型，设备状态可信 |
| TTS-07 | 试听中停止或退出，重新启动再试听 | 无残留播放；按钮能恢复，下一次试听正常 |

八个目标选项是简体中文、繁体中文、英语、日语、西班牙语、法语、德语、俄语；简繁对应同一种中文口语。设计音色按语言提供男女声；也保留官方预设。默认预设的口音风格不等同于母语保证。

| 目标 | 男声记录 | 女声记录 | 语言正确 | 听感评分 / 备注 |
| --- | --- | --- | --- | --- |
| 简体中文 | 待填 | 待填 | 待填 | 待填 |
| 繁体中文 | 待填 | 待填 | 待填 | 待填 |
| 英语 | 待填 | 待填 | 待填 | 待填 |
| 日语 | 待填 | 待填 | 待填 | 待填 |
| 西班牙语 | 待填 | 待填 | 待填 | 待填 |
| 法语 | 待填 | 待填 | 待填 | 待填 |
| 德语 | 待填 | 待填 | 待填 | 待填 |
| 俄语 | 待填 | 待填 | 待填 | 待填 |

听感建议由熟悉目标语言的人评估：内容完整、发音准确、停顿合理、语调自然、语速可听懂，分别记 1–5 分。任何漏词、重复整句、语言错误或明显变调均记失败；不熟悉的语言标“听感未验收”，不要用自动转写正确率替代母语听感。

## 7. 确认真实配音设备

在客户端中完成一次试听，保持对应服务运行，在终端保存状态。每次更换引擎后，使用对应地址。若界面设置了自定义地址，以实际地址为准。

| 模式 | 默认地址 |
| --- | --- |
| Qwen 标准/设计音色 | `http://127.0.0.1:19882/subflow/runtime` |
| Qwen 原声克隆 | `http://127.0.0.1:9881/subflow/runtime` |
| GPT-SoVITS | `http://127.0.0.1:9880/subflow/runtime` |

例如检查 Qwen 标准/设计音色：

```bash
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:19882/subflow/runtime > "$QA_DIR/qwen-native-after.json"
```

每种模式在真实合成前后各保存一次。Apple M 的实际 `device` 必须保持 `mps` 才计 GPU 通过；变成 `cpu` 只能记为“CPU 回退后功能通过”。GPT 的 MPS 路径应 `is_half=false`。Qwen 不要求存在同名字段；以实际 `device` 为准。请求失败或空文件不算通过，先确认选对了服务与端口。

## 8. 翻译、字幕、配音与任务恢复

| 编号 | 操作 | 通过条件 |
| --- | --- | --- |
| FLOW-01 | 中文短片 → 英语；选择 Qwen 官方音色并开始 | 输出目标语音，字幕内容对应；不能仍是整段中文原声 |
| FLOW-02 | 中文短片 → 法语；选择设计男声再开始 | 实际使用所选设计音色，不被改成 GPT-SoVITS |
| SUB-01 | 播放有长短句混合的成片 | 全片字号一致、位置稳定，每种语言最多一行；无出界、叠字或频繁跳动 |
| SUB-02 | 检查长句、标点、最后一句 | 不漏译、不重复，字幕与配音内容一致；查看 `subtitle_fit_warnings` 中的时长/阅读速度记录 |
| CTRL-01 | 运行中暂停 → 继续 | 从当前任务恢复，保持原输出路径 |
| CTRL-02 | 运行中停止 → 启动新任务 | 停止生效，无旧线程继续覆盖新任务；原片与已完成文件完整 |
| REC-01 | 保存一个无效测试翻译令牌，启动短片，等翻译失败 | 任务退出后“继续”可用；前面的识别结果保留 |
| REC-02 | 填回有效令牌，点击“继续” | 从翻译重试，日志不重新出现音频提取/识别；成功生成译文和成片 |
| REC-03 | 若出现部分缺译 | “继续”能补译；后续烧录或配音失败时，缺译也仍可重试 |
| REC-04 | 翻译失败后换一条视频或修改界面选项，但不点开始 | “继续”恢复原任务快照，不把旧识别结果混入新视频；新视频应点“开始”建立新任务 |

恢复测试不要修改/删除缓存来模拟网络故障，否则正确行为是拒绝复用。按钮重试针对当前客户端会话；不要关闭应用后期待按钮仍携带上一会话的任务状态。

恢复证据：保存失败前后的工作目录路径、`transcript.json` 的 SHA-256、`job_state.json` 和日志。继续后应仍使用同一工作目录，识别文件摘要不变，译文补全。

## 9. 在真实客户端强制 CPU 再跑一次

先从菜单完整退出所有 SubFlow 实例。在终端直接启动可执行文件，环境覆盖只影响这次启动：

```bash
SUBFLOW_TORCH_BACKEND=cpu SUBFLOW_GPTSOVITS_DEVICE=cpu \
  "$APP/Contents/MacOS/SubFlow"
```

重复 ASR-01、TTS-01、TTS-04、TTS-05 和 FLOW-01。检查 Whisper 最终成功行及各配音服务状态均为 `cpu`，成片可播放。CPU 显式选择与 GPU 出错后的自动回退是两项不同证据。

结束后退出这个实例，再从“应用程序”正常启动恢复自动设备选择。若你设置过明确 ASR 设备覆盖，应恢复 `auto` 或使用与本次一致的设备。Mac 上 Docker Desktop 的 Linux 容器按 CPU 验收，不能将容器 CPU 成功计作 Apple GPU 成功。

## 10. 稳定性、迁移与离线配音

1. 3–5 分钟视频完成后再测试常用长视频，记录各阶段耗时、峰值内存、内存压力与是否回退。进度仍在更新且进程正在计算时，不能仅凭停留百分比认定卡死；同时检查日志、CPU/GPU 活动及停止按钮是否有效。
2. 连续运行三次短任务，分别使用官方音色、设计音色和克隆模式，确认没有持续累积的内存占用或端口冲突。
3. 退出应用后将完整 `.app` 复制到另一个带空格的路径，保持内部结构不变，再启动并试听。测试完成前保留原副本。
4. 退出应用、断开外网，再启动并试听三种模式。标准/设计音色直接使用内置资源，克隆模式使用本地参考音频。不要同时测试尚未下载的识别模型或云端翻译。
5. 正常退出后检查没有仍在播放或执行本次任务的服务；不要用 `killall python`，它可能终止无关程序。

## 11. 证据与最终判定

工作目录定位文件：`$HOME/.cache/bilingual-sub/last_job.json`。它是最后一个任务的指针，同时运行多个实例时应核对具体工作目录，不能混用。Qwen 日志位于 `$HOME/.config/subflow/managed/qwen-tts.log`，GPT 日志位于 `$HOME/.config/subflow/gptsovits.log`；自定义运行根目录时按实际路径查找。

建议每个场景保存：场景编号、输入名称/摘要、配置截图、耗时、最终设备、输出文件、错误信息、通过/失败/未测。API 令牌、Cookies、完整用户配置与私有视频不需要放进验收材料；分享日志前检查是否有不宜公开的内容。

| 验收项 | M1 结果 | Intel 结果 | 证据 |
| --- | --- | --- | --- |
| 包版本/架构/签名与环境 | 未测 | 未测 | 系统信息、环境 report.json |
| Whisper 真 GPU / Intel CPU | 未测 | 未测 | whisper.log、成片 |
| WhisperX CPU | 未测 | 未测 | whisperx.log |
| 三种配音模式与真实设备 | 未测 | 未测 | 服务状态、试听、成片 |
| 八语种与男女音色 | 未测 | 未测 | 逐项记录与听感评价 |
| 固定字号/单行/时序 | 未测 | 未测 | 截图、成片 |
| 失败翻译继续 | 未测 | 未测 | 工作目录、摘要、日志 |
| CPU 完整流程 | 未测 | 未测 | CPU 日志和成片 |
| 停止/重启/迁移/离线配音 | 未测 | 未测 | 各场景记录 |

只有执行完的项目可以标为通过。M1 通过不能替代 Intel Mac 验收；环境组件通过不能替代真实模型推理和人工听感验收。遇到失败，请提供场景编号、芯片/内存/macOS、实际设备、错误文字和对应日志，不需要发送令牌。

## 12. 维护者在 Mac 构建当前完整包

使用**本轮源码快照**，不要用旧 Release 来替代。构建需要在对应架构的 Mac 上进行；这是开发者步骤，与最终用户无需安装环境并不冲突。

1. 准备原生 Python 3.11+、Xcode Command Line Tools、FFmpeg（含字幕烧录能力）和足够磁盘空间；首次构建需要联网下载四套环境和模型。完整包与组装目录会同时占空间，先检查 `df -h .`。
2. 如果使用 Homebrew，安装 `python@3.11`、`ffmpeg-full`、`sevenzip`，并让 `python3` 指向原生 Python 3.11+。不要在 Rosetta 终端构建 Apple M 包。
3. 在当前源码根目录执行：

```bash
bash scripts/build-macos.sh
```

脚本会创建隔离的构建环境，避免修改系统/Homebrew Python；Apple M 完整包固定携带 MPS/CPU 可用的原生环境，Intel 携带 CPU 环境。依赖安装、签名或验证失败都会停止构建。

4. 得到 `dist/SubFlow.app` 后，先按第 3 节运行随包检查，再按整份手册测试。只在构建机成功启动不算可迁移通过。
5. 可选的严格真实离线配音检查，在安装了本项目开发依赖的源码环境执行：

```bash
python scripts/check-offline-voices.py dist/SubFlow.app/Contents/Resources/offline \
  --backend mps --require-gpu --output /tmp/SubFlow-Mac-voice-gpu
python scripts/check-offline-voices.py dist/SubFlow.app/Contents/Resources/offline \
  --backend cpu --output /tmp/SubFlow-Mac-voice-cpu
```

Intel 只运行 CPU 命令。输出目录应由本次测试专用，重试时使用新名字。`--voice-bank` 可追加全部设计音色，耗时更长。明确 `--backend mps` 或 `--require-gpu` 时回退 CPU 会判定失败。自动脚本仅检查合成成功与实际设备，听感仍按第 6 节人工评估。


### 复用完整包并保留其他平台产物

已有同架构完整离线包时，可复用模型和解释器；脚本仍会刷新当前源码中的 GPT-SoVITS 修复及资源摘要：

```bash
SUBFLOW_BUILD_PYTHON=/path/to/native/python3 \
SUBFLOW_REUSE_OFFLINE=/Applications/SubFlow.app/Contents/Resources/offline \
SUBFLOW_DIST_DIR="$PWD/dist-macos" \
bash scripts/build-macos.sh
```

Mac 归档必须保留 Qt framework 的符号链接。发布前验证实际解压后的应用，不能仅验证压缩前目录：

```bash
cd dist-macos
7zz a -t7z -mx=1 -ms=off -mmt=2 -snl -v1900m SubFlow-macos-arm64.7z ./SubFlow.app
7zz t SubFlow-macos-arm64.7z.001
7zz x -snld20 -o/tmp/SubFlow-extracted SubFlow-macos-arm64.7z.001
# 解压后执行第 2、3 节，并运行：
/path/to/extracted/SubFlow.app/Contents/MacOS/SubFlow --self-test /tmp/release-smoke.json
```

本次使用的 7-Zip 26.03 默认链接保护会忽略 PyInstaller 从 Resources 指向 `../Frameworks` 的应用内部链接。对已校验的本项目完整分卷使用 `-snld20` 才能完整还原。发布 CI 在打包前和解压后用 `scripts/check-macos-links.py` 检查所有链接：禁止绝对路径、应用外目标、悬空链接及循环链接。

父目录链接和间接链接需要 `-snld20`，这是 [7-Zip 作者给出的参数](https://sourceforge.net/p/sevenzip/bugs/2593/)。只对来源及摘要已核实的本项目包使用，并在解压后运行链接检查和签名验证。
