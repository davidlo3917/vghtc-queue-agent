#!/usr/bin/env python3
"""
收集器監控網頁。跑在 Cloud Run 上、由 IAP 保護；讀 bucket 裡的 status.json（VM 每 5 分鐘上傳）
和 backups/ 清單，畫成一頁。刻意不連 VM：VM 死掉時這頁仍要能開，並顯示心跳過期。只用標準函式庫。

    /               監控總覽
    /data           今天每個診次的最新狀態（status.json 的快照）
    /data.csv       同上，CSV
    /backup/latest  下載最新一份 SQLite 備份（.db.gz）
    /status.json    原始狀態
    /healthz

    BUCKET=gs://vghtc-calllight-2026 TRIAL_END=2026-12-20 PORT=8080 python3 app.py
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import shutil
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BUCKET = os.environ.get("BUCKET", "").removeprefix("gs://")
TRIAL_END = os.environ.get("TRIAL_END")  # YYYY-MM-DD，GCP 試用到期日；到期前要啟用完整帳戶
TZ = timezone(timedelta(hours=8), "Asia/Taipei")
META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
STALE_STATUS_MIN = 12   # status.json 超過這麼久沒更新 → VM 可能掛了
STALE_POLL_MIN = 3      # 收集時段內，產生 status.json 當下距最後一輪超過這麼久 → 收集器掛了
DOW = "一二三四五六日"


# ---------------------------------------------------------------- bucket

def token() -> str:
    req = urllib.request.Request(META, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)["access_token"]


def gcs_url(path: str, query: str = "") -> str:
    return f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o{path}{query}"


def gcs(path: str, query: str = "") -> dict:
    req = urllib.request.Request(gcs_url(path, query), headers={"Authorization": f"Bearer {token()}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def load_status() -> dict:
    return gcs("/" + urllib.parse.quote("status.json", safe=""), "?alt=media")


def load_backups() -> list[dict]:
    items = gcs("", "?prefix=backups/&fields=items(name,size,updated)").get("items", [])
    return sorted(items, key=lambda i: i["name"])


# ---------------------------------------------------------------- health

def parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts).astimezone(TZ) if ts else None


def in_window(now: datetime, w: dict) -> bool:
    return now.isoweekday() in w["days"] and w["start"] <= now.strftime("%H:%M") <= w["end"]


def next_start(now: datetime, w: dict) -> datetime:
    h, m = map(int, w["start"].split(":"))
    for d in range(0, 8):
        day = now + timedelta(days=d)
        t = datetime.combine(day.date(), dtime(h, m), TZ)
        if day.isoweekday() in w["days"] and t > now:
            return t
    return now


def minutes_between(a: datetime | None, b: datetime | None) -> int | None:
    return int((b - a).total_seconds() // 60) if a and b else None


def health(st: dict, now: datetime) -> tuple[str, str, str]:
    """回傳 (good|warning|critical|idle, 標題, 說明)。
    心跳的新舊是看「產生 status.json 當下」距最後一輪多久，不是看現在，因為 status.json 本身 5 分鐘才更新一次。"""
    gen = parse(st.get("generated_at"))
    gen_age = minutes_between(gen, now)
    if gen_age is None or gen_age > STALE_STATUS_MIN:
        return "critical", "回報中斷", f"status.json 最後更新是 {gen_age} 分鐘前，VM 或上傳排程可能掛了"
    c = st["collector"]
    if c.get("service_active") not in (None, "active"):
        return "critical", "收集器服務未執行", f"systemd 回報：{c.get('service_active')}"
    w = st["window"]
    if not in_window(now, w):
        ns = next_start(now, w)
        return "idle", "休息中", f"不在收集時段（週一至週六 {w['start']}–{w['end']}），下次 {ns.strftime('%m/%d')}（{DOW[ns.weekday()]}）{w['start']} 開始"
    last = parse(c.get("last_poll_started"))
    poll_age = minutes_between(last, gen)
    if poll_age is None:
        return "critical", "還沒有任何輪詢", "資料庫裡沒有 polls 紀錄"
    if poll_age > STALE_POLL_MIN:
        return "critical", "心跳停止", f"收集時段內，最後一輪是 {fmt_ts(c.get('last_poll_started'))}（狀態回報於 {fmt_ts(st['generated_at'], False)}）"
    if c.get("last_poll_fail"):
        return "warning", "最後一輪失敗", "API 查詢失敗，收集器會在下一輪自動重試"
    if not c.get("last_poll_records"):
        return "warning", "最後一輪沒有診間", "API 回傳 0 個診間；開診前或假日屬正常，上班時段就不對"
    return "good", "正常收集中", f"最後一輪 {fmt_ts(c.get('last_poll_started'))}，看到 {c['last_poll_records']} 個診間（狀態回報 {gen_age} 分鐘前）"


# ---------------------------------------------------------------- page

CSS = """
:root { color-scheme: light; --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --line:#e1e0d9; --ring:rgba(11,11,11,.10); --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; --idle:#898781; --link:#2a78d6; }
* { box-sizing: border-box; }
body { margin:0; padding:16px; background:var(--page); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width: 1000px; margin: 0 auto; }
h1 { font-size:20px; margin:0 0 4px; }
h2 { font-size:14px; color:var(--ink2); font-weight:600; margin:24px 0 8px; }
a { color:var(--link); }
nav a { margin-right:14px; }
.meta { color:var(--muted); font-size:13px; }
.hero { display:flex; align-items:center; gap:14px; background:var(--surface); border:1px solid var(--ring); border-radius:10px; padding:16px 18px; margin-top:16px; }
.dot { width:18px; height:18px; border-radius:50%; flex:none; }
.hero .title { font-size:28px; font-weight:700; line-height:1.2; }
.hero .sub { color:var(--ink2); }
.s-good .dot{background:var(--good)} .s-warning .dot{background:var(--warn)} .s-critical .dot{background:var(--crit)} .s-idle .dot{background:var(--idle)}
.tiles { display:grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap:10px; }
.tile { background:var(--surface); border:1px solid var(--ring); border-radius:10px; padding:12px 14px; }
.tile .k { color:var(--muted); font-size:12px; }
.tile .v { font-size:26px; font-weight:600; line-height:1.2; margin-top:2px; }
.tile.small .v { font-size:17px; }
.tile .d { color:var(--ink2); font-size:12px; margin-top:2px; }
.tile.warn { border-color:var(--crit); } .tile.warn .v { color:var(--crit); }
table { width:100%; border-collapse:collapse; background:var(--surface); border:1px solid var(--ring); border-radius:10px; overflow:hidden; }
th, td { text-align:left; padding:7px 10px; border-top:1px solid var(--line); font-variant-numeric: tabular-nums; white-space:nowrap; }
th { color:var(--muted); font-size:12px; font-weight:600; border-top:0; position:sticky; top:0; background:var(--surface); }
td.n, th.n { text-align:right; }
.scroll { overflow:auto; max-height:75vh; border-radius:10px; }
pre { background:var(--surface); border:1px solid var(--ring); border-radius:10px; padding:12px; overflow:auto; font-size:12px; color:var(--ink2); white-space:pre-wrap; }
.crit { color:var(--crit); }
.empty { color:var(--muted); }
"""


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def tile(k: str, v, d: str = "", small: bool = False, warn: bool = False) -> str:
    cls = "tile" + (" small" if small else "") + (" warn" if warn else "")
    return f'<div class="{cls}"><div class="k">{e(k)}</div><div class="v">{e(v)}</div><div class="d">{e(d)}</div></div>'


def fmt_ts(ts: str | None, seconds: bool = True) -> str:
    t = parse(ts)
    return t.strftime("%m/%d %H:%M:%S" if seconds else "%m/%d %H:%M") if t else "—"


def fmt_size(n) -> str:
    n = int(n or 0)
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def page(title: str, body: str, now: datetime, viewer: str) -> str:
    return (f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<meta http-equiv='refresh' content='60'><title>{e(title)}</title><style>{CSS}</style></head><body><main>"
            f"<h1>台中榮總燈號收集器</h1>"
            f"<div class='meta'>現在 {now.strftime('%Y-%m-%d %H:%M')}（台北）· 資料每 5 分鐘更新，頁面每分鐘重新整理"
            f"{' · ' + e(viewer) if viewer else ''}</div>"
            f"<nav class='meta'><a href='/'>總覽</a><a href='/data'>今天的資料</a><a href='/data.csv'>下載 CSV</a>"
            f"<a href='/backup/latest'>下載最新備份（SQLite）</a><a href='/status.json'>status.json</a></nav>"
            f"{body}</main></body></html>")


def hero(level: str, title: str, sub: str) -> str:
    return f"<div class='hero s-{level}'><div class='dot'></div><div><div class='title'>{e(title)}</div><div class='sub'>{e(sub)}</div></div></div>"


def render_overview(st: dict, backups: list[dict], now: datetime, viewer: str, error: str | None) -> str:
    if error:
        return page("燈號收集器監控", hero("critical", "無法讀取狀態", error), now, viewer)
    level, title, sub = health(st, now)
    parts = [hero(level, title, sub)]
    c, t, tot, w = st["collector"], st["today"], st["totals"], st["window"]
    gen = parse(st["generated_at"])

    # 今天預期輪數 ≈ 從 07:30 到現在（或 22:30）的分鐘數
    h, m = map(int, w["start"].split(":"))
    start = datetime.combine(now.date(), dtime(h, m), TZ)
    eh, em = map(int, w["end"].split(":"))
    end = min(now, datetime.combine(now.date(), dtime(eh, em), TZ))
    expected = int((end - start).total_seconds() // 60) if now.isoweekday() in w["days"] and end > start else 0

    sess = t.get("sessions", {})
    last_change_age = minutes_between(parse(t.get("last_change_ts")), gen)
    parts.append("<h2>今天</h2><div class='tiles'>")
    parts.append(tile("輪詢次數", t["polls"], f"預期約 {expected}（07:30 起每分鐘一輪）" if expected else "今天不收集"))
    parts.append(tile("失敗輪數", t["failed_polls"], f"最後失敗 {fmt_ts(t['last_error']['ts'])}" if t.get("last_error") else "沒有失敗",
                      warn=bool(t["failed_polls"])))
    parts.append(tile("燈號變化", t["changes"], f"最近 1 小時 {t['changes_last_hour']}"))
    parts.append(tile("最後一次變化", fmt_ts(t.get("last_change_ts"), False), f"狀態回報時 {last_change_age} 分鐘前" if last_change_age is not None else "—",
                      small=True, warn=level == "good" and (last_change_age or 0) > 20))
    parts.append(tile("診次", sum(sess.values()), " / ".join(f"{k} {v}" for k, v in sorted(sess.items())) or "—"))
    parts.append(tile("最後一輪診間數", c.get("last_poll_records") if c.get("last_poll_records") is not None else "—",
                      f"{fmt_ts(c.get('last_poll_started'))}，{c.get('last_poll_changes')} 筆變化"))
    parts.append(tile("每輪耗時", f"{t.get('poll_seconds_avg') if t.get('poll_seconds_avg') is not None else '—'} 秒",
                      f"今天最長 {t.get('poll_seconds_max')} 秒", warn=(t.get("poll_seconds_max") or 0) > 30))
    parts.append("</div>")

    gaps = t.get("gaps") or []
    parts.append("<h2>今天的缺口（收集時段內超過 3 分鐘沒輪詢）</h2>")
    if gaps:
        parts.append("<table><tr><th>開始</th><th>結束</th></tr>" + "".join(
            f"<tr><td>{e(a)}</td><td>{e(b) if b else '<span class=crit>進行中</span>'}</td></tr>" for a, b in gaps) + "</table>")
    else:
        parts.append("<div class='empty'>沒有缺口</div>")

    parts.append("<h2>累積</h2><div class='tiles'>")
    parts.append(tile("收集天數", tot["days"]))
    parts.append(tile("診次", tot["sessions"]))
    parts.append(tile("燈號變化筆數", tot["observations"]))
    parts.append(tile("資料庫", f"{tot['db_mb']} MB", f"磁碟剩餘 {tot.get('disk_free_gb')} GB"))
    parts.append("</div>")

    last_bk = backups[-1] if backups else None
    bk_age = minutes_between(parse(last_bk["updated"]), now) if last_bk else None
    bk_warn = (bk_age or 0) > 2 * 24 * 60
    trial_days = (date.fromisoformat(TRIAL_END) - now.date()).days if TRIAL_END else None
    parts.append("<h2>備份與排程</h2><div class='tiles'>")
    parts.append(tile("最後備份", fmt_ts(last_bk["updated"], False) if last_bk else "還沒有",
                      f"{fmt_size(last_bk['size'])} · 共 {len(backups)} 份，保留 60 天" if last_bk else "每天 23:30 備份",
                      small=True, warn=bk_warn))
    parts.append(tile("門診手冊", st.get("handbook_latest") or "—", "每月 2 號自動存檔", small=True))
    parts.append(tile("狀態回報", fmt_ts(st["generated_at"], False), f"{minutes_between(gen, now)} 分鐘前 · 每 5 分鐘", small=True))
    parts.append(tile("收集器", f"{c.get('service_active') or '—'}", f"主機 {st.get('host') or '—'} · 重啟 {c.get('restarts', 0)} 次",
                      small=True, warn=(c.get("restarts") or 0) > 3))
    if trial_days is not None:
        parts.append(tile("GCP 試用到期", f"{trial_days} 天", f"{TRIAL_END} 前要在 Console 啟用完整帳戶", small=True, warn=trial_days <= 14))
    parts.append("</div>")

    parts.append("<h2>最近 7 天</h2><table><tr><th>日期</th><th class='n'>輪數</th><th class='n'>變化</th><th class='n'>失敗輪數</th></tr>")
    for d in reversed(st.get("daily") or []):
        dt = datetime.fromisoformat(d["date"])
        parts.append(f"<tr><td>{e(d['date'])}（{DOW[dt.weekday()]}）</td><td class='n'>{e(d['polls'])}</td>"
                     f"<td class='n'>{e(d['changes'])}</td><td class='n'>{e(d['fails'])}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>最近的警告（收集器 log）</h2>")
    warnings = st.get("warnings") or []
    parts.append(f"<pre>{e(chr(10).join(warnings))}</pre>" if warnings else "<div class='empty'>沒有警告</div>")
    if t.get("last_error"):
        parts.append(f"<div class='meta'>最後一次查詢失敗：{fmt_ts(t['last_error']['ts'])}，失敗的查詢：{e(t['last_error']['failed'])}</div>")
    return page("燈號收集器監控", "".join(parts), now, viewer)


DATA_COLS = [("time_flag", "午別"), ("section", "科別"), ("section_name", "科別名稱"), ("room", "診間"), ("doctor", "醫師"),
             ("cur_seq", "目前號"), ("tot_seq", "最末號"), ("cur_waiting", "待看"), ("delay_waiting", "過號待看"),
             ("max_delay_seq", "過號看診號"), ("changes", "變化次數"), ("last_change", "最後變化"), ("first_seen", "第一次看到"),
             ("last_seen", "最後看到")]
NUM = {"cur_seq", "tot_seq", "cur_waiting", "delay_waiting", "max_delay_seq", "changes"}
TS = {"last_change", "first_seen", "last_seen"}


def render_data(st: dict, now: datetime, viewer: str, error: str | None) -> str:
    if error:
        return page("今天的資料", hero("critical", "無法讀取狀態", error), now, viewer)
    rows = st.get("sessions_today") or []
    head = "".join(f"<th class='{'n' if k in NUM else ''}'>{e(label)}</th>" for k, label in DATA_COLS)
    body = []
    for r in rows:
        cells = []
        for k, _ in DATA_COLS:
            v = r.get(k)
            if k in TS:
                t = parse(v)
                v = t.strftime("%H:%M:%S") if t else "—"
            cells.append(f"<td class='{'n' if k in NUM else ''}'>{e(v)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    note = (f"<h2>今天的診次（{st['today']['date']}，共 {len(rows)} 個；狀態回報於 {fmt_ts(st['generated_at'], False)}）</h2>"
            f"<div class='meta'>這是 status.json 產生時各診次的最新一筆觀察，不是完整時間序列。要看完整資料請下載備份，用 DB Browser for SQLite 或 pandas 開 `observations` 表。</div>")
    table = f"<div class='scroll'><table><tr>{head}</tr>{''.join(body)}</table></div>" if rows else "<div class='empty'>今天還沒有資料</div>"
    return page("今天的資料", note + table, now, viewer)


def render_csv(st: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([k for k, _ in DATA_COLS])
    for r in st.get("sessions_today") or []:
        w.writerow([r.get(k) for k, _ in DATA_COLS])
    return "﻿" + buf.getvalue()  # BOM 讓 Excel 正確顯示中文


# ---------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self._send(200, "ok", "text/plain")
        if path == "/backup/latest":
            return self._backup()
        viewer = self.headers.get("X-Goog-Authenticated-User-Email", "").split(":")[-1]
        now = datetime.now(TZ)
        st, backups, error = {}, [], None
        try:
            st = load_status()
            if path == "/":
                backups = load_backups()
        except Exception as ex:  # noqa: BLE001
            error = f"{type(ex).__name__}: {ex}"
        if path == "/status.json":
            return self._send(502 if error else 200, error or json.dumps(st, ensure_ascii=False), "application/json" if not error else "text/plain")
        if path == "/data.csv":
            if error:
                return self._send(502, error, "text/plain")
            return self._send(200, render_csv(st), "text/csv", f'attachment; filename="vghtc_{st["today"]["date"]}.csv"')
        if path == "/data":
            return self._send(200, render_data(st, now, viewer, error), "text/html")
        self._send(200, render_overview(st, backups, now, viewer, error), "text/html")

    def _backup(self):
        try:
            latest = load_backups()[-1]
            req = urllib.request.Request(gcs_url("/" + urllib.parse.quote(latest["name"], safe=""), "?alt=media"),
                                         headers={"Authorization": f"Bearer {token()}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", f'attachment; filename="{latest["name"].split("/")[-1]}"')
                self.send_header("Content-Length", latest["size"])
                self.end_headers()
                shutil.copyfileobj(r, self.wfile)
        except Exception as ex:  # noqa: BLE001
            self._send(502, f"{type(ex).__name__}: {ex}", "text/plain")

    def _send(self, code: int, body: str, ctype: str, disposition: str | None = None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):  # noqa: A002 — Cloud Run 已有請求 log，不重複印
        pass


def selftest() -> None:
    now = datetime(2026, 10, 22, 10, 0, tzinfo=TZ)  # 週四 10:00，收集時段內
    w = {"start": "07:30", "end": "22:30", "days": [1, 2, 3, 4, 5, 6]}
    gen = now - timedelta(minutes=4)  # status.json 4 分鐘前產生
    base = {"generated_at": gen.isoformat(), "window": w, "host": "x",
            "collector": {"last_poll_started": (gen - timedelta(minutes=1)).isoformat(), "last_poll_fail": 0,
                          "last_poll_records": 155, "last_poll_changes": 3, "service_active": "active", "restarts": 0},
            "today": {"date": "2026-10-22", "polls": 1, "failed_polls": 0, "changes": 1, "changes_last_hour": 1,
                      "last_change_ts": gen.isoformat(), "poll_seconds_avg": 2.0, "poll_seconds_max": 3,
                      "sessions": {"A": 1}, "gaps": []},
            "sessions_today": [{"time_flag": "A", "section": "CV", "room": "2321", "doctor": "x", "cur_seq": 1, "changes": 1,
                                "last_change": gen.isoformat(), "first_seen": gen.isoformat(), "last_seen": gen.isoformat()}],
            "totals": {"days": 1, "sessions": 1, "observations": 1, "db_mb": 0.1, "disk_free_gb": 10}, "daily": []}
    assert health(base, now)[0] == "good", health(base, now)   # 最後一輪距產生狀態只有 1 分鐘，雖然距現在 5 分鐘
    stale = dict(base, collector=dict(base["collector"], last_poll_started=(gen - timedelta(minutes=5)).isoformat()))
    assert health(stale, now)[0] == "critical"
    assert health(base, now + timedelta(minutes=20))[0] == "critical"      # status.json 太舊
    sunday = datetime(2026, 10, 25, 10, 0, tzinfo=TZ)
    assert health(dict(base, generated_at=sunday.isoformat()), sunday)[0] == "idle"
    assert next_start(sunday, w).strftime("%m/%d %H:%M") == "10/26 07:30"
    assert "<html" in render_overview(base, [{"name": "backups/a.db.gz", "size": "20650", "updated": gen.isoformat()}], now, "me@x", None)
    assert "2321" in render_data(base, now, "me@x", None)
    assert render_csv(base).startswith("﻿time_flag,")
    assert fmt_size(20650) == "21 KB" and fmt_size(2_500_000) == "2.5 MB"
    print("selftest OK")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
