"""MCP smoke test: spawn jyb server over stdio, list tools, exercise tool paths.

凭据从环境变量继承(或服务器目录 .env 自动加载); 未配置时仅验证握手与报错路径.
"""
import asyncio
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
PARAMS = StdioServerParameters(command="python3", args=[SERVER])
# 天津市内通用示例坐标(和平区), 非个人位置
LAT, LNG = 39.117, 117.195


def _env_has_creds() -> bool:
    if all(os.environ.get(k) for k in ("JYB_TOKEN", "JYB_AES_KEY", "JYB_AES_IV")):
        return True
    env_file = os.path.join(os.path.dirname(SERVER), ".env")
    if os.path.isfile(env_file):
        text = open(env_file, encoding="utf-8").read()
        return all(f"{k}=" in text for k in ("JYB_TOKEN", "JYB_AES_KEY", "JYB_AES_IV"))
    return False


HAS_CREDS = _env_has_creds()


async def main():
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])

            if not HAS_CREDS:
                print("未配置 JYB_* 凭据 — 跳过在线调用(配置方法见 docs/OBTAINING_CREDENTIALS.md)")
                return

            r1 = await s.call_tool("search_drug", {"drug_name": "阿司匹林", "page_size": 3})
            d1 = json.loads(r1.content[0].text)
            print("search_drug code:", d1["code"], "| 候选:", len(d1["drugs"]))

            r2 = await s.call_tool("find_drug_stores",
                                   {"drug_name": "二甲双胍", "latitude": LAT, "longitude": LNG})
            d2 = json.loads(r2.content[0].text)
            print("find_drug_stores:", d2["chosen_drug"]["drugName"], "| 机构数:", len(d2["orgs"]))
            if d2["orgs"]:
                o = d2["orgs"][0]
                print("  首家:", o["orgName"], o["latestPrice"], "元",
                      o["addrInfo"][0]["distance"], "| 最后交易:", o.get("lastTrnsDate"))

            r3 = await s.call_tool("update_session",
                                   {"token": "bad", "aes_key": "k" * 32, "aes_iv": "i" * 16})
            print("update_session:", r3.content[0].text)
            r4 = await s.call_tool("find_orgs", {"drug_code": "X" * 24,
                                                 "latitude": LAT, "longitude": LNG})
            print("坏凭据 isError =", r4.isError, "| 报文头:", r4.content[0].text[:60])


asyncio.run(main())
