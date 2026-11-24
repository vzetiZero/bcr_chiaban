"""Lưu và khôi phục phiên đăng nhập site (cookie + localStorage) giữa các lần mở.

Vì sao cần: người dùng đăng nhập một lần, sau đó app tự mở/đóng Chrome nhiều lần.
Chrome tự lưu cookie vào thư mục profile, nhưng webview site vẫn có thể mất phiên
khi (a) profile bị dọn, (b) site dùng localStorage cho token, (c) phiên bị reset
do mở hai cửa sổ cùng lúc. Bản lưu này tạo một bản sao dự phòng để nạp lại.

Bảo mật: tệp chứa cookie đăng nhập thật, nên
  * chỉ ghi trong thư mục profile của người dùng (đã nằm trong ``.gitignore``),
  * không bao giờ trả token ra log/UI: ``describe()`` chỉ trả số lượng và tên miền,
  * nội dung tệp không được đưa vào thông báo lỗi.
"""

import json
import os
import time

# Chỉ lưu những gì cần để dựng lại phiên; không lưu toàn bộ localStorage của site
# (có thể rất lớn và chứa dữ liệu không liên quan).
MAX_LOCAL_ITEMS = 80
MAX_LOCAL_VALUE = 20000


def session_path(profile_dir, name="session"):
    """Đường dẫn tệp phiên cho một thư mục profile Chrome.

    Đặt cạnh thư mục profile (``chrome_profile/session-gk881.json``) để khi
    ``.gitignore`` bỏ qua ``chrome_profile*/`` thì tệp cũng không bị commit.
    """
    directory = str(profile_dir or "").strip() or "."
    return os.path.join(directory, "session-%s.json" % _safe_name(name))


def _safe_name(value):
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_") else "-"
                      for ch in str(value or "session"))
    return cleaned.strip("-") or "session"


def _read_cookies(driver):
    """Đọc cookie của **mọi** tên miền trong profile, không chỉ tab đang mở.

    ``driver.get_cookies()`` chỉ trả cookie thuộc origin hiện tại. Sau khi GK881
    chuyển sang sảnh DG (``new-dd-cn…``) nó không còn thấy cookie ``gk881``, nên
    bước lưu phiên cuối lượt chạy ghi ra ``cookies: 0`` — đo được trên đĩa: tệp
    phiên của profile 1 chỉ còn 105 byte trong khi profile 2 có 10 cookie.
    ``Network.getAllCookies`` (CDP) trả toàn bộ cookie của profile.
    """
    try:
        result = driver.execute_cdp_cmd("Network.getAllCookies", {}) or {}
        cookies = result.get("cookies")
        if cookies:
            out = []
            for item in cookies:
                if not item.get("name"):
                    continue
                expiry = item.get("expires")
                try:
                    # CDP trả -1 cho session cookie; Selenium chỉ nhận số dương.
                    expiry = int(expiry) if expiry is not None and int(expiry) > 0 else None
                except (TypeError, ValueError):
                    expiry = None
                out.append({"name": item.get("name"), "value": item.get("value"),
                            "domain": item.get("domain"), "path": item.get("path"),
                            "expiry": expiry, "secure": item.get("secure"),
                            "httpOnly": item.get("httpOnly"),
                            "sameSite": item.get("sameSite")})
            return out
    except Exception:
        pass
    return driver.get_cookies() or []


def save(driver, profile_dir, name="session", domains=None):
    """Ghi cookie + localStorage hiện tại của ``driver`` xuống đĩa.

    ``domains`` giới hạn tên miền được lưu (mặc định: mọi tên miền đang thấy).
    Trả ``{"ok": bool, "cookies": n, "local": n, "path": ...}`` và không bao giờ
    chứa giá trị cookie/token.
    """
    if driver is None:
        return {"ok": False, "error": "Chưa mở Chrome nên không lưu được phiên."}
    try:
        cookies = _read_cookies(driver)
    except Exception:
        return {"ok": False, "error": "Không đọc được cookie của phiên."}
    seen = len(cookies)
    if domains:
        wanted = tuple(str(item).lower() for item in domains)
        cookies = [c for c in cookies
                   if any(wanted_item in str(c.get("domain") or "").lower()
                          for wanted_item in wanted)]
    # Chỉ giữ trường cần để nạp lại; bỏ các trường do Selenium thêm vào.
    keep = ("name", "value", "domain", "path", "expiry", "secure",
            "httpOnly", "sameSite")
    cookies = [{key: c[key] for key in keep if key in c} for c in cookies
               if c.get("name")]

    local = {}
    try:
        local = _read_local_storage(driver)
    except Exception:
        local = {}

    # Không bao giờ thay một phiên thật bằng bản rỗng. Sau khi sảnh DG mở, tab
    # đã sang tên miền nhà cung cấp (``new-dd-cn…``) nên bộ lọc ``gk881`` không
    # khớp cookie nào và localStorage là của trang khác. Đo được: profile 1 lưu
    # 7 cookie, chạy xong một lượt thành công thì tệp còn ``cookies: 0`` — tức
    # là lần sau mất phiên vì chính lần lưu "thành công".
    previous = load(profile_dir, name) or {}
    if not cookies and previous.get("cookies"):
        cookies = list(previous.get("cookies") or [])
    merged_local = dict(previous.get("local") or {})
    merged_local.update(local)

    payload = {"format": "bcr-session-v1", "saved_at": time.time(),
               "cookies": cookies, "local": merged_local}
    path = session_path(profile_dir, name)
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        return {"ok": False, "error": "Không ghi được tệp phiên."}
    return {"ok": True, "cookies": len(cookies), "local": len(merged_local),
            "path": path, "seen": seen}


def _read_local_storage(driver):
    script = """
    return (() => {
      const out = {};
      try {
        for (let i = 0; i < localStorage.length && i < %d; i++) {
          const key = localStorage.key(i);
          if (!key) continue;
          let value = String(localStorage.getItem(key) || '');
          if (value.length > %d) value = value.slice(0, %d);
          out[key] = value;
        }
      } catch (error) {}
      return out;
    })()
    """ % (MAX_LOCAL_ITEMS, MAX_LOCAL_VALUE, MAX_LOCAL_VALUE)
    try:
        return driver.execute_script(script) or {}
    except Exception:
        return {}


def load(profile_dir, name="session"):
    """Đọc tệp phiên; trả ``None`` khi chưa có hoặc tệp hỏng."""
    path = session_path(profile_dir, name)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("cookies"), list):
        return None
    return data


def restore(driver, profile_dir, name="session", url=None):
    """Nạp lại cookie/localStorage đã lưu vào ``driver``.

    Cookie được thêm qua WebDriver (đúng tên miền mới có tác dụng), rồi
    localStorage được ghi lại trên ``url`` vì nó gắn với từng origin. Không bao
    giờ ném lỗi: mục tiêu là "thử khôi phục", còn nếu site vẫn hết phiên thì
    ``open_dg`` sẽ chờ người dùng đăng nhập.
    """
    data = load(profile_dir, name)
    if not data:
        return {"ok": False, "found": False, "cookies": 0}
    if driver is None:
        return {"ok": False, "found": True, "cookies": 0}

    cookies = [cookie for cookie in (data.get("cookies") or [])
               if cookie.get("name") and cookie.get("domain")]
    # WebDriver chỉ nhận cookie cho origin đang mở; trên ``about:blank`` (đúng
    # trạng thái một profile vừa khởi động) mọi ``add_cookie`` đều ném
    # InvalidCookieDomainException. Không điều hướng trước thì "khôi phục phiên"
    # im lặng không thêm được cookie nào — đo được trên profile mới mở.
    # Chỉ điều hướng khi tab còn trắng: nếu đang ở sảnh/bàn DG (tên miền khác
    # hẳn) thì ``driver.get`` sẽ phá mất phiên vừa mở.
    if cookies and _is_blank(driver):
        if not url:
            return {"ok": False, "found": True, "cookies": 0,
                    "reason": "no_origin"}
        try:
            driver.get(url)
        except Exception:
            return {"ok": False, "found": True, "cookies": 0,
                    "reason": "navigate_failed"}

    added = 0
    for cookie in cookies:
        item = {key: cookie[key] for key in
                ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite")
                if key in cookie}
        expiry = cookie.get("expiry")
        if expiry is not None:
            try:
                # Selenium chỉ nhận expiry dạng số nguyên.
                item["expiry"] = int(expiry)
            except (TypeError, ValueError):
                item.pop("expiry", None)
        try:
            driver.add_cookie(item)
            added += 1
        except Exception:
            continue
    local = data.get("local") or {}
    if local:
        script = """
        const items = arguments[0] || {};
        let written = 0;
        try {
          for (const key of Object.keys(items)) {
            localStorage.setItem(key, String(items[key]));
            written++;
          }
        } catch (error) {}
        return written;
        """
        try:
            driver.execute_script(script, local)
        except Exception:
            pass
    return {"ok": added > 0, "found": True, "cookies": added,
            "local": len(local)}


def _is_blank(driver):
    """Tab còn trắng (chưa có origin) thì chưa nhận được cookie nào."""
    try:
        url = str(getattr(driver, "current_url", "") or "").strip().lower()
    except Exception:
        return False
    if not url:
        return True
    return url.startswith("about:") or url.startswith("data:") or url.startswith("chrome:")


def describe(profile_dir, name="session"):
    """Thông tin an toàn để hiện trên UI: không có giá trị cookie/token."""
    data = load(profile_dir, name)
    if not data:
        return {"found": False}
    cookies = data.get("cookies") or []
    domains = sorted({str(item.get("domain") or "") for item in cookies if item.get("domain")})
    saved = data.get("saved_at")
    try:
        saved_text = time.strftime("%d/%m/%Y %H:%M", time.localtime(float(saved)))
    except (TypeError, ValueError, OSError):
        saved_text = ""
    return {"found": True, "cookies": len(cookies),
            "local": len(data.get("local") or {}), "domains": domains[:6],
            "saved_at": saved_text}


def clear(profile_dir, name="session"):
    try:
        os.remove(session_path(profile_dir, name))
        return {"ok": True}
    except OSError:
        return {"ok": False}
