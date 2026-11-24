"""Controller flow for 888AE66's Dream Gaming lobby."""

from aibcr.adapters import ae888 as AE888

from .base import SiteEntryController


class AE888EntryController(SiteEntryController):
    def open_dg(self, params=None):
        params = params or {}
        try:
            wait = max(1.0, min(300.0, float(params.get("wait", 180.0))))
        except (TypeError, ValueError):
            wait = 180.0
        driver = self.browser_driver()
        if driver is None:
            return self.not_ready()

        def trace(text, level="info"):
            self.parent.log(text, level)

        with self.parent.browser.lock:
            return AE888.open_dg(driver, wait=wait, log=trace)
