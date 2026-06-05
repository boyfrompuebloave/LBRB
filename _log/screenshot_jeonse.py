import asyncio
from playwright.async_api import async_playwright

async def go():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto("http://localhost:8502", timeout=60000)
        print("waiting 60s...")
        await asyncio.sleep(60)
        await page.evaluate("(() => { var el = document.querySelector('[id=\"jeonse-rate\"]'); if (el) el.scrollIntoView({block: 'start'}); })()")
        await asyncio.sleep(2)
        await page.screenshot(path="C:/Users/top00/Claudeworks/dashboard/_log/jeonse_current.png")
        print("saved jeonse_current.png")
        await browser.close()

asyncio.run(go())
