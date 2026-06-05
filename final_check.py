import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.goto('http://localhost:8501', wait_until='domcontentloaded', timeout=60000)
    print("Waiting 40s for all API calls to complete...")
    time.sleep(40)

    alerts = page.locator('[data-testid="stAlert"]')
    count = alerts.count()
    print(f"=== {count} Alerts ===")
    for i in range(count):
        txt = alerts.nth(i).inner_text()
        print(f"[{i+1}] {txt[:300]}")

    # Screenshots: top, middle, bottom via mouse wheel
    page.screenshot(path='C:/Users/top00/Claudeworks/dashboard/final_00_top.png')
    page.mouse.move(700, 450)
    for i in range(1, 12):
        page.mouse.wheel(0, 700)
        time.sleep(0.8)
        page.screenshot(path=f'C:/Users/top00/Claudeworks/dashboard/final_{i:02d}.png')

    print("Screenshots saved")
    browser.close()
