# -*- coding: utf-8 -*-
"""Chay DUNG luong app tu URL gameRecord -> sanh DG -> vao ban -> doc cua cuoc.

Dung adapter that (``e3951.open_dg``, ``febet.lobby_tables``, ``febet.sync_table``,
``febet.bet_state``, ``febet.stage_bet``) qua Selenium gan vao Chrome CDP 9222,
de kiem chung cac cho vua sua tren site that.

Khong bao gio bam xac nhan cuoc. Chrome co the bi chromedriver dong khi script
thoat (da gap tren may nay), khi do mo lai bang tools/launch_profile_chrome.py.

    python tools/probe_full_flow.py [table_id]
"""

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aibcr.adapters import browser as BR
from aibcr.adapters import e3951 as E
from aibcr.adapters import febet as DG
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

START = "https://e39d5d05qc.e3951.com/m/gameRecord"
TABLE = sys.argv[1] if len(sys.argv) > 1 else "60101"
BET_KEYS = ("ok", "in_table", "table_id", "round_id", "state_id", "countdown",
            "bet_open", "scale", "min_k", "max_k", "balance_k", "balance_known",
            "denominations_k", "error")
OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode")


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
    kind, why = BR.driver_for()
    service = Service(BR.DRIVER_PATH) if kind == "local" else Service()
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(40)
    driver.set_script_timeout(30)
    driver.implicitly_wait(0)
    return driver, why


def log(text, level="info"):
    print("[%s] %s" % (level.upper(), text), flush=True)


def main():
    driver, why = attach()
    print("driver:", why, flush=True)

    print("\n=== 0: mo lai dung URL nguoi dung dua ===", flush=True)
    driver.switch_to.default_content()
    driver.execute_cdp_cmd("Page.navigate", {"url": START})
    time.sleep(6)
    print("  url:", driver.current_url.split("?")[0], flush=True)

    print("\n=== 1: e3951.open_dg (login -> Casino -> DG -> Choi ngay) ===", flush=True)
    began = time.time()
    entry = E.open_dg(driver, wait=180.0, log=log)
    tables = entry.get("tables") or []
    print("  %.1fs ok=%s already=%s tables=%s err=%s"
          % (time.time() - began, entry.get("ok"), entry.get("already_open"),
             len(tables), entry.get("error") or ""), flush=True)
    for row in tables[:8]:
        print("    %s | %s | online=%s" % (row.get("table_id"), row.get("name"),
                                          row.get("online")), flush=True)
    if not entry.get("ok"):
        try:
            driver.save_screenshot(str(OUT / "flow_fail_open.png"))
        except Exception:
            pass
        print("DUNG: khong vao duoc sanh DG.", flush=True)
        return 1

    print("\n=== 2: febet.lobby_tables ===", flush=True)
    lobby = DG.lobby_tables(driver, wait=20.0)
    rows = lobby.get("tables") or []
    print("  ok=%s so ban=%s err=%s" % (lobby.get("ok"), len(rows),
                                        lobby.get("error") or ""), flush=True)
    for row in rows[:8]:
        print("    %s | %s | online=%s" % (row.get("table_id"), row.get("name"),
                                          row.get("online")), flush=True)

    print("\n=== 3: febet.sync_table(%s) ===" % TABLE, flush=True)
    began = time.time()
    sync = DG.sync_table(driver, TABLE, wait=40.0, settle=120.0)
    print("  %.1fs %s" % (time.time() - began,
                          json.dumps({k: v for k, v in sync.items() if k != "tables"},
                                     ensure_ascii=False)), flush=True)
    if not sync.get("ok"):
        driver.save_screenshot(str(OUT / "flow_fail_sync.png"))
        print("DUNG: khong vao duoc ban.", flush=True)
        return 1

    print("\n=== 4: febet.bet_state ===", flush=True)
    state = {}
    for tick in range(10):
        state = DG.bet_state(driver, wait=5.0)
        print("  [%d] %s" % (tick, json.dumps({k: state.get(k) for k in BET_KEYS},
                                              ensure_ascii=False)), flush=True)
        if state.get("ok") and state.get("bet_open"):
            break
        time.sleep(2.0)
    driver.save_screenshot(str(OUT / "flow_bet_state.png"))

    print("\n=== 5: febet.stage_bet (chi xep, KHONG xac nhan) ===", flush=True)
    if not (state.get("ok") and state.get("bet_open")):
        print("  bo qua: ban chua mo cua cuoc.", flush=True)
        return 0
    amount = max(int(state.get("min_k") or 10), 10)
    outcome = DG.stage_bet(driver, "P", amount, state.get("round_id"), confirm=False)
    print("  %s" % json.dumps(outcome, ensure_ascii=False), flush=True)
    driver.save_screenshot(str(OUT / "flow_stage.png"))
    print("\n=== KET THUC (khong bam xac nhan) ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
