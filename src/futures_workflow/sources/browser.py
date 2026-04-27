from typing import Dict, Tuple


def bootstrap_browser_cookies(start_url: str, user_agent: str, wait_ms: int = 5000) -> Tuple[Dict[str, str], str]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True, user_agent=user_agent, locale="zh-CN")
        page = context.new_page()
        navigation_error = None
        try:
            # Some exchange pages set the needed cookies at DOM ready time but keep
            # loading slow third-party assets long enough to miss the full load
            # event. Treat DOM readiness as sufficient for anti-bot bootstrap.
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightTimeoutError as exc:
            navigation_error = exc
        page.wait_for_timeout(wait_ms)
        content = page.content()
        cookies = {cookie["name"]: cookie["value"] for cookie in context.cookies()}
        browser.close()
        if navigation_error and not cookies and not content.strip():
            raise navigation_error
        return cookies, content
