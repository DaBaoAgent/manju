from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE = Path(r"D:\@kaifa\manju\deploy\autodl-browser-profile")
MD5, SIZE = "b26b54932ddc1fe476d8a3cb213156d9", 73

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.goto("https://autodl.art/app/market", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print("NAV_WARN:", e)
    cookies = ctx.cookies()
    print("COOKIES NOW:")
    for c in cookies:
        print(f"  {c['name']} @ {c['domain']} len={len(c['value'])}")
    # 是否已登录：页面头部是否还有「登录」按钮
    try:
        logged_out = page.evaluate("() => document.body.innerText.includes('注册') && document.body.innerText.includes('登录')")
        print("仍显示登录/注册按钮(未登录)?", logged_out)
    except Exception:
        pass
    r = ctx.request.post("https://autodl.art/api/v1/file/before_upload",
                         data={"md5": MD5, "file_size": SIZE})
    print("file-api(cookies only):", r.status, r.text()[:180])
    ctx.close()
