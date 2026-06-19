#!/usr/bin/env python3
"""Stempeluhr – NFC-Zeiterfassung.

Antippen des NFC-Stickers ruft  /s/<TOKEN>  auf:
  * 1. Scan am Tag  -> "Kommen"  (neue Tageszeile mit Startzeit)
  * 2. Scan am Tag  -> "Gehen"   (dieselbe Zeile, Endzeit + Stunden)
  * 3. Scan am Tag  -> ignoriert (Tag bereits vollständig)

Die Übersicht ( /?t=<TOKEN> ) zeigt alle Tage und erlaubt nachträgliches
Bearbeiten, Hinzufügen und Löschen von Zeiten.

Konfiguration über Umgebungsvariablen:
  STAMP_TOKEN   geheimer Token in der URL (Schutz vor Fremd-Stempeln)
  TZ            Zeitzone (Standard Europe/Berlin)
  DATABASE_URL  Postgres-URL (Railway). Ohne -> lokale SQLite-Datei.
"""
from __future__ import annotations

import os
from datetime import datetime, date, timedelta, time
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from sqlalchemy import (Integer, Date, DateTime, String, create_engine, select)
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column)

# --- Konfiguration ----------------------------------------------------------
TZ = ZoneInfo(os.getenv("TZ", "Europe/Berlin"))
TOKEN = os.getenv("STAMP_TOKEN", "dev")
DB_URL = os.getenv("DATABASE_URL", "sqlite:///stempeluhr.db")
if DB_URL.startswith("postgres://"):  # Railway liefert teils das alte Schema
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

_connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, pool_pre_ping=True, connect_args=_connect_args)


class Base(DeclarativeBase):
    pass


class Entry(Base):
    __tablename__ = "entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    clock_in: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    clock_out: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")


Base.metadata.create_all(engine)
app = FastAPI(title="Stempeluhr")


# --- Hilfsfunktionen --------------------------------------------------------
def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def parse_time(s: str) -> time | None:
    s = (s or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def parse_date(s: str) -> date | None:
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def duration(e: Entry) -> timedelta | None:
    if e.clock_in and e.clock_out:
        d = e.clock_out - e.clock_in
        if d.total_seconds() < 0:        # über Mitternacht
            d += timedelta(days=1)
        return d
    return None


def fmt_hours(d: timedelta | None) -> str:
    if d is None:
        return "—"
    total = int(d.total_seconds())
    return f"{total // 3600}:{(total % 3600) // 60:02d}"


def fmt_time(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else ""


# --- Stempeln (NFC ruft das auf) -------------------------------------------
@app.get("/s/{token}")
def stamp(token: str, fmt: str = ""):
    """NFC-Scan: stempelt ein/aus. fmt=json -> JSON-Antwort für Kurzbefehle."""
    if token != TOKEN:
        if fmt == "json":
            return JSONResponse({"ok": False, "message": "Ungültiger Token"}, status_code=403)
        return PlainTextResponse("Ungültiger Token.", status_code=403)
    today = now_local().date()
    now = now_local()
    with Session(engine) as s:
        e = s.scalar(
            select(Entry).where(Entry.work_date == today).order_by(Entry.id.desc())
        )
        if e is None:
            s.add(Entry(work_date=today, clock_in=now))
            s.commit()
            msg = f"✅ Eingestempelt um {now.strftime('%H:%M')}"
        elif e.clock_in and not e.clock_out:
            e.clock_out = now
            s.commit()
            msg = f"🏁 Ausgestempelt um {now.strftime('%H:%M')}  ({fmt_hours(duration(e))} Std.)"
        else:
            msg = "ℹ️ Heute bereits Kommen & Gehen erfasst – Scan ignoriert."
    if fmt == "json":
        return JSONResponse({"ok": True, "message": msg})
    return RedirectResponse(f"/?t={token}&msg={quote(msg)}", status_code=303)


# --- Übersicht / Bearbeiten -------------------------------------------------
PAGE = """<!doctype html>
<html lang="de"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Stempeluhr</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:#0f172a; color:#e2e8f0; padding:16px; -webkit-text-size-adjust:100%; }}
  h1 {{ font-size:1.4rem; margin:.2rem 0 1rem; }}
  .msg {{ background:#16a34a22; border:1px solid #16a34a; color:#bbf7d0;
          padding:10px 12px; border-radius:10px; margin-bottom:14px; font-weight:600; }}
  .stampbtn {{ display:block; text-align:center; background:#22c55e; color:#04210f;
          font-weight:700; font-size:1.1rem; padding:16px; border-radius:14px;
          text-decoration:none; margin-bottom:18px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th,td {{ padding:8px 6px; text-align:left; border-bottom:1px solid #1e293b; font-size:.95rem; }}
  th {{ color:#94a3b8; font-weight:600; font-size:.8rem; text-transform:uppercase; }}
  input[type=time], input[type=date] {{ background:#1e293b; border:1px solid #334155;
          color:#e2e8f0; border-radius:8px; padding:7px; font-size:1rem; width:100%; }}
  .hours {{ font-variant-numeric:tabular-nums; font-weight:700; color:#7dd3fc; white-space:nowrap; }}
  .btn {{ background:#334155; color:#e2e8f0; border:none; border-radius:8px; padding:8px 10px;
          font-size:.9rem; }}
  .btn.save {{ background:#2563eb; color:#fff; }}
  .btn.del {{ background:#7f1d1d; color:#fecaca; }}
  .row form {{ display:flex; gap:6px; align-items:center; flex-wrap:wrap; }}
  .card {{ background:#0b1220; border:1px solid #1e293b; border-radius:12px; padding:12px; margin-bottom:10px; }}
  .card .d {{ font-weight:700; margin-bottom:8px; color:#cbd5e1; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr auto; gap:8px; align-items:end; }}
  .lbl {{ font-size:.7rem; color:#94a3b8; display:block; margin-bottom:3px; }}
  .total {{ margin-top:14px; font-size:1.1rem; font-weight:700; }}
  .add {{ margin-top:20px; }}
  .muted {{ color:#64748b; font-size:.85rem; }}
  a.plain {{ color:#7dd3fc; }}
</style></head><body>
<h1>⏱️ Stempeluhr</h1>
{msg}
<a class="stampbtn" href="/s/{token}">Jetzt stempeln (Kommen / Gehen)</a>
{cards}
<div class="total">Summe gesamt: <span class="hours">{total}</span> Std.</div>

<div class="add card">
  <div class="d">➕ Eintrag manuell hinzufügen</div>
  <form method="post" action="/add">
    <input type="hidden" name="token" value="{token}">
    <div class="grid">
      <div><span class="lbl">Datum</span><input type="date" name="work_date" value="{today}" required></div>
      <div><span class="lbl">Kommen</span><input type="time" name="clock_in"></div>
      <div><span class="lbl">Gehen</span><input type="time" name="clock_out"></div>
    </div>
    <button class="btn save" style="margin-top:10px">Hinzufügen</button>
  </form>
</div>
<p class="muted">Tipp: Über das NFC-Etikett oder den grünen Button wird automatisch
Kommen bzw. Gehen gestempelt. Zeiten hier jederzeit nachträglich anpassbar.</p>
</body></html>"""

CARD = """<div class="card">
  <div class="d">{datum}</div>
  <form method="post" action="/update" class="row">
    <input type="hidden" name="token" value="{token}">
    <input type="hidden" name="id" value="{id}">
    <input type="hidden" name="work_date" value="{iso}">
    <div class="grid">
      <div><span class="lbl">Kommen</span><input type="time" name="clock_in" value="{cin}"></div>
      <div><span class="lbl">Gehen</span><input type="time" name="clock_out" value="{cout}"></div>
      <div><span class="lbl">Std.</span><div class="hours">{hours}</div></div>
    </div>
    <div style="display:flex; gap:6px; margin-top:10px;">
      <button class="btn save" type="submit">Speichern</button>
      <button class="btn del" type="submit" formaction="/delete"
              onclick="return confirm('Diesen Eintrag löschen?')">Löschen</button>
    </div>
  </form>
</div>"""

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


@app.get("/", response_class=HTMLResponse)
def home(t: str = "", msg: str = ""):
    if t != TOKEN:
        return HTMLResponse(
            "<body style='font-family:sans-serif;background:#0f172a;color:#e2e8f0;padding:30px'>"
            "<h2>🔒 Zugriff nur über deinen NFC-Link.</h2>"
            "<p>Bitte über das NFC-Etikett (mit gültigem Token) öffnen.</p></body>",
            status_code=403,
        )
    with Session(engine) as s:
        entries = list(s.scalars(
            select(Entry).order_by(Entry.work_date.desc(), Entry.id.asc())
        ))
    cards, total = [], timedelta()
    for e in entries:
        d = duration(e)
        if d:
            total += d
        wd = WEEKDAYS[e.work_date.weekday()]
        cards.append(CARD.format(
            token=t, id=e.id, iso=e.work_date.isoformat(),
            datum=f"{wd}, {e.work_date.strftime('%d.%m.%Y')}",
            cin=fmt_time(e.clock_in), cout=fmt_time(e.clock_out), hours=fmt_hours(d),
        ))
    body = PAGE.format(
        token=t, msg=(f'<div class="msg">{msg}</div>' if msg else ""),
        cards="".join(cards) or '<p class="muted">Noch keine Einträge.</p>',
        total=fmt_hours(total), today=now_local().date().isoformat(),
    )
    return HTMLResponse(body)


def _redirect(token: str, msg: str):
    return RedirectResponse(f"/?t={token}&msg={quote(msg)}", status_code=303)


@app.post("/update")
def update(token: str = Form(), id: int = Form(),
           work_date: str = Form(), clock_in: str = Form(""), clock_out: str = Form("")):
    if token != TOKEN:
        return PlainTextResponse("Ungültiger Token.", status_code=403)
    d = parse_date(work_date)
    ti, to = parse_time(clock_in), parse_time(clock_out)
    with Session(engine) as s:
        e = s.get(Entry, id)
        if not e:
            return _redirect(token, "⚠️ Eintrag nicht gefunden.")
        if d:
            e.work_date = d
        e.clock_in = datetime.combine(e.work_date, ti) if ti else None
        e.clock_out = datetime.combine(e.work_date, to) if to else None
        s.commit()
    return _redirect(token, "💾 Gespeichert.")


@app.post("/add")
def add(token: str = Form(), work_date: str = Form(),
        clock_in: str = Form(""), clock_out: str = Form("")):
    if token != TOKEN:
        return PlainTextResponse("Ungültiger Token.", status_code=403)
    d = parse_date(work_date)
    if not d:
        return _redirect(token, "⚠️ Bitte ein gültiges Datum angeben.")
    ti, to = parse_time(clock_in), parse_time(clock_out)
    with Session(engine) as s:
        s.add(Entry(
            work_date=d,
            clock_in=datetime.combine(d, ti) if ti else None,
            clock_out=datetime.combine(d, to) if to else None,
        ))
        s.commit()
    return _redirect(token, "➕ Eintrag hinzugefügt.")


@app.post("/delete")
def delete(token: str = Form(), id: int = Form()):
    if token != TOKEN:
        return PlainTextResponse("Ungültiger Token.", status_code=403)
    with Session(engine) as s:
        e = s.get(Entry, id)
        if e:
            s.delete(e)
            s.commit()
    return _redirect(token, "🗑️ Eintrag gelöscht.")


@app.get("/health")
def health():
    return {"ok": True}
