# meding API 契约

> Base URL 固定为 `https://api.meding.site`，不可配置。实现只允许出现在 `adapters/meding.py`。

翻译与 OpenAI 配音共用该站点。客户端「API 分发站」打开的就是这个地址。

## 端点（OpenAI 兼容）

```
POST https://api.meding.site/v1/chat/completions
Authorization: Bearer {USER_API_KEY}
```

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "中文句子"}
  ]
}
```

健康检查与模型列表：

```
GET https://api.meding.site/v1/models
```

保存令牌后，CLI `subflow models` 与桌面「获取模型」都打这一支。

## 错误码

| HTTP | 处理 |
| --- | --- |
| 401 | 提示检查令牌，进程退出码 3 |
| 429 | 指数退避 1s / 2s / 4s，最多 3 次 |
| 5xx | 同上 |

## 实现要点

- SDK `base_url=https://api.meding.site/v1`（常量 `MEDING_BASE_URL` 不含路径）
- 翻译缓存：`~/.cache/bilingual-sub/translations.db`，key = sha256(model + 源文)
- 请求体只有字幕文本，不含视频文件
