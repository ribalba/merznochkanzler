#!/usr/bin/env python3
"""
Baut site/ (Startseite mit Fortschreibung, Impressum mit AGB) aus der DAWUM-Umfragedatenbank (https://api.dawum.de/, ODC-ODbL).

Aufruf:
    python3 build.py                 # holt die Datenbank live
    python3 build.py --input db.json # nutzt eine lokale Kopie (Tests, Offline)
    python3 build.py --out /tmp/x    # schreibt woandershin (siehe serve.py)

Keine Abhängigkeiten außerhalb der Standardbibliothek. Das Diagramm wird als
Inline-SVG erzeugt, damit die Seite ohne JavaScript-Bundle auskommt.
"""
import argparse
import datetime as dt
import json
import math
import pathlib
import statistics
import urllib.request

API_URL = "https://api.dawum.de/"
HERE = pathlib.Path(__file__).parent
TEMPLATE = HERE / "template.html"
STYLE = HERE / "style.css"
OUT_DIR = HERE / "site"
PAGES = {                             # Vorlage -> Datei in site/
    "template.html": "index.html",
    "impressum.html": "impressum.html",
}

# Fixpunkte
MERZ_IN_OFFICE = True                 # bei Amtsende auf False setzen und neu bauen
TERM_START = dt.date(2025, 5, 6)      # Wahl zum Bundeskanzler, 2. Wahlgang
ELECTION_DAY = dt.date(2025, 2, 23)   # Bundestagswahl 2025
AFD_ELECTION_RESULT = 20.8            # Zweitstimmen, amtliches Endergebnis
# Spätester regulärer Termin der nächsten Bundestagswahl: 48 Monate nach der
# konstituierenden Sitzung (25.03.2025), Wahltag ist ein Sonntag.
NEXT_ELECTION = dt.date(2029, 3, 25)
RECENT_WINDOW_DAYS = 180              # zweites, kurzfristigeres Modell auf der Prognoseseite

PARLIAMENT_SHORTCUT = "Bundestag"
PARTY_SHORTCUT = "AfD"
TREND_WINDOW_DAYS = 21                # Umfragen älter als das fließen nicht in den Trend ein


def load_database(path):
    if path:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    req = urllib.request.Request(API_URL, headers={"User-Agent": "merznochkanzler-build/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def find_id(table, key, value):
    for id_, row in table.items():
        if row.get(key) == value:
            return str(id_)
    raise KeyError(f"{key}={value!r} nicht in Datenbank gefunden")


def extract_surveys(db):
    """Alle Bundestags-Umfragen seit der Bundestagswahl mit AfD-Wert."""
    parl_id = find_id(db["Parliaments"], "Shortcut", PARLIAMENT_SHORTCUT)
    party_id = find_id(db["Parties"], "Shortcut", PARTY_SHORTCUT)
    institutes = db["Institutes"]
    rows = []
    for s in db["Surveys"].values():
        if str(s.get("Parliament_ID")) != parl_id:
            continue
        value = s.get("Results", {}).get(party_id)
        if value is None:
            continue
        date = dt.date.fromisoformat(s["Date"][:10])
        if date < ELECTION_DAY:
            continue
        rows.append({
            "date": date,
            "value": float(value),
            "institute": institutes.get(str(s.get("Institute_ID")), {}).get("Name", "?"),
            "n": s.get("Surveyed_Persons"),
        })
    rows.sort(key=lambda r: (r["date"], r["institute"]))
    return rows


def trend(rows, day):
    """Mittelwert der jeweils neuesten Umfrage pro Institut bis `day`
    (höchstens TREND_WINDOW_DAYS alt). Entspricht in der Idee dem
    dawum-Wahltrend, ist aber eine eigene Berechnung."""
    latest = {}
    for r in rows:
        if r["date"] > day or (day - r["date"]).days > TREND_WINDOW_DAYS:
            continue
        cur = latest.get(r["institute"])
        if cur is None or r["date"] > cur["date"]:
            latest[r["institute"]] = r
    if not latest:
        return None
    return statistics.fmean(r["value"] for r in latest.values())


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def slope(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def fmt(x, digits=1):
    return f"{x:.{digits}f}".replace(".", ",")


def timeline_html(today, term_start=TERM_START, election=NEXT_ELECTION):
    """Waagerechte Zeitleiste: Amtsantritt, heute, spätester Wahltermin.

    Als HTML und nicht als SVG, weil die Beschriftung sonst auf schmalen
    Displays mitskaliert und unleserlich wird."""
    total = max((election - term_start).days, 1)
    done = min(max((today - term_start).days, 0), total)
    pct = 100 * done / total
    # Nähe zum Rand: die Fahne rückt dann an den Punkt statt mittig darüber.
    where = " start" if pct < 12 else (" end" if pct > 88 else "")
    ticks = []
    for year in range(term_start.year + 1, election.year + 1):
        p = 100 * (dt.date(year, 1, 1) - term_start).days / total
        if 4 <= p <= 94:              # dichter am Rand kollidiert es mit den Endbeschriftungen
            ticks.append(f'<span class="tl-year" style="left:{p:.2f}%"><span>{year}</span></span>')
    label = (f"Zeitleiste: Amtsantritt am {term_start.strftime('%d.%m.%Y')}, "
             f"heute Tag {done} von {total}, nächste Wahl spätestens am "
             f"{election.strftime('%d.%m.%Y')}.")
    return (
        f'<div class="tl" role="img" aria-label="{label}">\n'
        f'  <div class="tl-ends">'
        f'<span><b>Amtsantritt</b>{term_start.strftime("%d.%m.%Y")}</span>'
        f'<span class="r"><b>Nächste Wahl</b>{election.strftime("%d.%m.%Y")}</span>'
        f'</div>\n'
        f'  <div class="tl-track">\n'
        f'    <div class="tl-done" style="width:{pct:.2f}%"></div>\n'
        f'    <span class="tl-cap" style="left:0"></span>'
        f'<span class="tl-cap" style="right:0"></span>\n'
        + "".join(f"    {t}\n" for t in ticks) +
        f'    <div class="tl-now{where}" style="left:{pct:.2f}%">'
        f'<span class="tl-flag">heute</span></div>\n'
        f'  </div>\n'
        f'</div>'
    )


def chart_svg(rows, fit, today):
    """Punkte = Einzelumfragen seit Amtsantritt, Gerade = lineare Regression
    über diese Punkte, gestrichelt = Wahlergebnis."""
    W, H = 760, 380
    ml, mr, mt, mb = 44, 16, 16, 40
    pw, ph = W - ml - mr, H - mt - mb

    since = [r for r in rows if r["date"] >= TERM_START]
    days_max = max((today - TERM_START).days, 1)
    ys_all = ([r["value"] for r in since] + [AFD_ELECTION_RESULT]
              + [fit["a"], fit["a"] + fit["b"] * days_max])
    y0, y1 = math.floor(min(ys_all)) - 1, math.ceil(max(ys_all)) + 1

    def X(d): return ml + pw * d / days_max
    def Y(v): return mt + ph * (1 - (v - y0) / (y1 - y0))

    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="AfD in Bundestagsumfragen, aufgetragen über die Tage der Amtszeit von Friedrich Merz">']
    # y-Gitter
    for v in range(y0, y1 + 1):
        y = Y(v)
        out.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" class="grid"/>')
        if v % 2 == 0:
            out.append(f'<text x="{ml-8}" y="{y+4:.1f}" class="tick" text-anchor="end">{v}</text>')
    # x-Achse: Tage im Amt
    step = 100 if days_max > 500 else 50
    for d in range(0, days_max + 1, step):
        x = X(d)
        out.append(f'<line x1="{x:.1f}" y1="{mt+ph}" x2="{x:.1f}" y2="{mt+ph+5}" class="grid"/>')
        out.append(f'<text x="{x:.1f}" y="{mt+ph+20}" class="tick" text-anchor="middle">{d}</text>')
    out.append(f'<text x="{ml+pw/2:.1f}" y="{H-4}" class="tick" text-anchor="middle">Tage im Amt</text>')
    # Wahlergebnis
    ye = Y(AFD_ELECTION_RESULT)
    out.append(f'<line x1="{ml}" y1="{ye:.1f}" x2="{W-mr}" y2="{ye:.1f}" class="baseline"/>')
    out.append(f'<text x="{W-mr}" y="{ye-5:.1f}" class="tick" text-anchor="end">Bundestagswahl 2025: {fmt(AFD_ELECTION_RESULT)}&#8239;%</text>')
    # Punkte
    for r in since:
        d = (r["date"] - TERM_START).days
        title = f'{r["institute"]}, {r["date"].strftime("%d.%m.%Y")}: {fmt(r["value"])} %'
        out.append(f'<circle cx="{X(d):.1f}" cy="{Y(r["value"]):.1f}" r="3" class="poll"><title>{title}</title></circle>')
    # Regressionsgerade über alle Einzelumfragen
    ya, yb = fit["a"], fit["a"] + fit["b"] * days_max
    out.append(f'<polyline points="{X(0):.1f},{Y(ya):.1f} {X(days_max):.1f},{Y(yb):.1f}" class="trend"/>')
    out.append("</svg>")
    return "\n".join(out)


def ols(xs, ys):
    """Kleinste Quadrate. Gibt Achsenabschnitt, Steigung, Reststreuung,
    Mittelwert und Streuungsquadratsumme von x zurück."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    resid = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    se = math.sqrt(resid / (n - 2))
    return {"a": a, "b": b, "se": se, "n": n, "mx": mx, "sxx": sxx}


def predict(f, x):
    """Punktschätzung und 95-%-Prognoseintervall für eine einzelne künftige Umfrage.
    Das Intervall deckt nur die Streuung um die Gerade ab, nicht das Risiko,
    dass die Gerade das falsche Modell ist."""
    y = f["a"] + f["b"] * x
    half = 1.96 * f["se"] * math.sqrt(1 + 1 / f["n"] + (x - f["mx"]) ** 2 / f["sxx"])
    return y, max(0.0, y - half), min(100.0, y + half)


def crossing_day(f, level):
    """Tag im Amt, an dem die Gerade `level` erreicht (None, wenn sie fällt)."""
    if f["b"] <= 0:
        return None
    return (level - f["a"]) / f["b"]


def projection_svg(rows, fit, today, election_day):
    """Umfragen, Regressionsgerade und Prognoseband bis zum Wahltag."""
    W, H = 760, 400
    ml, mr, mt, mb = 44, 16, 16, 46
    pw, ph = W - ml - mr, H - mt - mb

    since = [r for r in rows if r["date"] >= TERM_START]
    d_today = (today - TERM_START).days
    d_end = (election_day - TERM_START).days
    days_max = max(d_end, d_today, 1)

    band = [(d,) + predict(fit, d)[1:] for d in range(0, days_max + 1, 10)]
    ys_all = ([r["value"] for r in since] + [AFD_ELECTION_RESULT]
              + [lo for _, lo, _ in band] + [hi for _, _, hi in band])
    y0, y1 = max(0, math.floor(min(ys_all)) - 1), math.ceil(max(ys_all)) + 1

    def X(d): return ml + pw * d / days_max
    def Y(v): return mt + ph * (1 - (v - y0) / (y1 - y0))

    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="Umfragewerte der AfD seit Amtsantritt und lineare Fortschreibung bis zum Wahltag">']
    # y-Gitter
    for v in range(y0, y1 + 1):
        y = Y(v)
        out.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" class="grid"/>')
        if v % 5 == 0:
            out.append(f'<text x="{ml-8}" y="{y+4:.1f}" class="tick" text-anchor="end">{v}</text>')
    # x-Achse: Tage im Amt
    for d in range(0, days_max + 1, 200):
        x = X(d)
        out.append(f'<line x1="{x:.1f}" y1="{mt+ph}" x2="{x:.1f}" y2="{mt+ph+5}" class="grid"/>')
        out.append(f'<text x="{x:.1f}" y="{mt+ph+20}" class="tick" text-anchor="middle">{d}</text>')
    out.append(f'<text x="{ml+pw/2:.1f}" y="{H-4}" class="tick" text-anchor="middle">Tage im Amt</text>')
    # Prognoseband
    poly = ([f'{X(d):.1f},{Y(hi):.1f}' for d, _, hi in band]
            + [f'{X(d):.1f},{Y(lo):.1f}' for d, lo, _ in reversed(band)])
    out.append(f'<polygon points="{" ".join(poly)}" class="band"/>')
    # Wahlergebnis 2025
    ye = Y(AFD_ELECTION_RESULT)
    out.append(f'<line x1="{ml}" y1="{ye:.1f}" x2="{W-mr}" y2="{ye:.1f}" class="baseline"/>')
    out.append(f'<text x="{ml+4}" y="{ye-5:.1f}" class="tick">Bundestagswahl 2025: {fmt(AFD_ELECTION_RESULT)}&#8239;%</text>')
    # Heute
    xt = X(d_today)
    out.append(f'<line x1="{xt:.1f}" y1="{mt}" x2="{xt:.1f}" y2="{mt+ph}" class="marker"/>')
    out.append(f'<text x="{xt-5:.1f}" y="{mt+12}" class="tick" text-anchor="end">heute</text>')
    # Punkte
    for r in since:
        d = (r["date"] - TERM_START).days
        title = f'{r["institute"]}, {r["date"].strftime("%d.%m.%Y")}: {fmt(r["value"])} %'
        out.append(f'<circle cx="{X(d):.1f}" cy="{Y(r["value"]):.1f}" r="2.5" class="poll"><title>{title}</title></circle>')
    # Gerade: durchgezogen über den beobachteten Zeitraum, gestrichelt darüber hinaus
    y_a, y_t, y_e = (fit["a"] + fit["b"] * d for d in (0, d_today, d_end))
    out.append(f'<polyline points="{X(0):.1f},{Y(y_a):.1f} {xt:.1f},{Y(y_t):.1f}" class="fit"/>')
    out.append(f'<polyline points="{xt:.1f},{Y(y_t):.1f} {X(d_end):.1f},{Y(y_e):.1f}" class="fit-ext"/>')
    out.append(f'<circle cx="{X(d_end):.1f}" cy="{Y(y_e):.1f}" r="4" fill="var(--afd)"/>')
    out.append(f'<text x="{X(d_end)-6:.1f}" y="{Y(y_e)-10:.1f}" class="tick" text-anchor="end">Wahltag: {fmt(y_e)}&#8239;%</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="lokale JSON-Kopie der DAWUM-Datenbank")
    ap.add_argument("--today", help="Stichtag YYYY-MM-DD (Standard: heute)")
    ap.add_argument("--out", help="Ausgabeverzeichnis (Standard: site/)")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    db = load_database(args.input)
    rows = extract_surveys(db)
    if not rows:
        raise SystemExit("Keine Umfragen gefunden")

    # Trend als Tagesreihe ab Amtsantritt
    trend_points = []
    d = TERM_START
    while d <= today:
        v = trend(rows, d)
        if v is not None:
            trend_points.append(((d - TERM_START).days, v))
        d += dt.timedelta(days=1)
    afd_now = trend_points[-1][1]
    afd_start = trend_points[0][1]

    since = [r for r in rows if r["date"] >= TERM_START]
    xs = [(r["date"] - TERM_START).days for r in since]
    ys = [r["value"] for r in since]
    r_coef = pearson(xs, ys)
    per_100 = slope(xs, ys)
    per_100 = per_100 * 100 if per_100 is not None else None

    # Fortschreibung bis zum spätesten regulären Wahltermin
    fit = ols(xs, ys)
    recent = [r for r in since if (today - r["date"]).days <= RECENT_WINDOW_DAYS]
    fit_recent = ols([(r["date"] - TERM_START).days for r in recent], [r["value"] for r in recent])
    d_end = (NEXT_ELECTION - TERM_START).days
    proj, proj_lo, proj_hi = predict(fit, d_end)
    proj_recent = fit_recent["a"] + fit_recent["b"] * d_end if fit_recent else None

    cross = crossing_day(fit, 30.0)
    if cross is None:
        cross_text = "Die Gerade steigt nicht, eine 30-Prozent-Marke wird nicht erreicht."
    else:
        cross_date = TERM_START + dt.timedelta(days=round(cross))
        cross_text = (f"Die 30-Prozent-Marke liegt auf dieser Geraden am "
                      f"{cross_date.strftime('%d.%m.%Y')}" +
                      (" – also bereits in der Vergangenheit." if cross_date <= today
                       else f", das sind {(cross_date - today).days} Tage ab heute."))

    ctx = {
        "ANSWER": "Leider ja." if MERZ_IN_OFFICE else "Nein.",
        "TERM_START_ISO": TERM_START.isoformat(),
        "TERM_START_DE": TERM_START.strftime("%d.%m.%Y"),
        "DAYS_TODAY": str((today - TERM_START).days),
        "AFD_ELECTION": fmt(AFD_ELECTION_RESULT),
        "AFD_START": fmt(afd_start),
        "AFD_NOW": fmt(afd_now),
        "AFD_DELTA": ("+" if afd_now >= AFD_ELECTION_RESULT else "") + fmt(afd_now - AFD_ELECTION_RESULT),
        "N_POLLS": str(len(since)),
        "R": fmt(r_coef, 2) if r_coef is not None else "n/a",
        "PER_100": (("+" if per_100 >= 0 else "") + fmt(per_100)) if per_100 is not None else "n/a",
        "WINDOW": str(TREND_WINDOW_DAYS),
        "LAST_POLL": since[-1]["date"].strftime("%d.%m.%Y") if since else "?",
        "DB_UPDATE": str(db.get("Database", {}).get("Last_Update", ""))[:10],
        "BUILD_DATE": today.strftime("%d.%m.%Y"),
        "CHART": chart_svg(rows, fit, today),
        "TIMELINE": timeline_html(today),
        # Prognoseseite
        "NEXT_ELECTION_DE": NEXT_ELECTION.strftime("%d.%m.%Y"),
        "DAYS_TO_ELECTION": str((NEXT_ELECTION - today).days),
        "DAYS_IN_OFFICE_THEN": str(d_end),
        "PROJ": fmt(proj),
        "PROJ_LO": fmt(proj_lo),
        "PROJ_HI": fmt(proj_hi),
        "PROJ_DELTA": ("+" if proj >= afd_now else "") + fmt(proj - afd_now),
        "PROJ_RECENT": fmt(proj_recent) if proj_recent is not None else "n/a",
        "RECENT_WINDOW": str(RECENT_WINDOW_DAYS),
        "N_RECENT": str(len(recent)),
        "CROSS_30": cross_text,
        "PROJ_CHART": projection_svg(rows, fit, today, NEXT_ELECTION),
        "STYLE": STYLE.read_text(encoding="utf-8").rstrip("\n"),
    }

    out_dir = pathlib.Path(args.out) if args.out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for template_name, out_name in PAGES.items():
        html = (HERE / template_name).read_text(encoding="utf-8")
        for k, v in ctx.items():
            html = html.replace("{{" + k + "}}", v)
        (out_dir / out_name).write_text(html, encoding="utf-8")
    (out_dir / "data.json").write_text(json.dumps({
        "source": "dawum.de (ODC-ODbL)",
        "term_start": TERM_START.isoformat(),
        "afd_election_result": AFD_ELECTION_RESULT,
        "trend": [{"day": d, "value": round(v, 2)} for d, v in trend_points],
        "polls": [{"date": r["date"].isoformat(), "institute": r["institute"],
                   "value": r["value"], "n": r["n"]} for r in since],
        "projection": {
            "model": "OLS über alle Umfragen seit Amtsantritt, lineare Fortschreibung",
            "election_day": NEXT_ELECTION.isoformat(),
            "value": round(proj, 2),
            "low95": round(proj_lo, 2),
            "high95": round(proj_hi, 2),
            "value_recent_window": round(proj_recent, 2) if proj_recent is not None else None,
        },
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(since)} Umfragen seit Amtsantritt, Trend {ctx['AFD_NOW']} %, r = {ctx['R']}")
    print(f"Fortschreibung auf {NEXT_ELECTION.isoformat()}: {ctx['PROJ']} % "
          f"({ctx['PROJ_LO']} bis {ctx['PROJ_HI']} %)")


if __name__ == "__main__":
    main()
