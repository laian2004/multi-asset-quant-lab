import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.sources.browser import bootstrap_browser_cookies


class _FakeTimeoutError(Exception):
    pass


class _FakePage:
    def __init__(self, *, content="<html></html>", timeout=False):
        self._content = content
        self._timeout = timeout
        self.goto_calls = []
        self.wait_calls = []

    def goto(self, *args, **kwargs):
        self.goto_calls.append((args, kwargs))
        if self._timeout:
            raise _FakeTimeoutError("timed out")

    def wait_for_timeout(self, wait_ms):
        self.wait_calls.append(wait_ms)

    def content(self):
        return self._content


class _FakeContext:
    def __init__(self, *, page, cookies):
        self._page = page
        self._cookies = cookies

    def new_page(self):
        return self._page

    def cookies(self):
        return list(self._cookies)


class _FakeBrowser:
    def __init__(self, *, context):
        self._context = context
        self.closed = False

    def new_context(self, **kwargs):
        return self._context

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, *, browser):
        self._browser = browser

    def launch(self, headless=True):
        return self._browser


class _FakePlaywright:
    def __init__(self, *, chromium):
        self.chromium = chromium


class _FakePlaywrightManager:
    def __init__(self, *, playwright):
        self._playwright = playwright

    def __enter__(self):
        return self._playwright

    def __exit__(self, exc_type, exc, tb):
        return False


class BrowserBootstrapTests(unittest.TestCase):
    def _patch_playwright(self, *, page, cookies):
        context = _FakeContext(page=page, cookies=cookies)
        browser = _FakeBrowser(context=context)
        playwright = _FakePlaywright(chromium=_FakeChromium(browser=browser))
        manager = _FakePlaywrightManager(playwright=playwright)
        return mock.patch("playwright.sync_api.sync_playwright", return_value=manager), browser

    def test_bootstrap_browser_cookies_uses_domcontentloaded_navigation(self):
        page = _FakePage()
        cookie_rows = [{"name": "session", "value": "abc"}]
        patcher, browser = self._patch_playwright(page=page, cookies=cookie_rows)
        with patcher, mock.patch("playwright.sync_api.TimeoutError", _FakeTimeoutError):
            cookies, content = bootstrap_browser_cookies("https://example.com", "ua", wait_ms=1234)

        self.assertEqual(cookies, {"session": "abc"})
        self.assertEqual(content, "<html></html>")
        self.assertEqual(page.goto_calls[0][1]["wait_until"], "domcontentloaded")
        self.assertEqual(page.wait_calls, [1234])
        self.assertTrue(browser.closed)

    def test_bootstrap_browser_cookies_keeps_partial_state_after_timeout(self):
        page = _FakePage(content="<html>partial</html>", timeout=True)
        cookie_rows = [{"name": "session", "value": "abc"}]
        patcher, browser = self._patch_playwright(page=page, cookies=cookie_rows)
        with patcher, mock.patch("playwright.sync_api.TimeoutError", _FakeTimeoutError):
            cookies, content = bootstrap_browser_cookies("https://example.com", "ua")

        self.assertEqual(cookies, {"session": "abc"})
        self.assertEqual(content, "<html>partial</html>")
        self.assertEqual(page.goto_calls[0][1]["wait_until"], "domcontentloaded")
        self.assertTrue(browser.closed)


if __name__ == "__main__":
    unittest.main()
