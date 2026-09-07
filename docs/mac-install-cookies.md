# SubFlow · Mac 安装与 Cookies

## 安装

在苹果菜单的“关于本机”查看“芯片”或“处理器”：Apple M1/M2/M3/M4/M5 等选 Apple M（arm64）DMG；Intel 处理器选 Intel（x86_64）DMG。两个包均使用相同的 SubFlow 界面，Apple M 使用 MPS/CPU，Intel 使用 CPU 推理。

打开相应 DMG，把 **SubFlow.app 拖到 Applications**。复制完成后推出磁盘映像，从“应用程序”启动 SubFlow。升级前退出旧客户端；用户配置保存在用户目录，不需要放进应用包。最低系统版本以该包 Info.plist 和交付报告为准。

本地测试包采用临时签名，未做 Apple 公证。如果系统阻止打开，请先核对交付 SHA-256；确认是本包后，在“系统设置 → 隐私与安全性”允许本应用打开。不要全局关闭系统安全检查。

## 启动时的密码提示

1.3.65 起，客户端以静默方式读取 API Key，不会因启动读取而要求输入 Mac 登录密码。现有钥匙串条目保留不动；若该条目要求认证，客户端会跳过它，需要在线翻译时请在 API Key 输入框重新填入你的密钥。只有你主动保存或清除密钥时才可能触发系统的钥匙串授权。

安装包的首次系统安全检查与钥匙串读取是两件事。本地包未公证，首次允许打开仍由 macOS 决定。

## Cookies 放在哪里

当前客户端自动读取文件，不需要把 Cookie 字符串粘贴到 API Key 或视频链接输入框。

Mac 用户目录：

```text
~/.config/subflow/Cookies/
```

| 网站 | 文件名 |
| --- | --- |
| YouTube | `youtube-cookies.txt` |
| Bilibili | `bilibili-cookies.txt` |

1. 用浏览器登录对应网站，确认自己可以播放目标视频。
2. 导出 **Netscape cookies.txt** 格式，分别按上表命名。
3. 在“终端”执行 `mkdir -p ~/.config/subflow/Cookies` 创建文件夹。
4. 在 Finder 按 **⌘⇧G**，粘贴上面的目录，把两个导出文件放进去。
5. 回到 SubFlow，填入视频链接后重新开始下载；已失败的下载需重新发起。

保留原来的制表符和字段，不要改成 Word、RTF、JSON 或 `Cookie: name=value` 请求头。第一行应为 `# Netscape HTTP Cookie File` 或 `# HTTP Cookie File`。`#HttpOnly_` 开头的是有效 Cookie 行，应完整保留。

如果用 Mac“文本编辑”保存文件，先选 **格式 → 制作纯文本（⇧⌘T）**，再按上表保存为 `.txt`。仅把 `.rtf` 后缀改成 `.txt` 不会转换文件内容。

## 怎样导出

**Chrome / Edge：** 可使用 yt-dlp 官方 FAQ 推荐的 **Get cookies.txt LOCALLY** 扩展，导出格式选择 Netscape，并仅导出需要的网站。Bilibili 在已登录的 `www.bilibili.com` 页面导出后，保存为 `bilibili-cookies.txt`。

**YouTube：** 官方建议在新的无痕/隐私窗口登录 YouTube；同一标签页随后打开 `https://www.youtube.com/robots.txt`，导出该会话的 Cookie，保存为 `youtube-cookies.txt`，然后关闭该隐私窗口。这可减少普通浏览会话自动轮换 Cookie 导致的失效。扩展需允许在该隐私窗口运行。

也可用已安装的 yt-dlp 从自己的普通浏览器配置导出：

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

该命令可能导出浏览器中多个网站的 Cookie，也不能代替上述 YouTube 隐私会话导出方式；针对单个网站使用扩展导出更容易管理。

Cookies 相当于登录凭据，只保存在自己的电脑上，不放进应用包、源码仓库或聊天。退出网站账号、修改密码或会话过期后，应重新导出；它不会赋予账号原本没有的播放权限。

参考：[yt-dlp Cookie 格式与导出说明](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)、[YouTube 导出步骤](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)。
