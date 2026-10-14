# 如何获取会话凭据（JYB_TOKEN / JYB_AES_KEY / JYB_AES_IV）

津医保 App 与服务端的业务流量在 HTTPS 之外还有**一层应用层加密**（AES-256-CBC），
密钥是登录时下发、仅存于 App WebView 内的会话级凭据，无法从任何公开页面直接拿到。
本文描述用 mitmproxy + 一次 JS 探针注入把这三项凭据取出来的完整流程。

> 原理摘要见 README「协议分析」一节。整个过程只读取自己账号的会话凭据，
> 不涉及越狱、不修改 App 本体。请仅用于自己账号的研究与学习。

## 凭据的形态

| 环境变量 | 形态 | 来源 |
|---|---|---|
| `JYB_TOKEN` | `TJSYAPP_TOKEN_ALIAS_<uuid>` | 每个业务请求的 `token` 请求头 |
| `JYB_AES_KEY` | 32 位字符串 | 登录接口下发，存于 WebView storage |
| `JYB_AES_IV` | 16 位字符串 | 同上 |

三者同时过期（通常伴随重新登录），届时重新执行本流程即可。

## 前置条件

- 一台 Mac（本流程以 macOS 为例）+ 一台已登录津医保的 iPhone
- 二者连同一 Wi-Fi
- 安装 [mitmproxy](https://mitmproxy.org/)：`brew install mitmproxy`

## 步骤

### 1. 启动带探针的代理

```sh
cd jyb-drug-mcp
mitmdump -p 8080 -s capture_addon.py --set block_global=false
```

首次运行若 macOS 弹出"是否允许 mitmdump 接受传入网络连接"，点允许。

`capture_addon.py` 做两件事：把所有流量记到 `flows.jsonl`；对津医保 H5 主包
注入一段探针（语法安全，页面正常使用），在首个加密请求发出时把
`token / aesKey / aesIv` 拼进一张一次性图片的 URL 回传（服务端 404，无副作用）。

### 2. iPhone 配置代理与证书

1. 设置 → Wi-Fi → 当前网络 (i) → 配置代理 → 手动：
   服务器填 Mac 的 IP（`ipconfig getifaddr en0`），端口 `8080`
2. Safari 打开 `http://mitm.it` → 下载 mitmproxy 证书并安装描述文件
3. **设置 → 通用 → 关于本机 → 证书信任设置** → 打开 mitmproxy 的完全信任
   （漏掉这步是 HTTPS 抓不到的头号原因）

### 3. 触发凭据回传

彻底杀掉津医保（上滑划掉）→ 重新打开 → 进入任意使用 H5 的页面
（首页/医药云平台均可）。页面一发出加密请求，mitmdump 日志即出现：

```
GET https://jyt.ylbz.tj.gov.cn:4443/jyt-icon/kx_<TOKEN>_<AES_KEY>_<AES_IV>.png
```

（也可直接看 `flows.jsonl` 里含 `kx_` 的行。）

### 4. 填入 .env

```sh
cp .env.example .env
# 把 kx_ 后三段依次填入 JYB_TOKEN / JYB_AES_KEY / JYB_AES_IV
```

`.env` 已被 `.gitignore` 排除。填完重启 MCP server（或在对话里让 agent 调用
`update_session` 热更新）即可正常调用全部工具。

## 故障排查

| 现象 | 处理 |
|---|---|
| 页面白屏 / 没有 `kx_` 回传 | 确认拿到的是新版 `capture_addon.py`；确认杀掉 App 后重开（WebView 缓存） |
| App 全部请求失败、页面空白 | 证书未开"完全信任"（第 2 步第 3 小步） |
| 只有部分域名出现在日志 | 业务接口可能走 QUIC(UDP 443)，在路由器/防火墙封 UDP 443 强制回退 TCP |
| `服务端返回 401/403` | 凭据过期（App 重新登录会使旧会话失效），重新执行本流程 |
| Mac 收不到任何连接 | 检查 macOS 防火墙对 mitmdump 的放行；确认 iPhone 与 Mac 同网段 |

## 不想用注入探针？

凭据也可手工获取：完成步骤 2（代理 + 证书）后直接打开 App 搜药，在
`flows.jsonl` 中任选一条 `/app-prod/` 加密请求——`req_headers.token` 即
`JYB_TOKEN`；但 `aesKey/aesIv` 只存在于 WebView 本地存储中，不注入探针的话
需要从 iPhone 备份里提取 localStorage，繁琐得多。推荐直接用探针。
