from pathlib import Path
import json
from playwright.sync_api import sync_playwright

PROFILE = Path(r"D:\@kaifa\manju\deploy\autodl-browser-profile")
MD5, SIZE = "b26b54932ddc1fe476d8a3cb213156d9", 73

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.goto("https://autodl.art/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print("NAV_WARN:", e)
    cookies = ctx.cookies()
    print("COOKIES:")
    for c in cookies:
        print(f"  {c['name']} @ {c['domain']} len={len(c['value'])} head={c['value'][:8]}")
    ls = page.evaluate("() => { const out={}; for (let i=0;i<localStorage.length;i++){const k=localStorage.key(i); out[k]=String(localStorage.getItem(k)||'').slice(0,50);} return out; }")
    print("LOCALSTORAGE:", json.dumps(ls, ensure_ascii=False))
    r = ctx.request.post("https://autodl.art/api/v1/file/before_upload",
                         data={"md5": MD5, "file_size": SIZE})
    print("file-api(cookies only):", r.status, r.text()[:150])
    for name in ("user_token", "token", "Authorization", "access_token"):
        for c in cookies:
            if c["name"] == name:
                r2 = ctx.request.post("https://autodl.art/api/v1/file/before_upload",
                                      headers={"Authorization": c["value"]},
                                      data={"md5": MD5, "file_size": SIZE})
                print(f"file-api(header {name}={c['value'][:8]}...):", r2.status, r2.text()[:200])
    ctx.close()
