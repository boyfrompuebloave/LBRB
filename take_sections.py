from playwright.sync_api import sync_playwright
import time, os

shots_dir = "C:/Users/top00/Claudeworks/dashboard/_screenshots"
os.makedirs(shots_dir, exist_ok=True)

js_scroll = """
(y) => {
    var el = document.querySelector('[data-testid="stMain"]');
    if (el) { el.scrollTop = y; return true; }
    window.scrollTo(0, y);
    return false;
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501", wait_until="networkidle", timeout=60000)
    time.sleep(8)

    sections = [0, 900, 1800, 2700, 3600, 4500, 5400, 6300, 7200]
    for i, y in enumerate(sections):
        page.evaluate(js_scroll, y)
        time.sleep(1.8)
        path = f"{shots_dir}/sec_{i:02d}_{y}.png"
        page.screenshot(path=path)
        print("saved", path)

    browser.close()
print("done")
