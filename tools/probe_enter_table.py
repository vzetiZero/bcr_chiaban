# -*- coding: utf-8 -*-
"""Kiem chung ``_laya_enter_table`` (chuot that qua Selenium CDP) tren sanh DG.

Vao sanh -> goi ``_laya_enter_table`` -> doc lai ``in_table``/``table_id``.
"""

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aibcr.adapters import browser as BR
from aibcr.adapters import febet as DG
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode")
TABLE = sys.argv[1] if len(sys.argv) > 1 else "60102"


def attach(port=9222):
    major = ""
    try:
        with BR.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=3) as response:
            major = str((json.load(response).get("Browser") or "")).split("/")[-1].split(".")[0]
    except Exception:
        pass
    opts = Options()
    opts.debugger_address = "127.0.0.1:%d" % port
    if major.isdigit():
        opts.browser_version = major
    kind, _why = BR.driver_for()
    service = Service(BR.DRIVER_PATH) if kind == "local" else Service()
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(40)
    driver.set_script_timeout(30)
    driver.implicitly_wait(0)
    return driver


def main():
    driver = attach()
    ctx = DG._dg_context(driver, wait=20.0)
    print("ctx mode:", (ctx or {}).get("mode"), flush=True)
    if not ctx or ctx.get("mode") != "tab":
        print("canh bao: khong phai tab DG", flush=True)
        return 1

    print("\n== ve sanh ==", flush=True)
    left = DG.leave_table(driver, wait=25.0)
    print(" ", json.dumps(left, ensure_ascii=False), flush=True)
    lobby = DG.lobby_tables(driver, wait=15.0)
    rows = lobby.get("tables") or []
    print("  sanh ok=%s so ban=%s" % (lobby.get("ok"), len(rows)), flush=True)
    if not rows:
        print("DUNG: khong ve duoc sanh", flush=True)
        return 1

    print("\n== _laya_enter_table(%s) ==" % TABLE, flush=True)
    name = ""
    for row in rows:
        if str(row.get("table_id")) == TABLE:
            name = str(row.get("name") or "")
    began = time.time()
    entered = DG._laya_enter_table(driver, TABLE, name)
    print("  %.2fs %s" % (time.time() - began, json.dumps(entered, ensure_ascii=False)), flush=True)

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        time.sleep(1.0)
        state = driver.execute_script(DG._DG_STATE_JS) or {}
        print("  in_table=%s label=%s url_table=%s"
              % (state.get("in_table"), state.get("label"), state.get("url_table")), flush=True)
        if state.get("in_table"):
            print("\nVAO BAN BANG getElement + CDP MOUSE: OK", flush=True)
            driver.save_screenshot(str(OUT / "enter_ok.png"))
            return 0
    driver.save_screenshot(str(OUT / "enter_fail.png"))
    print("\nTHAT BAI: van o sanh", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
