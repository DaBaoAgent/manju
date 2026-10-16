#!/usr/bin/env python3
"""改进版登录流程：自动点开登录弹窗 → 拦截网络请求捕获认证头 →
登录成功后保存会话与认证材料 → 立即跑上传探针（拿最终文件 URL）。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DELIVER = Path(r"D:\@kaifa\manju\deploy")
PROFILE = DELIVER / "autodl-browser-profile"
STATE = DELIVER / "autodl-session.json"
AUTH_FILE = DELIVER / "autodl-web-auth.json"
TEST_PNG = Path(r"D:\@kaifa\manju\adapters\selftest\upload-test.png")

MD5 = "b26b54932ddc1fe476d8a3cb213156d9"
SIZE = 73

captured_auth: dict[str, str] = {}


def on_request(request) -> None:
    try:
        url = request.url
        if "/api/v1/" not in url:
            return
        headers = request.all_headers()
        auth = headers.get("authorization") or ""
        if len(auth) > 8:
            captured_auth["authorization"] = auth
            captured_auth["sample_url"] = url.split("?")[0]
    except Exception:
        pass


def probe_upload(ctx, auth_header: str) -> None:
    payload = TEST_PNG.read_bytes()
    headers = {"Authorization": auth_header} if auth_header else {}
    r1 = ctx.request.post(
        "https://autodl.art/api/v1/file/before_upload",
        headers=headers,
        data={"md5": MD5, "file_size": SIZE},
    )
    b1 = r1.json()
    print("PROBE_1 before_upload:", json.dumps(b1, ensure_ascii=False)[:400], flush=True)
    data = b1.get("data") or {}
    token, host = data.get("token"), data.get("host")
    if not token or not host:
        print("PROBE_ABORT 无 token/host", flush=True)
        return
    if data.get("quickly_upload"):
        print("PROBE_2 秒传命中（跳过上传）", flush=True)
    else:
        r2 = ctx.request.put(
            f"{host}/api/v1/file",
            headers={**headers, "FileToken": token},
            multipart={
                "md5": MD5,
                "chunk": "0",
                "chunks": "1",
                "chunk_size": str(SIZE),
                "file": {"name": "upload-test.png", "mimeType": "image/png", "buffer": payload},
            },
        )
        print(f"PROBE_2 PUT: status={r2.status} body={r2.text()[:400]}", flush=True)
    r3 = ctx.request.post(
        f"{host}/api/v1/file",
        headers={**headers, "FileToken": token},
        data={"md5": MD5, "total_size": SIZE, "chunks": 1},
    )
    print(f"PROBE_3 合并: status={r3.status} body={r3.text()[:600]}", flush=True)


def main() -> int:
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE),
            channel="msedge",
            headless=False,
            viewport={"width": 1280, "height": 880},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ctx.on("request", on_request)
        try:
            page.goto("https://autodl.art/app/market", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            page.get_by_text("登录", exact=True).first.click(timeout=10000)
            page.wait_for_timeout(1500)
        except Exception as exc:
            print(f"UI_WARN: {type(exc).__name__}: {exc}", flush=True)
        print("LOGIN_MODAL_OPEN 请在窗口里登录（手机号/微信/短信均可）", flush=True)

        deadline = time.time() + 480
        logged_in = False
        last_api_check = 0.0
        while time.time() < deadline:
            if "authorization" in captured_auth:
                logged_in = True
                print("AUTH_HEADER_CAPTURED", flush=True)
                break
            now = time.time()
            if now - last_api_check >= 10:
                last_api_check = now
                try:
                    r = ctx.request.post(
                        "https://autodl.art/api/v1/file/before_upload",
                        data={"md5": MD5, "file_size": SIZE},
                    )
                    if r.ok and (r.json() or {}).get("code") == "Success":
                        logged_in = True
                        print("SESSION_API_OK", flush=True)
                        break
                except Exception:
                    pass
            if not ctx.pages:
                print("WINDOW_CLOSED", flush=True)
                break
            time.sleep(2)

        if logged_in:
            print(
                f"LOGIN_OK（认证头捕获: {'是' if 'authorization' in captured_auth else '否'}，来自 {captured_auth.get('sample_url', 'API 探测')}）",
                flush=True,
            )
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
            except Exception:
                pass
            try:
                ctx.storage_state(path=str(STATE))
                AUTH_FILE.write_text(
                    json.dumps(captured_auth, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"AUTH_SAVED {AUTH_FILE}", flush=True)
            except Exception as exc:
                print(f"SAVE_WARN: {exc}", flush=True)
            page.wait_for_timeout(1000)
            try:
                probe_upload(ctx, captured_auth.get("authorization", ""))
            except Exception as exc:
                print(f"PROBE_WARN: {type(exc).__name__}: {exc}", flush=True)
        else:
            print("LOGIN_TIMEOUT", flush=True)
        page.wait_for_timeout(2000)
        try:
            ctx.close()
        except Exception:
            pass
        return 0 if logged_in else 2


if __name__ == "__main__":
    raise SystemExit(main())
