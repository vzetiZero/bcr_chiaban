"""Controller flow for opening the Dream Gaming lobby from FEBET."""

from aibcr.adapters import febet as FEBET

from .base import SiteEntryController


class FEBETEntryController(SiteEntryController):
    def open_dg(self, _params=None):
        driver = self.browser_driver()
        if driver is None:
            return self.not_ready()
        with self.parent.browser.lock:
            return FEBET.open_dream_gaming_baccarat(driver)

