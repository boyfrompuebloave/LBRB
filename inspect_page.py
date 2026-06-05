from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.goto('http://localhost:8501', wait_until='domcontentloaded', timeout=60000)
    time.sleep(25)

    # Dump page structure
    structure = page.evaluate("""() => {
        function getInfo(el, depth) {
            if (depth > 3) return '';
            let children = Array.from(el.children).map(c => getInfo(c, depth+1)).join('');
            let id = el.id ? '#'+el.id : '';
            let cls = el.className && typeof el.className === 'string' ? '.'+el.className.split(' ').slice(0,2).join('.') : '';
            let dt = el.dataset && el.dataset.testid ? '[data-testid='+el.dataset.testid+']' : '';
            let sh = el.scrollHeight;
            let ch = el.clientHeight;
            return `${' '.repeat(depth*2)}<${el.tagName}${id}${cls}${dt} sh=${sh} ch=${ch}>\\n${children}`;
        }
        return getInfo(document.body, 0).substring(0, 5000);
    }""")
    print(structure)

    # Also check if there's a spinner still running
    spinners = page.locator('[data-testid="stSpinner"]').count()
    print(f"Spinners visible: {spinners}")

    # Check for any error messages
    errors = page.locator('[data-testid="stAlert"]').count()
    print(f"Alerts: {errors}")

    browser.close()
