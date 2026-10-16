from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE = Path(r"D:\@kaifa\manju\deploy\autodl-browser-profile")
OUT = Path(r"D:\@kaifa\manju\deploy\login-modal.png")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=True,
                                               viewport={"width": 1280, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://autodl.art/app/market", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    # 点击「登录」
    try:
        page.get_by_text("登录", exact=True).first.click(timeout=10000)
    except Exception as e:
        print("CLICK_LOGIN_WARN:", e)
    page.wait_for_timeout(4000)
    print("URL:", page.url)
    text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 1500) : ''")
    print("=== 弹窗/页面文本 ===")
    print(text[-1200:])
    # 找可能的二维码图
    imgs = page.evaluate("() => Array.from(document.querySelectorAll('img,canvas')).map(i => ({tag: i.tagName, src: (i.src||'').slice(0,100), w: i.naturalWidth||i.width, h: i.naturalHeight||i.height})).filter(x => (x.w||0) > 80)")
    print("=== 大图/画布 ===")
    for im in imgs[:12]:
        print(" ", im)
    page.screenshot(path=str(OUT))
    print("SCREENSHOT:", OUT)
    ctx.close()
