"""Controller flow for E3951's Dream Gaming lobby."""

from aibcr.adapters import e3951 as E3951

from .base import SiteEntryController


class E3951EntryController(SiteEntryController):
    def open_dg(self, params=None):
        params = params or {}
        try:
            wait = max(1.0, min(180.0, float(params.get("wait", 150.0))))
        except (TypeError, ValueError):
            wait = 150.0
        driver = self.browser_driver()
        if driver is None:
            return self.not_ready()

        def trace(text, level="info"):
            self.parent.log(text, level)

        with self.parent.browser.lock:
            return E3951.open_dg(driver, wait=wait, log=trace)
