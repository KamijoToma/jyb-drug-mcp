#!/usr/bin/env python3
"""津医保·医药云平台 药店查询 MCP server (stdio).

Tools:
  - search_drug(drug_name)                 药品名 -> 候选药品(含 drugCode)
  - find_orgs(drug_code, lat, lng)         drugCode -> 有货机构列表(价格/距离/最后交易日期)
  - find_drug_stores(drug_name, lat, lng)  两步链路一步到位
  - update_session(token, aes_key, aes_iv) 会话过期后刷新凭据(仅当前进程)

凭据(会话级, 由 App 登录下发): 从环境变量 JYB_TOKEN / JYB_AES_KEY / JYB_AES_IV 读取;
本文件同目录下的 .env 会在启动时自动加载(不覆盖已存在的环境变量)。
获取方式见 docs/OBTAINING_CREDENTIALS.md。.env 已被 .gitignore 排除, 请勿提交。
"""
import base64
import hashlib
import json
import os
import random
import ssl
import string
import time
import urllib.request
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from mcp.server.fastmcp import FastMCP

BASE = "https://jyt.ylbz.tj.gov.cn/app-prod"
DOCS = "https://github.com/<you>/jyb-drug-mcp/blob/main/docs/OBTAINING_CREDENTIALS.md"


def _load_dotenv() -> None:
    """加载脚本同目录 .env(若存在), 不覆盖已有环境变量."""
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip("'\"")
        if k and v and k not in os.environ:
            os.environ[k] = v


_load_dotenv()

_STATE = {
    "token": os.environ.get("JYB_TOKEN", ""),
    "key": os.environ.get("JYB_AES_KEY", ""),
    "iv": os.environ.get("JYB_AES_IV", ""),
}

CTX = ssl.create_default_context()
mcp = FastMCP("jyb-pharmacy", instructions="津医保医药云平台: 药品检索与有货药店(价格/距离/最后交易日期)查询")


def _require_creds() -> None:
    missing = [k for k, v in (("JYB_TOKEN", _STATE["token"]),
                              ("JYB_AES_KEY", _STATE["key"]),
                              ("JYB_AES_IV", _STATE["iv"])) if not v]
    if missing:
        raise RuntimeError(
            f"缺少会话凭据: {', '.join(missing)}。"
            f"请在 .env 中配置(模板见 .env.example)或调用 update_session。获取方法: {DOCS}")


def _aes_enc(plain: str) -> str:
    c = AES.new(_STATE["key"].encode(), AES.MODE_CBC, _STATE["iv"].encode())
    return base64.b64encode(c.encrypt(pad(plain.encode(), 16))).decode()


def _aes_dec(b64: str) -> str:
    c = AES.new(_STATE["key"].encode(), AES.MODE_CBC, _STATE["iv"].encode())
    return unpad(c.decrypt(base64.b64decode(b64)), 16).decode()


def _headers(ts: str, nonce: str) -> dict:
    token = _STATE["token"]
    return {
        "content-type": "application/json",
        "token": token,
        "dataSouc": "1",
        "jyb-timestamp": ts,
        "jyb-nonce": nonce,
        "jyb-signature": hashlib.md5((ts + nonce + token + "jyb4443").encode()).hexdigest(),
        "X-Tif-Timestamp": ts,
        "X-Tif-Nonce": nonce,
        "X-Tif-Paasid": "jyt_test",
        "X-Tif-Signature": hashlib.sha256((ts + "" + nonce + ts).encode()).hexdigest().upper(),
        "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Mobile/15E148 MDLIFE/2.0",
        "origin": "https://jyt.ylbz.tj.gov.cn:4443",
        "referer": "https://jyt.ylbz.tj.gov.cn:4443/",
    }


def _call(path: str, param: dict) -> dict:
    _require_creds()
    ts = str(int(time.time()))
    nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=11))
    req = urllib.request.Request(
        BASE + path, data=_aes_enc(json.dumps(param, ensure_ascii=False)).encode(),
        headers=_headers(ts, nonce), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                f"服务端返回 {e.code}, 会话凭据大概率已过期。"
                f"重新抓取后调用 update_session 或更新 .env。获取方法: {DOCS}") from e
        raise
    try:
        return json.loads(_aes_dec(raw))
    except Exception as e:
        raise RuntimeError(f"解密失败, 会话凭据可能已过期: {e}; 请用 update_session 刷新") from e


def _rows(resp: dict) -> list:
    d = resp.get("data")
    return d if isinstance(d, list) else []


@mcp.tool()
def search_drug(drug_name: str, page: int = 1, page_size: int = 10) -> str:
    """按药品名检索医药云平台药品目录, 返回候选药品及 drugCode(后续查药店用)."""
    r = _call("/med/drug/queryIntlDrugList",
              {"drugName": drug_name, "pageNum": page, "pageSize": page_size})
    return json.dumps({"code": r.get("code"), "message": r.get("message"),
                       "drugs": _rows(r)}, ensure_ascii=False)


@mcp.tool()
def find_orgs(drug_code: str, latitude: float, longitude: float,
              page: int = 1, page_size: int = 20, sort_type: str = "1") -> str:
    """按 drugCode 查询有货机构列表. 返回机构名/编码/最新价/距离/最后交易日期(lastTrnsDate)/坐标.
    sort_type "1" 按距离排序. latitude/longitude 用于计算距离."""
    r = _call("/med/drug/queryDrugEquipOrgList", {
        "admdvs": "120000", "drugCode": drug_code, "orgType": "0", "orgName": "",
        "purcRcdFlag": "0", "trnsRcdFlag": "1", "userLatitude": latitude,
        "userLongitude": longitude, "sortType": sort_type,
        "pageNum": page, "pageSize": page_size, "dataSouc": "1"})
    return json.dumps({"code": r.get("code"), "message": r.get("message"),
                       "orgs": _rows(r)}, ensure_ascii=False)


@mcp.tool()
def find_drug_stores(drug_name: str, latitude: float, longitude: float,
                     page_size: int = 20) -> str:
    """一步式: 药品名 -> 匹配候选 -> 有货药店列表(价格/距离/最后销售日期).
    依次尝试前 5 个候选药品, 取第一个有货的; 若想指定规格, 先用 search_drug 拿 drugCode 再调 find_orgs."""
    r = _call("/med/drug/queryIntlDrugList",
              {"drugName": drug_name, "pageNum": 1, "pageSize": 5})
    drugs = _rows(r)
    if not drugs:
        return json.dumps({"code": r.get("code"), "message": "未找到药品", "drugs": []},
                          ensure_ascii=False)
    orgs: list = []
    used: dict | None = None
    for cand in drugs[:5]:
        o = _call("/med/drug/queryDrugEquipOrgList", {
            "admdvs": "120000", "drugCode": cand["drugCode"], "orgType": "0", "orgName": "",
            "purcRcdFlag": "0", "trnsRcdFlag": "1", "userLatitude": latitude,
            "userLongitude": longitude, "sortType": "1",
            "pageNum": 1, "pageSize": page_size, "dataSouc": "1"})
        orgs = _rows(o)
        if orgs:
            used = cand
            break
    return json.dumps({"chosen_drug": used or drugs[0], "candidates": drugs,
                       "orgs": orgs,
                       "note": "所有候选均无货" if not orgs else ""}, ensure_ascii=False)


@mcp.tool()
def update_session(token: str, aes_key: str, aes_iv: str) -> str:
    """刷新会话凭据(token 来自抓包 header; aes_key 32位/aes_iv 16位由登录下发).
    仅对当前进程生效; 持久化请写入 .env. 当其他工具报 401/403 或解密失败时使用."""
    _STATE.update(token=token, key=aes_key, iv=aes_iv)
    return "会话凭据已更新(仅当前进程; 持久化请写入 .env)"


if __name__ == "__main__":
    mcp.run(transport="stdio")
