# API 令牌与数据说明

[返回文档索引](README.md) · 适用于 **1.3.46**

## 什么时候需要令牌

识别和默认 GPT-SoVITS 配音在本机完成，不消耗翻译令牌。中文原片输出简体 / 繁体单语字幕并保留原声时，不需要翻译 API。

中英双语字幕中的英文行、跨语种翻译、可选翻译润色和 AI 术语处理会调用 [meding](https://api.meding.site) 的 OpenAI 兼容接口，需要用户自己的有效令牌。可用模型和额度以账户实际返回结果为准。

## 配置

客户端：粘贴令牌 →「保存令牌」→「获取模型」→ 选择翻译模型。留空保存表示沿用已有令牌，不代表删除。

源码 CLI：

```bash
subflow config set-api-key
subflow models
subflow config set-model MODEL_ID
subflow config show
```

把 `MODEL_ID` 替换为列表中的 ID。保存令牌后会尝试获取模型列表，因此接口不可达可能影响此步骤的结果。

Docker：将令牌填入部署目录的 `.env` 中 `SUBFLOW_API_KEY`，然后启动新任务容器。不要将令牌写入 Dockerfile、镜像或公开的 Compose 文件。具体步骤见 [Docker 指南](docker.md)。

## 存储和读取顺序

优先读取非空环境变量 `SUBFLOW_API_KEY`，其次 `MEDING_API_KEY`，再读取当前操作系统用户的凭据库及本地备用文件。旧版 `bilingual-sub` 凭据保留迁移兼容。

| 平台 | 首选存储 | 不可用时的备用文件 |
| --- | --- | --- |
| Windows | Windows Credential Manager | `%APPDATA%/SubFlow/users/<用户>/credentials.json` |
| macOS | 系统 Keychain | `~/.config/subflow/users/<用户>/credentials.json` |
| Linux | 可用的系统 keyring 后端 | `~/.config/subflow/users/<用户>/credentials.json` |

凭据服务名为 `subflow`。备用文件是 **JSON 明文**，程序尝试限制文件权限，不能等同于凭据库加密存储。操作系统权限决定隔离效果；管理员、同账户进程及有 Docker 管理权限的用户可能访问相关数据。

Docker 交互保存的配置写入 `subflow-config` 命名卷；通过环境变量注入的令牌也可能被有权限的容器管理工具查看。共享主机部署应按账户和项目限制访问。

## 实际网络请求

翻译请求通过 HTTPS 发送至固定的 meding 端点，使用 `Authorization: Bearer …` 鉴权。因此“令牌只保存在本机”指存储位置，并不表示鉴权时不会发送给服务端。

翻译请求包含字幕、提示词和所用术语；润色请求还可能包含原文、已有译文及相关上下文。默认流程不把原视频或参考音频发送到翻译接口。下载视频、安装依赖和获取模型也需要访问各自的站点。自定义外部配音服务的数据处理由其部署方式决定。

程序对常见敏感字段做日志脱敏，但日志仍可能含本机路径、字幕文本或第三方错误响应；分享前应检查，勿上传完整配置、Cookie 或私人媒体。

## 删除与轮换

```bash
subflow config delete-api-key
subflow config set-api-key
```

删除命令移除本机凭据及兼容备用文件，**不会清除父进程环境变量或 Docker 的 .env**。如仍读取旧令牌，检查并更新这些优先来源，再重新启动客户端或任务容器。

令牌泄露时，应先在服务提供方撤销旧令牌，再保存新令牌；单纯删除本地配置不会撤销服务端权限。
