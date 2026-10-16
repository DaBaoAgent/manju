from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE = Path(r"D:\@kaifa\manju\deploy\autodl-browser-profile")
OUT = Path(r"D:\@kaifa\manju\deploy\login-page.png")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=True,
                                               viewport={"width": 1280, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://autodl.art/login", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    print("URL:", page.url)
    text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 1200) : '(no body)'")
    print("=== 页面文本 ===")
    print(text)
    imgs = page.evaluate("() => Array.from(document.images).map(i => ({src: (i.src||'').slice(0,90), w: i.naturalWidth, h: i.naturalHeight})).filter(x => x.src)")
    print("=== 图片 ===")
    for im in imgs[:10]:
        print(" ", im)
    page.screenshot(path=str(OUT), full_page=True)
    print("SCREENSHOT:", OUT)
    ctx.close()
