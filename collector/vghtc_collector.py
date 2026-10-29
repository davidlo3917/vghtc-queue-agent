#!/usr/bin/env python3
"""
台中榮總 門診燈號收集器 (VGHTC outpatient call-light collector)

定時呼叫台中榮總官網「門診看診進度」背後的公開 API，把每個診間的燈號變化
存進 SQLite，作為之後訓練「到號時間預測模型」的資料。

只用 Python 標準函式庫，Python 3.9+ 即可執行。

用法：
    python vghtc_collector.py run                 # 持續收集（預設每 60 秒一輪）
    python vghtc_collector.py once                # 只跑一輪，測試用
    python vghtc_collector.py run --sections CV,DERM,OPH   # 只收集指定科別
    python vghtc_collector.py export --date 2026-10-22     # 匯出某天資料成 CSV
    python vghtc_collector.py stats               # 看資料庫概況

資料來源：
    POST https://publicmobileappservice20171114025941.azurewebsites.net/api/RegService/CallLightInfo/OPD
    body: {"OPDSection": "<科別代碼 | GETLIST | 空字串=全院>", "OPDRoom": "", "OPDTimeFlag": ""}
    預設每輪只打一次「全院」查詢；沒有診時 API 回 SRESULT=FALSE / 查無資料，視為正常空結果。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

API_URL = (
    "https://publicmobileappservice20171114025941.azurewebsites.net"
    "/api/RegService/CallLightInfo/OPD"
)
# 台灣沒有夏令時間，用固定 UTC+8（Windows 的 Python 沒有內建 IANA 時區資料，避免用 zoneinfo）
TZ = timezone(timedelta(hours=8), "Asia/Taipei")
USER_AGENT = "vghtc-calllight-collector/0.1 (personal research; polite polling)"

log = logging.getLogger("vghtc")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    code        TEXT PRIMARY KEY,      -- 科別代碼，例如 CV
    name        TEXT,                  -- 科別名稱，例如 心臟內科
    group_name  TEXT,                  -- 內科系門診 / 外科系門診 ...
    updated_at  TEXT
);

-- 一個「診次」= 某天 + 午別 + 診間
CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY,
    clinic_date  TEXT NOT NULL,        -- YYYY-MM-DD (台北時間)
    time_flag    TEXT NOT NULL,        -- A=上午 P=下午 N=晚上
    room         TEXT NOT NULL,        -- 診間號
    section      TEXT,                 -- 科別代碼
    section_name TEXT,
    room_place   TEXT,                 -- 例如 門診大樓前棟三樓
    doctor       TEXT,
    notice       TEXT,                 -- 最新公告（請假、停診、中午不休息…）
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    UNIQUE (clinic_date, time_flag, room, section)   -- 含科別：同一診間若被兩個科別列出，分開記，不互相覆蓋
);

-- 只有燈號相關數值「有變化」時才新增一筆，節省空間
CREATE TABLE IF NOT EXISTS observations (
    id             INTEGER PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES sessions(id),
    ts             TEXT NOT NULL,      -- ISO8601，台北時間；這次看到新值的時間
    seen_since     TEXT,               -- 上一次確認這個診次的時間；真正的變化發生在 seen_since 和 ts 之間
    cur_seq        INTEGER,            -- CURSEQ 目前看診號次
    tot_seq        INTEGER,            -- TOTSEQ 最末號
    cur_waiting    INTEGER,            -- CUR_WAITING_CNT 已報到待看診人次
    delay_waiting  INTEGER,            -- DELAY_WAITING_CNT 過號等待人次
    max_delay_seq  INTEGER,            -- MAX_DELAY_OPDSEQ 過號看診號
    doctor         TEXT,               -- 記錄當下醫師（代診時會變）
    reg_seq        TEXT,               -- REGSEQ（抽樣時皆為 null，先存著以防之後有值）
    case_no        TEXT,               -- OPDCaseNo（同上）
    finish_code    TEXT                -- OPDFinishCode（同上，可能是診次結束的標記）
);
CREATE INDEX IF NOT EXISTS idx_obs_session_ts ON observations(session_id, ts);

-- 公告文字變化紀錄（請假、代診、延誤等，之後可當特徵）
CREATE TABLE IF NOT EXISTS notice_changes (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts         TEXT NOT NULL,
    notice     TEXT
);

-- 每一輪輪詢的紀錄，用來分辨「燈號沒動」和「收集器當時沒在跑」
CREATE TABLE IF NOT EXISTS polls (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    sections_ok   INTEGER,
    sections_fail INTEGER,
    records       INTEGER,
    changes       INTEGER,
    failed_sections TEXT                -- 這一輪取得失敗的科別代碼，逗號分隔；用來分辨「沒變化」和「沒抓到」
);
"""

OBS_FIELDS = ("cur_seq", "tot_seq", "cur_waiting", "delay_waiting", "max_delay_seq", "doctor",
              "reg_seq", "case_no", "finish_code")


# ---------------------------------------------------------------- helpers

def now_tpe() -> datetime:
    return datetime.now(TZ)


def to_int(v):
    """API 數值都是字串，空字串或 None 轉成 None。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return s  # 非數字就保留原字串，不要默默變成 NULL；分析時會看到並處理


def clean_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def post_json(api_url: str, body: dict, timeout: float = 15.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_with_retry(api_url: str, body: dict, retries: int = 2) -> dict:
    last_err = None
    for attempt in range(retries + 1):
        try:
            data = post_json(api_url, body)
            if str(data.get("SRESULT", "")).upper() != "TRUE":
                if "查無資料" in str(data.get("SMESSAGE", "")):
                    data["RECORDS"] = []  # 現在沒有診，是正常的空結果，不是錯誤
                    return data
                raise RuntimeError(f"SRESULT={data.get('SRESULT')} SMESSAGE={data.get('SMESSAGE')}")
            return data
        except Exception as e:  # noqa: BLE001 — 連線、逾時、斷線、JSON 壞掉都重試
            last_err = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1) + random.random())
    raise last_err  # type: ignore[misc]


# ---------------------------------------------------------------- database

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)  # 有人用其他工具開著資料庫時，等鎖而不是直接炸掉
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def save_sections(conn: sqlite3.Connection, groups: list[dict]) -> list[str]:
    ts = now_tpe().isoformat(timespec="seconds")
    codes = []
    for g in groups:
        for it in g.get("SECTIONLIST") or []:
            code = clean_str(it.get("OPDSECTION"))
            if not code:
                continue
            codes.append(code)
            conn.execute(
                "INSERT INTO sections(code, name, group_name, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET name=excluded.name, "
                "group_name=excluded.group_name, updated_at=excluded.updated_at",
                (code, clean_str(it.get("SECTIONNMC")), clean_str(g.get("SECTIONGROUPNMC")), ts),
            )
    conn.commit()
    return codes


def upsert_session(conn, rec: dict, clinic_date: str, ts: str) -> tuple[int, str | None]:
    """回傳 (session id, 上一次看到這個診次的時間；新診次為 None)。"""
    key = (clinic_date, clean_str(rec.get("OPDTIMEFLAG")) or "?", clean_str(rec.get("OPDROOM")) or "?",
           clean_str(rec.get("OPDSECTION")))
    row = conn.execute(
        "SELECT id, notice, last_seen FROM sessions "
        "WHERE clinic_date=? AND time_flag=? AND room=? AND section IS ?", key
    ).fetchone()
    doctor = clean_str(rec.get("DRNMC"))
    notice = clean_str(rec.get("OPDMSG"))
    if row is None:
        cur = conn.execute(
            "INSERT INTO sessions(clinic_date, time_flag, room, section, section_name, room_place, "
            "doctor, notice, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?)",
            key + (
                clean_str(rec.get("SECTIONNMC")),
                clean_str(rec.get("OPDROOMPLACE")),
                doctor, notice, ts, ts,
            ),
        )
        sid = cur.lastrowid
        if notice:
            conn.execute("INSERT INTO notice_changes(session_id, ts, notice) VALUES (?,?,?)", (sid, ts, notice))
        return sid, None

    sid, old_notice, old_last_seen = row
    conn.execute(
        "UPDATE sessions SET last_seen=?, doctor=COALESCE(?, doctor), notice=? WHERE id=?",
        (ts, doctor, notice, sid),
    )
    if notice != old_notice:
        conn.execute("INSERT INTO notice_changes(session_id, ts, notice) VALUES (?,?,?)", (sid, ts, notice))
    return sid, old_last_seen


def record_observation(conn, sid: int, rec: dict, ts: str, seen_since: str | None) -> bool:
    """燈號數值跟上一筆不同才寫入。回傳是否有寫入。"""
    obs = {
        "cur_seq": to_int(rec.get("CURSEQ")),
        "tot_seq": to_int(rec.get("TOTSEQ")),
        "cur_waiting": to_int(rec.get("CUR_WAITING_CNT")),
        "delay_waiting": to_int(rec.get("DELAY_WAITING_CNT")),
        "max_delay_seq": to_int(rec.get("MAX_DELAY_OPDSEQ")),
        "doctor": clean_str(rec.get("DRNMC")),
        "reg_seq": clean_str(rec.get("REGSEQ")),
        "case_no": clean_str(rec.get("OPDCaseNo")),
        "finish_code": clean_str(rec.get("OPDFinishCode")),
    }
    last = conn.execute(
        f"SELECT {', '.join(OBS_FIELDS)} FROM observations WHERE session_id=? ORDER BY id DESC LIMIT 1",
        (sid,),
    ).fetchone()
    if last is not None and tuple(last) == tuple(obs[f] for f in OBS_FIELDS):
        return False
    conn.execute(
        f"INSERT INTO observations(session_id, ts, seen_since, {', '.join(OBS_FIELDS)}) "
        f"VALUES (?,?,?,{','.join('?' * len(OBS_FIELDS))})",
        (sid, ts, seen_since) + tuple(obs[f] for f in OBS_FIELDS),
    )
    return True


# ---------------------------------------------------------------- polling

def poll_once(conn, api_url: str, sections: list[str], delay: float) -> dict:
    started = now_tpe()
    poll_id = conn.execute(
        "INSERT INTO polls(started_at) VALUES (?)", (started.isoformat(timespec="seconds"),)
    ).lastrowid
    conn.commit()

    ok = n_records = n_changes = 0
    failed: list[str] = []
    for i, code in enumerate(sections):
        if i:
            time.sleep(delay)
        try:
            data = fetch_with_retry(api_url, {"OPDSection": code, "OPDRoom": "", "OPDTimeFlag": ""})
        except Exception as e:  # noqa: BLE001
            failed.append(code or "ALL")
            log.warning("查詢 %s 失敗：%s", code or "全院", e)
            continue
        ok += 1
        t = now_tpe()
        ts = t.isoformat(timespec="seconds")
        clinic_date = t.date().isoformat()
        for rec in data.get("RECORDS") or []:
            n_records += 1
            sid, seen_since = upsert_session(conn, rec, clinic_date, ts)
            if record_observation(conn, sid, rec, ts, seen_since):
                n_changes += 1
        conn.commit()

    conn.execute(
        "UPDATE polls SET finished_at=?, sections_ok=?, sections_fail=?, records=?, changes=?, "
        "failed_sections=? WHERE id=?",
        (now_tpe().isoformat(timespec="seconds"), ok, len(failed), n_records, n_changes,
         ",".join(failed) or None, poll_id),
    )
    conn.commit()
    return {"ok": ok, "fail": len(failed), "records": n_records, "changes": n_changes,
            "seconds": round((now_tpe() - started).total_seconds(), 1)}


def refresh_sections(conn, api_url: str) -> None:
    """更新 sections 表（科別代碼與名稱）。失敗只影響名稱對照，不影響收集。"""
    try:
        data = fetch_with_retry(api_url, {"OPDSection": "GETLIST", "OPDRoom": "", "OPDTimeFlag": ""})
        save_sections(conn, data.get("RECORDS") or [])
    except Exception as e:  # noqa: BLE001
        log.warning("科別清單取得失敗：%s", e)


def parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def in_active_window(t: datetime, start: dtime, end: dtime, days: set[int]) -> bool:
    return t.isoweekday() in days and start <= t.time() <= end


def cmd_run(args, once: bool = False):
    conn = open_db(args.db)
    refresh_sections(conn, args.api)
    # 預設一輪只打一次 API（OPDSection 空字串 = 全院所有門診診間）；指定 --sections 時才逐科查
    sections = [c.strip().upper() for c in args.sections.split(",") if c.strip()] if args.sections else [""]
    log.info("每輪查詢：%s，資料庫：%s", ",".join(sections) or "全院", Path(args.db).resolve())

    start, end = parse_hhmm(args.start), parse_hhmm(args.end)
    days = {int(d) for d in args.days.split(",")}
    last_section_refresh = time.monotonic()

    while True:
        t = now_tpe()
        if once or in_active_window(t, start, end, days):
            cycle_start = time.monotonic()
            try:
                r = poll_once(conn, args.api, sections, args.delay)
            except Exception:  # noqa: BLE001 — 收集器不能因為一輪出錯就死掉，留下幾天的資料缺口
                log.exception("這一輪發生未預期的錯誤，%s 秒後繼續", args.interval)
                conn.rollback()
                if once:
                    return 1
                time.sleep(args.interval)
                continue
            log.info("一輪完成：請求成功 %(ok)d、失敗 %(fail)d、%(records)d 個診間、"
                     "%(changes)d 筆變化、耗時 %(seconds)ss", r)
            if once:
                return 0 if r["ok"] else 1
            # 每 6 小時更新一次科別名稱表
            if time.monotonic() - last_section_refresh > 6 * 3600:
                refresh_sections(conn, args.api)
                last_section_refresh = time.monotonic()
            elapsed = time.monotonic() - cycle_start
            time.sleep(max(5.0, args.interval - elapsed))
        else:
            time.sleep(60)


# ---------------------------------------------------------------- export / stats

EXPORT_SQL = """
SELECT s.clinic_date, s.time_flag, s.section, s.section_name, s.room, o.doctor,
       o.ts, o.seen_since, o.cur_seq, o.tot_seq, o.cur_waiting, o.delay_waiting, o.max_delay_seq,
       o.reg_seq, o.case_no, o.finish_code
FROM observations o JOIN sessions s ON s.id = o.session_id
WHERE s.clinic_date = ?
ORDER BY s.time_flag, s.room, o.ts
"""


def cmd_export(args):
    conn = open_db(args.db)
    out = args.out or f"vghtc_{args.date}.csv"
    rows = conn.execute(EXPORT_SQL, (args.date,)).fetchall()
    with open(out, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig 讓 Excel 正確顯示中文
        w = csv.writer(f)
        w.writerow(["clinic_date", "time_flag", "section", "section_name", "room", "doctor",
                    "ts", "seen_since", "cur_seq", "tot_seq", "cur_waiting", "delay_waiting",
                    "max_delay_seq", "reg_seq", "case_no", "finish_code"])
        w.writerows(rows)
    print(f"已匯出 {len(rows)} 筆到 {out}")
    return 0


def cmd_stats(args):
    conn = open_db(args.db)
    q = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
    print(f"資料庫：{Path(args.db).resolve()}")
    print(f"科別數：{q('SELECT COUNT(*) FROM sections')}")
    print(f"診次數：{q('SELECT COUNT(*) FROM sessions')}")
    print(f"燈號變化筆數：{q('SELECT COUNT(*) FROM observations')}")
    print(f"輪詢次數：{q('SELECT COUNT(*) FROM polls')}")
    print(f"收集天數：{q('SELECT COUNT(DISTINCT clinic_date) FROM sessions')}")
    last = conn.execute("SELECT started_at, sections_ok, sections_fail, changes FROM polls "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    if last:
        print(f"最近一輪：{last[0]}（成功 {last[1]}、失敗 {last[2]}、變化 {last[3]}）")
    print("\n今天變化最多的 5 個診間：")
    today = now_tpe().date().isoformat()
    for row in conn.execute(
        "SELECT s.room, s.time_flag, s.section_name, s.doctor, COUNT(*) c FROM observations o "
        "JOIN sessions s ON s.id=o.session_id WHERE s.clinic_date=? GROUP BY s.id ORDER BY c DESC LIMIT 5",
        (today,),
    ):
        print(f"  {row[0]} {row[1]} {row[2]} {row[3]}：{row[4]} 筆")
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(description="台中榮總門診燈號收集器")
    p.add_argument("--db", default="vghtc_calllight.db", help="SQLite 檔案路徑")
    p.add_argument("--api", default=API_URL, help=argparse.SUPPRESS)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("run", "once"):
        sp = sub.add_parser(name, help="持續收集" if name == "run" else "只跑一輪（測試用）")
        sp.add_argument("--sections", help="改成逐科查詢，只收這些科別代碼，逗號分隔，例如 CV,DERM,OPH"
                                           "（預設一次查全院，但全院查詢不含檢查室，要收檢查室用 --sections ENDO,PSON）")
        sp.add_argument("--interval", type=float, default=60, help="每輪間隔秒數（預設 60，與官網自動刷新相同）")
        sp.add_argument("--delay", type=float, default=0.5, help="逐科查詢時，每個科別請求之間的間隔秒數")
        sp.add_argument("--start", default="07:30", help="每天開始收集時間（台北時間）")
        sp.add_argument("--end", default="22:30", help="每天結束收集時間（台北時間）")
        sp.add_argument("--days", default="1,2,3,4,5,6", help="收集星期幾，1=週一…7=週日")

    ex = sub.add_parser("export", help="匯出某天資料為 CSV")
    ex.add_argument("--date", default=now_tpe().date().isoformat(), help="YYYY-MM-DD，預設今天")
    ex.add_argument("--out", help="輸出檔名")

    sub.add_parser("stats", help="顯示資料庫概況")

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        if args.cmd == "run":
            return cmd_run(args)
        if args.cmd == "once":
            return cmd_run(args, once=True)
        if args.cmd == "export":
            return cmd_export(args)
        if args.cmd == "stats":
            return cmd_stats(args)
    except KeyboardInterrupt:
        log.info("已停止。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
