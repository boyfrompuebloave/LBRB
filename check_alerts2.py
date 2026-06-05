import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.goto('http://localhost:8501', wait_until='domcontentloaded', timeout=60000)
    print("Waiting 35s for all API data...")
    time.sleep(35)

    alerts = page.locator('[data-testid="stAlert"]')
    count = alerts.count()
    print(f"=== {count} Alerts ===")
    for i in range(count):
        txt = alerts.nth(i).inner_text()
        print(f"[{i+1}] {txt[:400]}")

    # Mouse wheel scroll through page
    page.mouse.move(700, 450)
    shots = []
    for i in range(16):
        fname = f'C:/Users/top00/Claudeworks/dashboard/pg_{i:02d}.png'
        page.screenshot(path=fname)
        shots.append(fname)
        page.mouse.wheel(0, 600)
        time.sleep(0.8)

    print(f"Saved {len(shots)} screenshots")
    browser.close()
