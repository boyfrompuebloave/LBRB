import asyncio
from playwright.async_api import async_playwright

async def go():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto("http://localhost:8502", timeout=60000)
        print("waiting 55s...")
        await asyncio.sleep(55)

        # Find Streamlit's main scrollable container and scroll to apartment section
        await page.evaluate("""
            (() => {
                var anchors = document.querySelectorAll('[id="apt-price"]');
                if (anchors.length > 0) { anchors[0].scrollIntoView(); }
            })()
        """)
        await asyncio.sleep(3)
        await page.screenshot(path="C:/Users/top00/Claudeworks/dashboard/_log/apt_view.png")
        print("saved apt_view.png")

        await browser.close()

asyncio.run(go())
