#!/usr/bin/env python3
"""打开有头 Edge 让用户登录 autodl.art；检测登录成功后：
1) 保存持久化会话（deploy/autodl-browser-profile + autodl-session.json）；
2) 立即跑一次完整上传探针（73 字节 PNG），打印三步响应，确定最终 URL 形态。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DELIVER = Path(r"D:\@kaifa\manju\deploy")
PROFILE = DELIVER / "autodl-browser-profile"
STATE = DELIVER / "autodl-session.json"
TEST_PNG = Path(r"D:\@kaifa\manju\adapters\selftest\upload-test.png")

MD5 = "b26b54932ddc1fe476d8a3cb213156d9"  # 73-byte test png
SIZE = 73


def probe_upload(context) -> None:
    payload = TEST_PNG.read_bytes()
    r1 = context.request.post(
        "https://autodl.art/api/v1/file/before_upload",
        data={"md5": MD5, "file_size": SIZE},
    )
    b1 = r1.json()
    print("PROBE_1 before_upload:", json.dumps(b1, ensure_ascii=False)[:500], flush=True)
    data = b1.get("data") or {}
    token = data.get("token")
    host = data.get("host")
    if not token or not host:
        print("PROBE_ABORT 无 token/host（可能已被拒）", flush=True)
        return
    if data.get("quickly_upload"):
        print("PROBE_2 秒传命中（服务端已有该文件）", flush=True)
    else:
        r2 = context.request.put(
            f"{host}/api/v1/file",
            headers={"FileToken": token},
            multipart={
                "md5": MD5,
                "chunk": "0",
                "chunks": "1",
                "chunk_size": str(SIZE),
                "file": {
                    "name": "upload-test.png",
                    "mimeType": "image/png",
                    "buffer": payload,
                },
            },
        )
        body2 = r2.text()[:500]
        print(f"PROBE_2 PUT 分块: status={r2.status} body={body2}", flush=True)
    r3 = context.request.post(
        f"{host}/api/v1/file",
        headers={"FileToken": token},
        data={"md5": MD5, "total_size": SIZE, "chunks": 1},
    )
    body3 = r3.text()[:800]
    print(f"PROBE_3 合并: status={r3.status} body={body3}", flush=True)


def main() -> int:
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE),
            channel="msedge",
            headless=False,
            viewport={"width": 1280, "height": 880},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(
                "https://autodl.art/login", timeout=60000, wait_until="domcontentloaded"
            )
        except Exception as exc:
            print(f"NAV_WARN: {exc}", flush=True)
        print("LOGIN_WINDOW_OPEN 请在弹出的窗口里完成登录（扫码或手机号）", flush=True)

        deadline = time.time() + 500
        success = False
        while time.time() < deadline:
            try:
                r = context.request.post(
                    "https://autodl.art/api/v1/file/before_upload",
                    data={"md5": MD5, "file_size": SIZE},
                )
                if r.ok and (r.json() or {}).get("code") == "Success":
                    success = True
                    break
            except Exception:
                pass
            try:
                if not context.pages:
                    print("WINDOW_CLOSED 窗口被关闭，视为放弃", flush=True)
                    break
            except Exception:
                pass
            time.sleep(3)

        if success:
            try:
                context.storage_state(path=str(STATE))
            except Exception as exc:
                print(f"STATE_SAVE_WARN: {exc}", flush=True)
            print("LOGIN_OK 登录态已保存", flush=True)
            try:
                probe_upload(context)
            except Exception as exc:
                print(f"PROBE_WARN: {type(exc).__name__}: {exc}", flush=True)
        else:
            print("LOGIN_TIMEOUT 未检测到登录成功", flush=True)
        time.sleep(2)
        try:
            context.close()
        except Exception:
            pass
        return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
