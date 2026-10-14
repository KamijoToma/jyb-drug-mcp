# jyb-drug-mcp

津医保（天津市医保局 App）「医药云平台 · 定位药品上架药店」功能的 MCP (Model Context Protocol) server。

让任意支持 MCP 的 AI 客户端（Claude Desktop、omp 等）可以直接：

- 按药品名检索药品目录（拿到 `drugCode`）
- 查询该药品的有货机构列表：机构名、**最新价格**、**与你的距离**、**最后交易日期（lastTrnsDate）**、坐标
- 一步式：药品名 → 自动匹配候选 → 有货药店列表

> English: An MCP server exposing the Tianjin Medical Insurance app's "drug → stocking pharmacies" API
> (search drugs, query stocking institutions with price / distance / last transaction date).

> **免责声明**：本项目仅供学习与个人研究，通过自己账号的会话凭据访问自己可见的数据。
> 请遵守相关服务条款与当地法规，勿用于商业用途或高频爬取。与官方无关。使用风险自负。

## 工作原理（协议摘要）

业务接口位于 `https://jyt.ylbz.tj.gov.cn/app-prod/`，HTTPS 之外还有一层应用层保护：

- **报文加密**：请求与响应体均为 AES-256-CBC(PKCS7) 密文的 Base64；
  key（32 字符）/ IV（16 字符）为登录时下发、会话级有效的 UTF-8 字符串
- **请求签名**（均不覆盖 body）：
  - `jyb-signature = md5(timestamp + nonce + token + "jyb4443")`
  - `X-Tif-Signature = SHA256(timestamp + paastoken + nonce + timestamp)`（paastoken 为空）
- **鉴权**：请求头 `token`（登录会话）

三个会话凭据（token / key / iv）需要通过一次抓包获取，见
[docs/OBTAINING_CREDENTIALS.md](docs/OBTAINING_CREDENTIALS.md)（含自动化探针脚本）。

## 安装

```sh
pip install "mcp<2" pycryptodome
```

要求 Python 3.10+。

## 配置凭据

```sh
cp .env.example .env   # 填入 JYB_TOKEN / JYB_AES_KEY / JYB_AES_IV
```

server 启动时自动加载同目录 `.env`（不覆盖已有环境变量）；`.env` 已被 `.gitignore`
排除。凭据获取的完整流程见 [docs/OBTAINING_CREDENTIALS.md](docs/OBTAINING_CREDENTIALS.md)。

## MCP 客户端配置

Claude Desktop / 通用 stdio 配置：

```json
{
  "mcpServers": {
    "jyb-pharmacy": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/jyb-drug-mcp/server.py"]
    }
  }
}
```

omp：在 `~/.omp/agent/mcp.json` 的 `mcpServers` 下加入同样条目。

## 工具

| 工具 | 说明 |
|---|---|
| `search_drug(drug_name, page, page_size)` | 药品名 → 候选药品（drugCode / 规格 / 厂家） |
| `find_orgs(drug_code, latitude, longitude, ...)` | drugCode → 有货机构（价格 / 距离 / 坐标 / lastTrnsDate） |
| `find_drug_stores(drug_name, latitude, longitude)` | 一步式：自动尝试候选，返回首个有货结果 |
| `update_session(token, aes_key, aes_iv)` | 凭据过期后热刷新（也可直接改 `.env` 重启） |

## 已知边界

- 凭据是会话级的：App 重新登录即失效，重新跑一遍抓包流程即可
- `purcRcdFlag`（采购记录视角）公开数据目前基本为空；采购明细未开放
- 行政区划参数当前固定为天津（`admdvs=120000`）

## 开发

```sh
python3 smoke_test.py        # 配置好 .env 后运行全链路冒烟测试
```

`capture_addon.py` 是抓凭据用的 mitmproxy 插件（见凭据文档），不属于运行时依赖。

## License

[MIT](LICENSE)
