from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.goto('http://localhost:8501', wait_until='networkidle', timeout=30000)
    time.sleep(10)

    # Check frames
    frames = page.frames
    print(f'Frames: {len(frames)}')
    for f in frames:
        print(f'  {f.url}')

    # Find the scrollable container
    info = page.evaluate("""() => {
        let candidates = ['section.main', '.main .block-container', '[data-testid="stAppViewContainer"]', 'body'];
        for (let sel of candidates) {
            let el = document.querySelector(sel);
            if (el) return {sel: sel, scrollH: el.scrollHeight, clientH: el.clientHeight};
        }
        return {body: document.body.scrollHeight};
    }""")
    print(f'Container info: {info}')

    # Try scrolling the window and take shots
    for y in [0, 2000, 4000, 6000, 8000, 10000]:
        page.keyboard.press('End')
        page.evaluate(f"window.scrollY")
        actual_y = page.evaluate("window.scrollY")
        print(f"scrollY={actual_y}")

    browser.close()
