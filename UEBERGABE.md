# Übergabe

Stand 15.11.2026, Lieferung 15. Fortschritt 94 %. Diese Datei reicht zusammen mit dem Repo-Zip, `PARAMETERKATALOG.md`
und dem Auftragstext, um in einem neuen Chat weiterzuarbeiten.

## Ziel

Möglichst hohe Renditen erwirtschaften; dafür Muster erkennen, die überdurchschnittliche Renditen
vorhersagen. Dieses Repo liefert die stichtagsechten Daten, Score und Auswertung liegen im privaten
Insider-Monitor.

## Was gebaut ist

| Quelle | Parameter | Offline getestet | Echter Lauf |
|---|---|---|---|
| `edgar_index` | – (Zeitbasis) | ja | ja |
| `edgar_insider` | IH1-01 bis IH1-07, IH1-09, IH1-10, IH1-16, IH1-17, IH1-18, WS3-01 | ja | ja |
| `edgar_ereignisse` | WS2-04, UA1-10, UA2-03, UA2-04, IH6-04, UA4-05, GA2-03, UA4-01, UA3-03, UA3-04, KD1-11, WS3-02, UA4-04, UA4-02 | ja | ja (UA4-04, UA4-02 seit 15.11.2026) |
| `edgar_xbrl` | UA1-01 bis UA1-08, UA2-01, UA3-01, UA3-02, UA3-05, UA4-03, GA1-02, GA1-03, GA1-06, GA3-03, PR2-03, GW1-04, WR2-02 | ja | ja (die sechs neuen seit 15.11.2026) |
| `edgar_rollen` | IH5-01, IH5-02, IH1-14 | ja | ja |
| `fred` | GW2-01, GW2-03, GW1-06, GW3-01, GW2-04, GW2-06, GW1-05 | ja | ja |
| `wikipedia` | WS3-05 | ja | ja |
| `cfpb` | GA3-01 | ja | ja |
| `klinik` | GA1-04, GA1-08 | ja | ja |
| `sec_ftd` | IH3-06 | ja | ja (Workflow `einzel`, 11.11.2026) |
| `edgar_13f` | IH5-03, IH5-04 | ja | ja (Workflow `einzel`, 11.11.2026; Einzelmeldungen als Gegenprobe) |
| `usaspending` | PR2-01 | ja | ja (Workflow `einzel`, 11./12.11.2026) |
| `uspto_patente` | GA1-01 | ja | ja (Workflow `einzel`, 13.11.2026); Historie ab 2001 lokal gebaut und veröffentlicht (15.11.2026) |
| `uspto_zitate` | GA1-09 | ja | nur lokal, veröffentlicht 15.11.2026; nicht im Tageslauf |
| `fed_sf` | GW1-01, GW1-02, WS2-05 | ja | ja (Workflow `einzel`, 15.11.2026) |
| `rueckrufe` | GA3-02 | ja | ja (Workflow `einzel`, 15.11.2026) |
| `sec_verfahren` | PR4-01 | ja | ja (Workflow `einzel`, 15.11.2026, Aufbau und Folgelauf) |

72 Parameter, 154 Tests (zuletzt unter pandas 2.3.3). Die neun ersten Module liefen am 10.11.2026 im echten Lauf
(`laufend`, 53 Minuten) grün; Ergebnis unten. Stand 11.11.2026 darunter.

## Prüfliste für den ersten echten Lauf

Jede Zeile ist eine Annahme, die erst der Lauf bestätigt. Der Prüfbericht je Quelle (Zusammenfassung
des Workflow-Laufs und Release `pruefbericht`) zeigt die genannten Werte.

| Quelle | Annahme | Woran man es sieht |
|---|---|---|
| `edgar_index` | Adresse der Sammeldatei `submissions.zip` stimmt | Lauf bricht sonst mit HTTP-Fehler ab |
| | Annahmezeit ist Ostküstenzeit | Hinweis „Annahmezeit gelesen als …“ mit beiden Trefferquoten; unter 0,9 Fehler |
| | Speicher und Laufzeit reichen (rund 1 Mio. Dateien) | Laufzeit des Jobs |
| `edgar_insider` | Links auf der SEC-Datenseite werden gefunden | Hinweis „Datenseite nicht lesbar“ darf fehlen |
| | Spaltennamen der TSV-Dateien | Fehler „Pflichtspalten fehlen“ nennt die echten Namen |
| | Datumsformat `31-MAR-2024` oder ISO | „unplausible Daten“ über 2 % wäre ein Zeichen für falsches Lesen |
| | Rohdatei der Form 4 liegt ohne den Ordner `xsl…/` daneben | Zählung `gelesen` gegen `fehlt` in `xml` |
| `edgar_ereignisse` | Items stehen als `2.02,9.01` | Zeilenzahl von WS2-04 und UA1-10 |
| `edgar_xbrl` | Aktenzeichen passen zum Verzeichnis | Fehler bei über 5 % Berichten ohne Annahmezeit |
| | Sammeldatei `companyfacts.zip` passt in Speicher und Zeit | Laufzeit des Jobs |
| `edgar_rollen` | Meldungskopf nennt `SUBJECT COMPANY` auch bei Form 144 | Fehler bei über 20 % `ohne_rolle` |
| | Teilabruf (Range) wird angenommen | Laufzeit je Meldung |
| `fred` | Alle Stände von INDPRO und CPIAUCSL in einem Abruf | Zeilenzahl in `info`; sonst HTTP 400 |
| | Veröffentlichungen heißen „FOMC Press Release“, „Employment Situation“, „Consumer Price Index“ | Hinweis „Termine nicht gefunden für …“ |
| `wikipedia` | Wikidata-Eigenschaft P5531 ist die CIK | Fehler bei unter 500 Zuordnungen |
| `cfpb` | Adresse und Spalten `Date received`, `Company` | Fehler „Pflichtspalten fehlen“ |
| | Namensabgleich trifft | Hinweis mit Trefferquote; unter 20 % Fehler |
| `klinik` | Seitengröße 1000 und Feld `resultsFirstPostDateStruct` | Zeilenzahl GA1-04 |
| | Aufbau des openFDA-Verzeichnisses `download.json` | Fehler „ohne … partitions“ |
| Workflow | Rechte `contents: write`, `actions: write`; Releases werden angelegt | Job `abschluss` |

## Ergebnis des ersten echten Laufs (10.11.2026)

Keine schweren Befunde, alle Annahmen der Prüfliste haben gehalten. Auffällig:

| Quelle | Befund | Folge |
|---|---|---|
| `edgar_index` | Annahmezeit ist UTC (Quote 0,937 gegen 0,392) | von Hand bestätigt, Nr. 65 |
| `fred` | `GW2-06` ohne Stände ab Dezember 2025 (CPI Oktober 2025 fehlt) | behoben, Nr. 66; im nächsten Lauf prüfen: Stand 2025-12-18 ≈ −0,0031 |
| `edgar_rollen` | 3.743 von 261.497 Meldungen gelesen | Modus `rueckwaerts` |
| `klinik` | Namensabgleich Zulassungen nur 10,1 %, Studien 53,4 % | später verbessern |
| `cfpb` | 4,8 % der Firmennamen, aber 61,9 % der Beschwerden zugeordnet | genügt |
| `wikipedia` | 3.104 Zuordnungen | genügt |
| Workflow | Hinweis: Node.js 20 der Actions veraltet | bei Gelegenheit Actions-Versionen anheben |

## Stand 12.11.2026 (Lieferung 7 bis 10)

- Rückwärtslauf (Rollen der 13D- und 144-Meldungen): abgeschlossen am 12.11.2026 nach sieben Läufen der Kette;
  261.725 Meldungen gelesen, keine offen. Die geplanten Tagesläufe (Di–Sa 11:20 UTC) laufen wieder.
- `sec_ftd` im echten Lauf grün: 437 Dateien, 28,2 Mio. Zeilen, 4,1 Mio. Werte für 17.664 Firmen ab 2004;
  erster Lauf 4 Minuten, Folgeläufe 1,5 Minuten. Seit dem 11.11. im Workflow `abruf`.
- `edgar_13f` im echten Lauf grün: 54 Datensätze (2,9 GB) in 8 Minuten, 53 Quartale ab 2013 Q2, 8.580 Manager
  im jüngsten Quartal; IH5-04 303.351 Werte für 11.664 Firmen, IH5-03 54.326 Werte. Seit dem 11.11. im Workflow
  `abruf`; dort ist es ohne neuen Datensatz ein Lauf von Sekunden. Der erste Lauf deckte zwei Fehler auf, beide
  behoben (Frist an Feiertagen, CUSIP-Wechsel; `ENTSCHEIDUNGEN.md` Nr. 75, 77).
  Bekannte Grenze: Wechselt eine Firma die CIK (neue Holding, z. B. Exxon Mobil 2026), sieht das bei der alten CIK
  wie ein Rückgang der Halter aus; eine Nachfolgetabelle für CIK gibt es noch nicht.
  Neuaufbau mit heutiger Zuordnung: `gh workflow run einzel.yml -f quelle=edgar_13f -f frisch=true`.
- `klinik`: bessere Zuordnung der Sponsoren im echten Lauf bestätigt (Studien 65,3 %, Zulassungen ohne
  Generika 44,3 %).
- Alle elf Quellen im Lauf vom 11.11. (07:45 UTC) ohne schweren Befund; die Warnung zu Node 20 ist weg.
- 13F des laufenden Quartals (Lieferung 8): Fehlt der Datensatz der SEC, baut `edgar_13f` das Quartal aus den
  einzelnen 13F-HR-Meldungen, sobald das Meldungsverzeichnis über die Frist hinausreicht (`ENTSCHEIDUNGEN.md`
  Nr. 81–86). Gegenprobe im echten Lauf für 2026 Q2: Zahl der Halter bei allen 23.229 Wertpapieren wie im
  Datensatz, 8.580 Manager auf beiden Wegen; 20 Minuten für 8.695 Meldungen.
- Zu prüfen am 18.11.2026: Die Frist für das dritte Quartal 2026 endet am 16.11. Das Meldungsverzeichnis eines
  Laufs reicht nur bis zum Vortag (Lauf vom 14.11.: jüngstes Datum 13.11.), der Lauf am 17.11. sieht also erst den
  16.11. Der erste Lauf mit einem Datum nach der Frist ist der am Mi 18.11.: Er muss im Prüfbericht `edgar_13f`
  die Zeile `aus_einzelmeldungen: ['2026q3']` zeigen; die Werte tragen den Stand `2026q3 Einzelmeldungen` und
  gelten ab 17.11., 09:30 Uhr Ostküste. Meldet der Lauf „Einzelmeldungen unvollständig“, liest der nächste neu.
  Eine geplante Aufgabe (`pruefung-13f-q3`) prüft das am 19.11. früh.
- Bundesaufträge (Lieferung 9): `usaspending` im echten Lauf grün. 20 Haushaltsjahre (2008–2027), 94,5 Mio.
  Transaktionen, 12,1 Billionen $ Umfang; zugeordnet 52,8 % des Volumens (43,2 % bei Firmen mit Börsenkürzel),
  PR2-01 mit 419.841 Monatswerten für 8.168 Firmen ab 10/2007. Größte: Lockheed Martin 983 Mrd. $, Boeing 483,
  General Dynamics 409, RTX 308, Northrop Grumman 283. Nicht zugeordnet sind vor allem private und
  gemeinnützige Auftragnehmer (TriWest, Staatslabore, Battelle, Bechtel).
  Der Dateiserver lässt je Lauf etwa neun Sammeldateien zu: Der Aufbau brauchte drei Läufe, der Monatsbetrieb
  braucht zwei Dateien. Neuaufbau: dreimal `gh workflow run einzel.yml -f quelle=usaspending` (der erste mit
  `-f frisch=true`). Wert für einen Monat erscheint mit der Sammeldatei am 6. bis 9. des Folgemonats.
  Mögliche Verbesserung: 0,4 % des Volumens haben einen Mutternamen im Abgleich, den kein gemeldeter Name
  stützt (Art `ungestuetzt`, z. B. Philips); 0,2 % sind gleichnamige Firmen (`mehrdeutig`).
- Patente (Lieferung 10): `uspto_patente` im echten Lauf grün. Quelle ist das Amtsblatt des USPTO (frei, aber
  nur 52 Ausgaben rückwirkend): 380.575 Patente vom 18.11.2025 bis 10.11.2026, 28 % bei Firmen mit
  Börsenkürzel, GA1-01 mit 25.353 Werten für 2.633 Firmen. Größte: Qualcomm, TSMC, Apple, Dell, Toyota, IBM.
  Die Reihe wächst ab jetzt wöchentlich (neue Ausgabe jeden Dienstag; der Lauf am Mittwoch liest sie).
- Patent-Historie und Zitationen (Lieferung 11, veröffentlicht 15.11.2026): Die Sammeldateien von PatentsView
  lassen sich mit einem einfachen USPTO-Konto von der Webseite des Open Data Portal laden (kein Schlüssel). Sie
  liegen entpackt im Ordner `rohdaten/patente` neben den Repos (rund 14 GB): `g_patent`,
  `g_assignee_not_disambiguated`, `g_us_patent_citation` (dazu ungenutzt `g_assignee_disambiguated`,
  `g_application`). `werkzeuge/patente_historie.sh` hat daraus die Historie gebaut und in die Releases geladen:
  `GA1-01` 633.607 Werte für 10.628 Firmen ab 01/2001, `GA1-09` 952.420 Werte für 10.119 Firmen bis 12/2025.
  Plausibilität: IBM 9.097 Patente im Jahr 2018; Raytheon bis 04/2020 unter eigener CIK, danach bei RTX.
  Die neue Lesart des Amtsblatts (Mitinhaber) ist im echten Lauf bestätigt (Workflow `einzel`, 13.11.2026).
  Der Lauf auf GitHub mit der Historie im Bestand ist bestätigt (Workflow `einzel`, 14.11.2026 abends UTC:
  49 Sekunden, dieselben 633.607 Werte).
  Verlängern: Die Dateien erscheinen vierteljährlich. Neu laden, dann im Repo-Ordner (ohne Ordner `ausgabe`)
  `PYTHON=<venv>/Scripts/python.exe bash werkzeuge/patente_historie.sh ../rohdaten/patente` – rund 10 Minuten;
  die Zitationen wachsen nur so. Der Rechner hat 8 GB Arbeitsspeicher: nichts Großes nebenher laufen lassen.
  `frisch=true` im Workflow `einzel` für `uspto_patente` nicht verwenden: Es baute `patente_ausgaben` und
  `patente_zuordnung` ohne die Historie neu.
- Lieferungen 12 bis 14 im echten Lauf (15.11.2026, Workflows `abruf` und `einzel`, alle grün): Umsatzwachstum
  295.981 Werte für 11.637 Firmen, Nettoverschuldung 360.636 / 14.326, Rückkäufe 79.562 / 5.446, Verwässerung
  239.585 / 10.195, Dividendenwechsel 1.842 / 1.473, F&E-Erfolgsbilanz 964 / 269 (braucht elf Jahresberichte),
  Lockup-Ablauf 5.777 Börsengänge seit 2007, Abspaltung 622 Zeilen; Zinsüberraschung 280 Erklärungen seit 1994,
  Nachrichtenstimmung 17.095 Tage seit 1980; Rückrufe siehe Prüfbericht `rueckrufe`.
  `rueckrufe` und `fed_sf` laufen ab jetzt im Tageslauf mit.
- SEC-Verfahren (Lieferung 15, 15.11.2026, grün): 30.886 Veröffentlichungen seit 09/1995 (Zivilklagen 12.011,
  Verwaltungsverfahren 18.751, davon 3.348 mit AAER-Nummer), 7.867 nennen eine zugeordnete Firma; 17.416 Werte
  für 7.021 Firmen ab 2001. Folgelauf liest je Liste zwei Seiten. Läuft ab jetzt im Tageslauf mit.
- `GW2-06` im echten Lauf bestätigt (340 Werte, letzter Stand 14.10.2026).
- Actions laufen auf Node 24 (checkout v5, setup-python v6, upload-artifact v6, download-artifact v7).
- Neue Module zuerst über `gh workflow run einzel.yml -f quelle=<name>` erproben; der Workflow berührt die
  Fortsetzungskette von `abruf` nicht.

## Vorgabe des Inhabers (15.11.2026)

Erst alle frei verfügbaren Kennzahlen bauen, dann breit über alle Aktien nach Zusammenhängen suchen – nicht
gefiltert über Insiderkäufe. Keine kostenpflichtigen Daten. Die Reihenfolge der offenen Quellen steht in
`ENTSCHEIDUNGEN.md` Nr. 110 und in der Tabelle „Noch offen“. Eine erste Bewertung der vorhandenen Kennzahlen liegt
privat vor (Ordner `auswertung` neben den Repos) und ruht, bis die Quellen ausgebaut sind.

## Empfohlene Reihenfolge

1. ~~Repo anlegen, Secrets setzen, Workflow `abruf` im Modus `laufend` starten.~~ erledigt
2. ~~Prüfberichte auswerten, Abweichungen beheben.~~ erledigt (Lieferung 6)
3. ~~Einmal im Modus `rueckwaerts` starten (Historie der 13D- und 144-Meldungen; setzt sich selbst fort).~~
   erledigt (10. bis 12.11.2026)
4. Offene Bausteine (Tabelle „Noch offen“ in `ENTSCHEIDUNGEN.md`). Erledigt: Lieferausfälle, 13F (auch das
   laufende Quartal), Sponsoren, Bundesaufträge, Patente mit Historie und Zitationen, Abschlüsse II mit Lockup
   und Abspaltung (Lieferung 12), Fed San Francisco (Lieferung 13). H-1B ist zurückgestellt (dol.gov sperrt
   automatische Abrufe), Rückrufe (Lieferung 14), SEC-Verfahren (Lieferung 15). Als Nächstes:
   Insider-Optionsausübungen, kleinere Bausteine (13F-Summe, Wahltermine, F-Score), N-PORT, zuletzt die Berichtstexte.
5. Anbindung im Insider-Monitor (eigener Auftrag; `SCHNITTSTELLE.md` beschreibt das Lesen).

## Dateien für einen neuen Chat

- neuestes Repo-Zip (`daten-offen_lieferung-<n>.zip`)
- `PARAMETERKATALOG.md` (IH1-18 „Tagescluster“ dort nachtragen)
- Auftragstext „Öffentliches Datenrepo bauen (selbstständig)“
- nach dem ersten Lauf: Log oder die Dateien des Release `pruefbericht`
- nur bei Bedarf: Repo-Zip des Insider-Monitors (Abgleich ist erfolgt, siehe `ENTSCHEIDUNGEN.md` Nr. 27–35)
