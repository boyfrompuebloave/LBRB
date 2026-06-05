import asyncio
from playwright.async_api import async_playwright

async def go():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto("http://localhost:8502", timeout=60000)
        print("waiting 60s for data to load...")
        await asyncio.sleep(60)
        await page.screenshot(path="C:/Users/top00/Claudeworks/dashboard/_log/sidebar_selectors.png")
        print("saved sidebar_selectors.png")
        await browser.close()

asyncio.run(go())
