# API 令牌 — SubFlow 语幕

翻译走 [meding](https://api.meding.site) 的 OpenAI 兼容接口。识别与配音在本机完成；配音只走内置 GPT-SoVITS，不消耗该令牌。

## 获取

打开 [https://api.meding.site](https://api.meding.site)（客户端内「API 分发站」同一地址），按站点说明领取 Key。

## 承诺

- 令牌**只保存在本机**
- 工具**不上传**、**不汇聚**、**不共享** Key
- 日志自动脱敏，异常栈不含 Authorization 头

## 存储位置

| 平台 | 主存储 | 兜底 |
| --- | --- | --- |
| Windows | Credential Manager（服务名 `subflow`） | `%APPDATA%\SubFlow\users\<用户>\credentials.json` |
| macOS | Keychain | `~/.config/subflow/users/<用户>/credentials.json` |
| Linux | secretstorage | `~/.config/subflow/users/<用户>/credentials.json` |

旧版 `bilingual-sub` 路径仍会被读取，便于升级后沿用已保存的 Key。

环境变量优先：`SUBFLOW_API_KEY` 或 `MEDING_API_KEY`。Docker 用 `.env` 注入到 `crazymsn/subflow:latest`，**不要写进镜像、不要提交 `.env`**。

## 命令

```bash
subflow config set-api-key     # 保存后自动打印模型列表
subflow models
subflow config set-model <id>
subflow config show
subflow config delete-api-key
```

桌面客户端：粘贴令牌 →「保存令牌」→「获取模型」→ 下拉选择。留空保存表示沿用本机已有令牌。

## 轮换

```bash
subflow config delete-api-key
subflow config set-api-key
```

## 多用户同机

按操作系统账户隔离凭据，互不可见。
