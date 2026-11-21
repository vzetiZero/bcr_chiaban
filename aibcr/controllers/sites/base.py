"""Shared browser readiness helper for site-entry controllers."""

import time


class SiteEntryController:
    def __init__(self, parent):
        self.parent = parent

    def browser_driver(self):
        deadline = time.monotonic() + 180
        while (self.parent.browser.driver is None and self.parent.chrome_busy
               and time.monotonic() < deadline):
            time.sleep(0.2)
        return self.parent.browser.driver

    @staticmethod
    def not_ready():
        return {"ok": False,
                "error": "Chrome profile ch\u01b0a s\u1eb5n s\u00e0ng sau 180 gi\u00e2y."}

