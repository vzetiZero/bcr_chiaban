"""Controller flow for VNWTop's Dream Gaming lobby."""

from aibcr.adapters import vnwtop as VNW

from .base import SiteEntryController


class VNWTopEntryController(SiteEntryController):
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
            return VNW.open_dg(driver, wait=wait, log=trace)
