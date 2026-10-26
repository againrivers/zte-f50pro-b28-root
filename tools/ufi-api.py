#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFI-TOOLS API 最小客户端

用法:
    python3 ufi-api.py --host 192.168.0.1:2333 --password admin \
        --call POST /api/root_shell '{"command":"id","timeout":15000}'

    python3 ufi-api.py --call GET /api/plugins_store

鉴权算法（逆出来的，官方文档未写全）:
    raw   = "minikano" + METHOD + PATH + timestamp
    hmac  = HMAC_MD5(key, raw)                 # 16 字节
    sign  = SHA256( SHA256(hmac[0:8]) + SHA256(hmac[8:16]) ).hex()
             ↑ 必须用原始 32 字节摘要拼接，不是 hex 字符串

    authorization = SHA256(password).hex()

三个头: kano-t / kano-sign / authorization

关于 KEY:
    KEY 是 UFI-TOOLS 内嵌在 APK 里的固定值, 本项目不随仓库分发。
    请从你自己手上的 APK 中提取后通过环境变量传入:

        export UFI_KEY="$(unzip -p UFI-TOOLS.apk 'classes*.dex' | strings \
            | grep -oE 'minikano_[A-Za-z0-9_]+' | head -1)"

    或在命令行用 --key 指定。
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# 不硬编码, 由环境变量或 --key 传入
KEY = os.environ.get("UFI_KEY", "").encode()


def sign(method: str, path: str, timestamp: str, key: bytes) -> str:
    raw = ("minikano" + method + path + timestamp).encode()
    digest = hmac.new(key, raw, hashlib.md5).digest()
    # 关键：原始摘要拼接，不是 hex
    combined = hashlib.sha256(digest[:8]).digest() + hashlib.sha256(digest[8:]).digest()
    return hashlib.sha256(combined).hexdigest()


def call(host: str, password: str, method: str, path: str, body=None, timeout=30,
         key: bytes = None):
    """path 含前导 /，不含 query string（query 由 urllib 处理时需自行剔除签名）。"""
    if urllib.parse.urlparse(path).query:
        raise SystemExit("签名用的 path 不能带 query string，请分开传")

    ts = str(int(time.time() * 1000))
    data = json.dumps(body).encode() if body is not None else None

    req = urllib.request.Request(f"http://{host}{path}", data=data, method=method)
    req.add_header("kano-t", ts)
    req.add_header("kano-sign", sign(method, path, ts, key or KEY))
    req.add_header("authorization", hashlib.sha256(password.encode()).hexdigest())
    if data:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def main():
    ap = argparse.ArgumentParser(description="UFI-TOOLS API 客户端")
    ap.add_argument("--host", default="192.168.0.1:2333")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--call", nargs=3, metavar=("METHOD", "PATH", "BODY"),
                    action="append", default=[],
                    help='例如 --call POST /api/root_shell \'{"command":"id"}\'')
    ap.add_argument("--key", default=None,
                    help="UFI-TOOLS 内嵌密钥；不填则读环境变量 UFI_KEY")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    key = (args.key.encode() if args.key else KEY)
    if not key:
        print("缺少 KEY。请设置环境变量 UFI_KEY，或用 --key 指定。\n"
              "提取方法：unzip -p UFI-TOOLS.apk 'classes*.dex' | strings \\\n"
              "          | grep -oE 'minikano_[A-Za-z0-9_]+' | head -1", file=sys.stderr)
        return 2

    if not args.call:
        ap.print_help()
        return 1

    rc = 0
    for method, path, raw_body in args.call:
        method = method.upper()
        body = None
        if raw_body and raw_body.strip() not in ("", "null"):
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError as e:
                print(f"BODY 不是合法 JSON: {e}", file=sys.stderr)
                return 2
        status, text = call(args.host, args.password, method, path, body,
                            args.timeout, key)
        print(f"--- {method} {path} -> {status}")
        print(text)
        if status != 200:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
