"""Controller flow for GK881's DG navigation menu and popup tab."""

from aibcr.adapters import gk881 as GK881

from .base import SiteEntryController


class GK881EntryController(SiteEntryController):
    def open_dg(self, params=None):
        params = params or {}
        try:
            wait = max(1.0, min(180.0, float(params.get("wait", 120.0))))
        except (TypeError, ValueError):
            wait = 120.0
        driver = self.browser_driver()
        if driver is None:
            return self.not_ready()
        with self.parent.browser.lock:
            return GK881.open_dg(driver, wait=wait)

