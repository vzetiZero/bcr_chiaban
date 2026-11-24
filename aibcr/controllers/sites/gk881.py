"""Controller flow for GK881's DG navigation menu and popup tab."""

from aibcr.adapters import browser as BR
from aibcr.adapters import gk881 as GK881
from aibcr.adapters import session_store as SESSIONS

from .base import SiteEntryController


class GK881EntryController(SiteEntryController):
    def profile_dir(self):
        """Thư mục profile đang dùng.

        ``BrowserSession`` không tự giữ đường dẫn: engine gán ``BR.PROFILE_DIR``
        theo từng profile (``chrome_profile``, ``chrome_profile_2``…), nên phải
        đọc biến module. Ghi cookie vào sai profile sẽ làm lần khôi phục sau vô
        nghĩa (mỗi profile có phiên riêng).
        """
        return str(getattr(self.parent.browser, "profile_dir", "") or BR.PROFILE_DIR or "")

    def open_dg(self, params=None):
        params = params or {}
        try:
            wait = max(1.0, min(180.0, float(params.get("wait", 120.0))))
        except (TypeError, ValueError):
            wait = 120.0
        driver = self.browser_driver()
        if driver is None:
            return self.not_ready()

        def trace(text, level="info"):
            self.parent.log(text, level)

        profile_dir = self.profile_dir()
        with self.parent.browser.lock:
            # A saved session restores cookies before the run so the site does not
            # ask for a sign-in the operator already did once.
            restored = {}
            if profile_dir and not params.get("no_restore"):
                restored = SESSIONS.restore(driver, profile_dir, "gk881",
                                            url="https://m.gk881.vip/")
                if restored.get("cookies"):
                    trace("GK881 · Đã khôi phục phiên đã lưu (%s cookie)."
                          % restored["cookies"])
            try:
                return GK881.open_dg(driver, wait=wait, log=trace)
            finally:
                # Save after every run: the site may have refreshed its session
                # during the flow, and that newer state is what should survive.
                if profile_dir:
                    saved = SESSIONS.save(driver, profile_dir, "gk881",
                                          domains=["gk881"])
                    if saved.get("cookies"):
                        trace("GK881 · Đã lưu phiên (%s cookie) để lần sau không "
                              "phải đăng nhập lại." % saved["cookies"])

    def session_info(self):
        profile_dir = self.profile_dir()
        if not profile_dir:
            return {"found": False}
        return SESSIONS.describe(profile_dir, "gk881")

    def session_clear(self):
        profile_dir = self.profile_dir()
        if not profile_dir:
            return {"ok": False, "error": "Chưa mở profile nên chưa có phiên để xoá."}
        return SESSIONS.clear(profile_dir, "gk881")
