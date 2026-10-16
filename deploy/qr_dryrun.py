from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE = Path(r"D:\@kaifa\manju\deploy\autodl-browser-profile")
OUT = Path(r"D:\@kaifa\manju\deploy\qr-dryrun.png")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=True,
                                               viewport={"width": 1280, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://autodl.art/app/market", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    page.get_by_text("登录", exact=True).first.click(timeout=10000)
    page.wait_for_timeout(2000)
    try:
        page.get_by_text("微信登录", exact=True).first.click(timeout=8000)
        print("点击微信登录 OK")
    except Exception as e:
        print("点击微信登录失败:", e)
    page.wait_for_timeout(5000)
    print("pages:", len(ctx.pages))
    print("url:", page.url)
    if len(ctx.pages) > 1:
        page = ctx.pages[-1]
        print("最新页 url:", page.url)
    # 找二维码候选元素
    cands = page.evaluate("() => Array.from(document.querySelectorAll('img,canvas')).map((el,i) => ({i, tag: el.tagName, src: (el.src||'').slice(0,110), w: el.naturalWidth||el.width, h: el.naturalHeight||el.height, vis: !!(el.offsetParent)})).filter(x => x.vis && x.w>=100 && x.w<=400 && Math.abs(x.w-x.h)<=40)")
    print("二维码候选:")
    for c in cands[:8]:
        print(" ", c)
    page.screenshot(path=str(OUT))
    print("SCREENSHOT:", OUT)
    ctx.close()
