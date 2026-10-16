#!/usr/bin/env python3
"""微信扫码登录 autodl.art（无头浏览器，二维码存图片给用户扫）。
- 每 20s 刷新二维码截图（网站会轮换二维码）
- 每 10s 检测登录态（captured Authorization 头 或 file-api 探测成功）
- 登录成功：保存会话 + 立即跑上传探针（三步协议 + 最终 URL 形态）
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DELIVER = Path(r"D:\@kaifa\manju\deploy")
PROFILE = DELIVER / "autodl-browser-profile"
STATE = DELIVER / "autodl-session.json"
AUTH_FILE = DELIVER / "autodl-web-auth.json"
QR_PNG = DELIVER / "autodl-qr.png"
QR_FULL = DELIVER / "autodl-qr-full.png"
TEST_PNG = Path(r"D:\@kaifa\manju\adapters\selftest\upload-test.png")

MD5 = "b26b54932ddc1fe476d8a3cb213156d9"
SIZE = 73
TOTAL_BUDGET = 1500  # 25 分钟

captured_auth: dict[str, str] = {}


def on_request(request) -> None:
    try:
        if "/api/v1/" not in request.url:
            return
        auth = (request.all_headers().get("authorization") or "").strip()
        if len(auth) > 8:
            captured_auth["authorization"] = auth
            captured_auth["sample_url"] = request.url.split("?")[0]
    except Exception:
        pass


def shot_qr(page) -> None:
    box = None
    best = None
    for el in page.query_selector_all("img,canvas"):
        try:
            bb = el.bounding_box()
            if not bb:
                continue
            w, h = bb["width"], bb["height"]
            if 180 <= w <= 290 and abs(w - h) <= 30:
                cx, cy = bb["x"] + w / 2, bb["y"] + h / 2
                dist = (cx - 640) ** 2 + (cy - 430) ** 2
                if best is None or dist < best:
                    best = dist
                    box = bb
        except Exception:
            continue
    if box:
        clip = {
            "x": max(box["x"] - 20, 0),
            "y": max(box["y"] - 20, 0),
            "width": box["width"] + 40,
            "height": box["height"] + 40,
        }
    else:
        clip = {"x": 620, "y": 250, "width": 330, "height": 330}
    page.screenshot(path=str(QR_PNG), clip=clip)
    page.screenshot(path=str(QR_FULL))


def check_login(ctx) -> bool:
    if "authorization" in captured_auth:
        print("AUTH_HEADER_CAPTURED", flush=True)
        return True
    try:
        r = ctx.request.post(
            "https://autodl.art/api/v1/file/before_upload",
            data={"md5": MD5, "file_size": SIZE},
        )
        if r.ok and (r.json() or {}).get("code") == "Success":
            print("SESSION_API_OK", flush=True)
            return True
    except Exception:
        pass
    return False


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
        print("PROBE_ABORT", flush=True)
        return
    if data.get("quickly_upload"):
        print("PROBE_2 秒传命中", flush=True)
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
    print(f"PROBE_3 合并: status={r3.status} body={r3.text()[:800]}", flush=True)


def main() -> int:
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE),
            channel="msedge",
            headless=True,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ctx.on("request", on_request)
        page.goto("https://autodl.art/app/market", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        page.get_by_text("登录", exact=True).first.click(timeout=10000)
        page.wait_for_timeout(1500)
        page.get_by_text("微信登录", exact=True).first.click(timeout=8000)
        page.wait_for_timeout(3000)
        shot_qr(page)
        print(f"QR_READY {QR_PNG}", flush=True)
        try:
            os.startfile(str(QR_PNG))
        except Exception as exc:
            print(f"OPEN_WARN: {exc}", flush=True)

        start = time.time()
        last_shot = 0.0
        last_check = 0.0
        repop = {90, 300, 600}
        repop_done: set[int] = set()
        logged_in = False
        while time.time() - start < TOTAL_BUDGET:
            elapsed = int(time.time() - start)
            if elapsed - last_shot >= 20:
                last_shot = elapsed
                try:
                    shot_qr(page)
                except Exception:
                    pass
                for mark in sorted(repop - repop_done):
                    if elapsed >= mark:
                        repop_done.add(mark)
                        try:
                            os.startfile(str(QR_PNG))
                        except Exception:
                            pass
                        break
            if elapsed - last_check >= 10:
                last_check = elapsed
                if check_login(ctx):
                    logged_in = True
                    break
            time.sleep(2)

        if logged_in:
            print("LOGIN_OK", flush=True)
            try:
                ctx.storage_state(path=str(STATE))
                AUTH_FILE.write_text(
                    json.dumps({k: v for k, v in captured_auth.items()}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                print(f"SAVE_WARN: {exc}", flush=True)
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)
            except Exception:
                pass
            try:
                probe_upload(ctx, captured_auth.get("authorization", ""))
            except Exception as exc:
                print(f"PROBE_WARN: {type(exc).__name__}: {exc}", flush=True)
        else:
            print("LOGIN_TIMEOUT_BG", flush=True)
        try:
            ctx.close()
        except Exception:
            pass
        return 0 if logged_in else 2


if __name__ == "__main__":
    raise SystemExit(main())
