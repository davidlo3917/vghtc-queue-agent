#!/usr/bin/env python3
"""
產生 status.json（收集狀況摘要）給監控網頁用，並上傳到 bucket。只用標準函式庫。

    python3 status.py --db /opt/vghtc/data/vghtc_calllight.db --bucket gs://xxx   # VM 上由 systemd timer 每 5 分鐘跑
    python3 status.py --db some.db --no-upload                                     # 本機看看內容
    python3 status.py --selftest                                                   # 自我檢查
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8), "Asia/Taipei")
WINDOW = {"start": "07:30", "end": "22:30", "days": [1, 2, 3, 4, 5, 6]}  # 跟收集器預設一致
GAP_SECONDS = 180  # 收集時段內兩輪相隔超過這個秒數就算缺口


def in_window(t: datetime) -> bool:
    return t.isoweekday() in WINDOW["days"] and WINDOW["start"] <= t.strftime("%H:%M") <= WINDOW["end"]


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:  # noqa: BLE001 — 本機沒有 systemctl/journalctl 時回空字串
        return ""


def gaps_today(polls: list[datetime], now: datetime) -> list[list[str]]:
    """polls 是今天每一輪的開始時間（遞增）。回傳 [[開始, 結束], ...]，正在進行中的缺口結束為 None。
    從收集時段開始（07:30）到第一輪之間太久也算缺口。"""
    gaps = []
    h, m = map(int, WINDOW["start"].split(":"))
    day_start = datetime.combine(now.date(), dtime(h, m), TZ)
    if now.isoweekday() in WINDOW["days"] and now > day_start:
        first = polls[0] if polls else now
        if (first - day_start).total_seconds() > GAP_SECONDS:
            gaps.append([WINDOW["start"], first.strftime("%H:%M") if polls else None])
    prev = None
    for t in polls:
        if prev and (t - prev).total_seconds() > GAP_SECONDS and in_window(prev):
            gaps.append([prev.strftime("%H:%M"), t.strftime("%H:%M")])
        prev = t
    if prev and in_window(now) and (now - prev).total_seconds() > GAP_SECONDS:
        gaps.append([prev.strftime("%H:%M"), None])
    return gaps


def compute(conn: sqlite3.Connection, now: datetime, db_path: Path, schedules_dir: Path) -> dict:
    q = lambda sql, *p: conn.execute(sql, p).fetchall()  # noqa: E731
    one = lambda sql, *p: conn.execute(sql, p).fetchone()  # noqa: E731
    today = now.date().isoformat()

    started = one("SELECT started_at FROM polls ORDER BY id DESC LIMIT 1")
    # 統計數字取最後一輪「已完成」的，免得剛好抓到進行中的那一輪（finished_at 還是空的）
    last = one("SELECT started_at, finished_at, sections_ok, sections_fail, records, changes "
               "FROM polls WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    collector = {
        "last_poll_started": started[0] if started else None,
        "last_poll_finished": last[1] if last else None,
        "last_poll_ok": last[2] if last else None,
        "last_poll_fail": last[3] if last else None,
        "last_poll_records": last[4] if last else None,
        "last_poll_changes": last[5] if last else None,
        "service_active": (sh(["systemctl", "is-active", "vghtc-collector"]) or None),
        "restarts": int(sh(["systemctl", "show", "-p", "NRestarts", "--value", "vghtc-collector"]) or 0),
    }

    polls_today = [datetime.fromisoformat(r[0]) for r in
                   q("SELECT started_at FROM polls WHERE started_at LIKE ? ORDER BY id", today + "%")]
    last_err = one("SELECT started_at, failed_sections FROM polls "
                   "WHERE failed_sections IS NOT NULL ORDER BY id DESC LIMIT 1")
    hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    dur = one("SELECT AVG(strftime('%s', finished_at) - strftime('%s', started_at)), "
              "MAX(strftime('%s', finished_at) - strftime('%s', started_at)) "
              "FROM polls WHERE started_at LIKE ? AND finished_at IS NOT NULL", today + "%")
    today_stats = {
        "date": today,
        "polls": len(polls_today),
        "failed_polls": one("SELECT COUNT(*) FROM polls WHERE started_at LIKE ? AND sections_fail > 0", today + "%")[0],
        "changes": one("SELECT COUNT(*) FROM observations WHERE ts LIKE ?", today + "%")[0],
        "changes_last_hour": one("SELECT COUNT(*) FROM observations WHERE ts >= ?", hour_ago)[0],
        "last_change_ts": one("SELECT MAX(ts) FROM observations")[0],
        "poll_seconds_avg": round(dur[0], 1) if dur and dur[0] is not None else None,
        "poll_seconds_max": int(dur[1]) if dur and dur[1] is not None else None,
        "sessions": {r[0]: r[1] for r in q("SELECT time_flag, COUNT(*) FROM sessions WHERE clinic_date=? GROUP BY 1", today)},
        "gaps": gaps_today(polls_today, now),
        "last_error": {"ts": last_err[0], "failed": last_err[1]} if last_err else None,
    }

    # 今天每個診次的最新狀態（給 /data 頁用）
    cols = ["time_flag", "section", "section_name", "room", "doctor", "cur_seq", "tot_seq", "cur_waiting",
            "delay_waiting", "max_delay_seq", "changes", "last_change", "first_seen", "last_seen"]
    sessions_today = [dict(zip(cols, r)) for r in q(
        "SELECT s.time_flag, s.section, s.section_name, s.room, s.doctor, "
        "       o.cur_seq, o.tot_seq, o.cur_waiting, o.delay_waiting, o.max_delay_seq, "
        "       (SELECT COUNT(*) FROM observations WHERE session_id = s.id), o.ts, s.first_seen, s.last_seen "
        "FROM sessions s LEFT JOIN observations o "
        "  ON o.id = (SELECT id FROM observations WHERE session_id = s.id ORDER BY id DESC LIMIT 1) "
        "WHERE s.clinic_date = ? ORDER BY s.time_flag, s.section, s.room", today)]

    db_bytes = sum(p.stat().st_size for p in [db_path, Path(str(db_path) + "-wal")] if p.exists())
    totals = {
        "days": one("SELECT COUNT(DISTINCT clinic_date) FROM sessions")[0],
        "sessions": one("SELECT COUNT(*) FROM sessions")[0],
        "observations": one("SELECT COUNT(*) FROM observations")[0],
        "db_mb": round(db_bytes / 1e6, 1),
        "disk_free_gb": round(shutil.disk_usage(db_path.parent).free / 1e9, 1) if db_path.parent.exists() else None,
    }

    since = (now - timedelta(days=6)).date().isoformat()
    daily = [{"date": r[0], "polls": r[1], "changes": r[2], "fails": r[3]} for r in
             q("SELECT substr(started_at,1,10) d, COUNT(*), COALESCE(SUM(changes),0), SUM(sections_fail > 0) "
               "FROM polls WHERE started_at >= ? GROUP BY d ORDER BY d", since)]

    handbooks = sorted(p.stem.split("_", 1)[1] for p in schedules_dir.glob("handbook_*.pdf")) if schedules_dir.exists() else []
    warnings = sh(["journalctl", "-u", "vghtc-collector", "-p", "warning", "-n", "20", "-o", "short-iso", "--no-pager"])

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "window": WINDOW,
        "collector": collector,
        "today": today_stats,
        "sessions_today": sessions_today,
        "totals": totals,
        "daily": daily,
        "handbook_latest": handbooks[-1] if handbooks else None,
        "warnings": [ln for ln in warnings.splitlines() if ln and not ln.startswith("-- ")],
    }


def selftest() -> None:
    """三輪 09:00、09:01、09:15，現在 09:30 → 一個已結束的缺口 + 一個進行中的缺口。"""
    base = datetime(2026, 10, 22, 7, 30, tzinfo=TZ)  # 週四，準時開始
    polls = [base, base + timedelta(minutes=1), base + timedelta(minutes=15)]
    got = gaps_today(polls, base + timedelta(minutes=30))
    assert got == [["07:31", "07:45"], ["07:45", None]], got
    assert gaps_today(polls, base + timedelta(minutes=16)) == [["07:31", "07:45"]]
    # 第一輪 09:00 才開始 → 07:30 到 09:00 是缺口
    late_start = [datetime(2026, 10, 22, 9, 0, tzinfo=TZ), datetime(2026, 10, 22, 9, 1, tzinfo=TZ)]
    assert gaps_today(late_start, datetime(2026, 10, 22, 9, 2, tzinfo=TZ)) == [["07:30", "09:00"]]
    # 完全沒輪詢且在時段內 → 進行中的缺口
    assert gaps_today([], datetime(2026, 10, 22, 8, 0, tzinfo=TZ)) == [["07:30", None]]
    # 時段外（週日）什麼都不算
    assert gaps_today([], datetime(2026, 10, 25, 8, 0, tzinfo=TZ)) == []
    print("selftest OK")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--out", default="status.json")
    ap.add_argument("--schedules", default="schedules")
    ap.add_argument("--bucket", help="例如 gs://vghtc-calllight-2026；不給就不上傳")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        selftest()
        return 0
    if not a.db:
        ap.error("--db 必填")
    db_path = Path(a.db)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    status = compute(conn, datetime.now(TZ), db_path, Path(a.schedules))
    Path(a.out).write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.bucket and not a.no_upload:
        subprocess.run(["gcloud", "storage", "cp", "--cache-control=no-cache", a.out, f"{a.bucket}/status.json"],
                       check=True, capture_output=True)
    else:
        print(json.dumps(status, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
