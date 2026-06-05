from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.goto('http://localhost:8501', wait_until='domcontentloaded', timeout=60000)
    print("Waiting 30s for all API data to load...")
    time.sleep(30)

    # Get all alert texts
    alerts = page.locator('[data-testid="stAlert"]')
    count = alerts.count()
    print(f"\n=== {count} Alerts found ===")
    for i in range(count):
        txt = alerts.nth(i).inner_text()
        print(f"[Alert {i+1}] {txt[:300]}")

    # Get all warning/error/info texts
    for sel, name in [('[data-testid="stNotification"]', 'Notification'),
                      ('.stAlert', 'stAlert class'),
                      ('[data-testid="stMarkdownContainer"]', 'Markdown')]:
        els = page.locator(sel)
        n = els.count()
        if n > 0:
            print(f"\n=== {name}: {n} found ===")

    # Screenshot at current state
    page.screenshot(path='C:/Users/top00/Claudeworks/dashboard/check_state.png')

    # Try scrolling via keyboard after focusing
    page.locator('[data-testid="stScreencast"]').scroll_into_view_if_needed()
    time.sleep(1)

    # Use mouse wheel to scroll
    page.mouse.move(700, 450)
    for i in range(20):
        page.mouse.wheel(0, 500)
        time.sleep(0.3)

    page.screenshot(path='C:/Users/top00/Claudeworks/dashboard/scrolled_state.png')
    print("Screenshots saved")

    browser.close()
