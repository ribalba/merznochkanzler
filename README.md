# merznochkanzler

Statische Seite mit einer Antwort ("Leider ja.") und den AfD-Umfragewerten seit Amtsantritt.

## Aufbau

- `build.py` holt `https://api.dawum.de/` (ODC-ODbL), filtert Bundestagsumfragen mit AfD-Wert,
  berechnet einen Trend und rendert die Vorlagen aus `PAGES` nach `site/` (Diagramme als
  Inline-SVG, die Zeitleiste als HTML, damit ihre Beschriftung auf schmalen Displays nicht
  mitskaliert; kein JavaScript-Bundle). Nebenbei entsteht `site/data.json`.
- Seiten: `template.html` → `site/index.html` (Antwort, Zeitleiste vom Amtsantritt über heute
  bis zum spätesten Wahltermin, Trend und der Abschnitt „Und wenn er bleibt?“ mit der
  Fortschreibung bis zur nächsten Wahl),
  `impressum.html` → `site/impressum.html` (Impressum und AGB).
- `style.css` wird über den Platzhalter `{{STYLE}}` in jede Seite eingebettet, damit die Seiten
  ohne zusätzlichen Request gleich aussehen.
- `.github/workflows/build.yml` baut täglich und deployt nach GitHub Pages
  (Repo-Einstellung: Pages, Source "GitHub Actions").
- Eigene Domain: `site/CNAME` mit dem Hostnamen anlegen und den DNS-Eintrag setzen.

## Container

    docker compose up -d --build     # Seite auf http://localhost:8080

`serve.py` ist der einzige Prozess im Container: Er baut die Seite beim Start, liefert
`site/` aus und baut danach täglich um 04:15 Ortszeit neu. Kein cron, kein nginx.
Der Build läuft in `site/.build/` und wird erst nach Erfolg per `os.replace` eingeblendet –
schlägt er fehl (API weg, Netz weg), bleibt die letzte funktionierende Fassung online
und es wird nach 30 Minuten erneut versucht. Das Volume `site` hält sie über Neustarts.

`GET /healthz` liefert den Buildzustand als JSON und dient als Healthcheck.

Stellschrauben (Umgebungsvariablen): `PORT`, `REBUILD_AT` (HH:MM Ortszeit), `TZ`,
`RETRY_MINUTES`, `BUILD_ON_START`, `SITE_DIR`.

## Lokal

    python3 build.py                        # live
    python3 build.py --input db.json        # mit lokaler Kopie der API
    python3 build.py --today 2026-09-06     # fester Stichtag
    python3 build.py --out /tmp/x           # anderes Ausgabeverzeichnis
    python3 serve.py                        # bauen und auf Port 8080 ausliefern

## Anpassen

Alle Fixpunkte stehen oben in `build.py`: Amtsbeginn, Wahlergebnis, Trendfenster,
Termin der nächsten Wahl (`NEXT_ELECTION`) und das kurzfristige Vergleichsfenster
(`RECENT_WINDOW_DAYS`). Bei Amtsende `MERZ_IN_OFFICE = False` setzen.
Anschrift und E-Mail im Impressum: `impressum.html`.

## Methodik

Trend = Mittelwert der jeweils neuesten Umfrage pro Institut, höchstens 21 Tage alt.
Das gleicht Institutseffekte aus (INSA liegt für die AfD regelmäßig über Infratest dimap),
ist aber eine eigene Rechnung und nicht identisch mit dem dawum-Wahltrend.
Die angegebene Korrelation ist eine Korrelation mit der Zeit, keine Kausalaussage.

Die Fortschreibung auf den Wahltag ist eine gewöhnliche Kleinste-Quadrate-Gerade über alle
Einzelumfragen seit Amtsantritt, verlängert bis `NEXT_ELECTION`, mit 95-%-Prognoseband für
eine einzelne Umfrage. Sie ist keine Wahlprognose: das Modell kennt keine Sättigung, keine
Ursachen und keinen vorgezogenen Wahltermin. Die Seite sagt das auch selbst.

## Lizenz

Code: MIT. Daten: dawum.de, ODC-ODbL (Quellenangabe auf der Seite ist Lizenzbedingung).
