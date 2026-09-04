# API Key 配置（语幕 SubFlow）

## 获取 Key

从 meding 运营渠道获取 API Key（占位，待运营补链接）。

## 承诺

- Key **只保存在本机**（Windows Credential Manager / macOS Keychain / Linux secretstorage）
- 工具**不上传**、**不汇聚**、**不共享** Key
- 日志自动脱敏，异常栈不含 Authorization 头

## 存储位置

| 平台 | 主存储 | 兜底 |
|------|--------|------|
| Windows | Credential Manager | `%APPDATA%\bilingual-sub\credentials.json` (0600) |
| macOS | Keychain | `~/.config/bilingual-sub/credentials.json` |
| Linux | secretstorage | `~/.config/bilingual-sub/credentials.json` |

## 命令

```bash
subflow config set-api-key     # 保存后自动打印模型列表
subflow models
subflow config set-model <id>
subflow config show
subflow config delete-api-key
```

Docker 用环境变量 `SUBFLOW_API_KEY`，不要写进镜像。

## 轮换 Key

```bash
bilingual-sub config delete-api-key
bilingual-sub config set-api-key
```

## 多用户同机

各 OS 账户凭据隔离，互不可见。
