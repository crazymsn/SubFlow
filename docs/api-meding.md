# meding API 契约

> Base URL 固定为 `https://api.meding.site`，不可配置。

## 端点（OpenAI 兼容）

```
POST https://api.meding.site/v1/chat/completions
Authorization: Bearer {USER_API_KEY}
```

## 请求体

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "中文句子"}
  ]
}
```

## 健康检查

```
GET https://api.meding.site/v1/models
```

## 错误码

| HTTP | 处理 |
|------|------|
| 401 | 提示用户检查 Key，退出码 3 |
| 429 | 指数退避重试 1s/2s/4s，最多 3 次 |
| 5xx | 同上 |

## 实现

客户端：`adapters/meding.py` — OpenAI SDK，`base_url=https://api.meding.site/v1`（常量仍为不含路径的 `MEDING_BASE_URL`）

缓存：`~/.cache/bilingual-sub/translations.db`，key = sha256(model+zh)
