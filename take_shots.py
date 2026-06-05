from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.goto('http://localhost:8501', wait_until='networkidle', timeout=60000)

    # Wait for content to fully render (API calls + charts)
    print("Waiting for render...")
    time.sleep(20)

    # Check scroll height after wait
    sh = page.evaluate("document.querySelector('[data-testid=\"stAppViewContainer\"]').scrollHeight")
    print(f"scrollHeight after wait: {sh}")

    # Scroll using keyboard
    page.click('body')
    shots = []
    for i in range(15):
        page.screenshot(path=f'C:/Users/top00/Claudeworks/dashboard/s_{i:02d}.png')
        shots.append(i)
        page.keyboard.press('PageDown')
        time.sleep(1.5)
        new_sh = page.evaluate("document.querySelector('[data-testid=\"stAppViewContainer\"]').scrollHeight")
        wy = page.evaluate("window.scrollY")
        print(f"  shot {i}: scrollY={wy}, containerScrollH={new_sh}")
        if i > 3 and wy == 0:
            # Try scrolling via JS on the container
            page.evaluate("document.querySelector('[data-testid=\"stAppViewContainer\"]').scrollTop += 800")
            time.sleep(1)

    browser.close()
    print("Done:", shots)
