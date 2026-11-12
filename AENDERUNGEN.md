# Änderungen

## Lieferung 10 – 2026-11-12 (Patente)

- Neue Quelle `uspto_patente`: erteilte Patente je Firma aus dem Amtsblatt des USPTO → GA1-01; Tabellen
  `patente_erteilt`, `patente_zuordnung`, `patente_ausgaben` (`ENTSCHEIDUNGEN.md` Nr. 96–101).
- Die Reihe beginnt am 18.11.2025 (52 Ausgaben rückwirkend) und wächst wöchentlich; die Historie davor braucht
  einen Schlüssel des USPTO und ist offen.
- Echter Lauf: 52 Ausgaben (18.11.2025 bis 10.11.2026), 380.575 Patente, davon 324.271 Erfindungspatente;
  33 % zugeordnet, 28 % bei Firmen mit Börsenkürzel; 25.353 Werte für 2.633 Firmen. Seit dem 12.11. im Workflow
  `abruf`.
- 134 Offline-Tests.

## Lieferung 9 – 2026-11-12 (Bundesaufträge)

- Neue Quelle `usaspending`: Vertragstransaktionen des Bundes ab Haushaltsjahr 2008 → PR2-01 (Verpflichtungen je
  Firma und Monat des Bekanntwerdens); Tabellen `usaspending_monat`, `usaspending_zuordnung`, `usaspending_dateien`.
- Zuordnung über Konzernfamilien (Mutter-UEI) mit Abstimmung der gemeldeten Namen (`ENTSCHEIDUNGEN.md` Nr. 87–95).
- Namensabgleich: Rechtsformen in Einzelbuchstaben und nachgestelltes „THE“; Suche ohne Ähnlichkeitsstufe.
- Abruf: `sende_json` für Abfrageschnittstellen.
- Echter Lauf: 20 Haushaltsjahre, 94,5 Mio. Transaktionen; 52,8 % des Auftragsvolumens zugeordnet, 43,2 % bei
  Firmen mit Börsenkürzel; 419.841 Monatswerte für 8.168 Firmen ab 10/2007. Seit dem 12.11. im Workflow `abruf`.
- Rückwärtsbefüllung der Rollen (13D, 144) abgeschlossen: 261.725 Meldungen gelesen, keine offen.
- 129 Offline-Tests.

## Lieferung 8 – 2026-11-11 (13F des laufenden Quartals)

- `edgar_13f`: Ein Quartal ohne Datensatz der SEC entsteht aus den einzelnen 13F-HR-Meldungen, sobald das
  Meldungsverzeichnis über die Frist hinausreicht; der Datensatz ersetzt es später (`ENTSCHEIDUNGEN.md` Nr. 81–86).
- Gegenprobe im echten Lauf für 2026 Q2: 8.695 Meldungen, Zahl der Halter bei allen 23.229 Wertpapieren wie im
  Datensatz der SEC.
- Abruf: Anfragegrenze gilt auch für gleichzeitige Abrufe; die Einzelmeldungen werden zu viert gelesen (20 statt 55 Minuten je Quartal).
- `edgar_13f_firmen` mit Spalte `herkunft`; Parameter-`stand` mit Zusatz „Einzelmeldungen“ für vorläufige Werte.
- Workflow `einzel`: Eingabe `pruefquartal` (Gegenprobe der Einzelmeldungen gegen ein Quartal des Datensatzes),
  lädt das Meldungsverzeichnis des laufenden und des vorigen Jahres.
- 122 Offline-Tests.

## Lieferung 7 – 2026-11-11 (Lieferausfälle, Fondsbestände, Sponsoren)

- Neue Quelle `sec_ftd`: Lieferausfälle der SEC ab 2004 → IH3-06; Tabelle `ftd_wertpapiere` (CUSIP → CIK).
- Neue Quelle `edgar_13f`: Bestände der 13F-Manager ab 2013 → IH5-04 (Änderung der Eigentümerbreite),
  IH5-03 (beste Ideen); Tabellen `edgar_13f_quartal` und `edgar_13f_bestaende`.
- `klinik`: Sponsoren und Antragsteller besser zugeordnet (Studien 53 → 65 %, neue Wirkstoffe 25 → 44 %).
- Workflow `einzel` zum Erproben einer Quelle; Release-Gruppe `*-markt`; Actions auf Node 24.
- `GW2-06` im echten Lauf bestätigt (340 Werte).
- 116 Offline-Tests.

## Lieferung 6 – 2026-11-10 (erster echter Lauf)

- Erster echter Lauf (`laufend`) mit allen neun Quellen grün; Prüfberichte ausgewertet (`UEBERGABE.md`).
- `fred`: `GW2-06` verträgt fehlende Monate (Oktober 2025); vorher fehlten alle Stände ab Dezember 2025.
- Annahmezeit als UTC von Hand bestätigt (`ENTSCHEIDUNGEN.md` Nr. 65).
- `.gitignore` angelegt.
- 103 Offline-Tests.

## Lieferung 5 – 2026-11-10 (Finanzrestriktion, Übergabe)

Diff zur Lieferung 4: `AENDERUNGEN_lieferung-5.diff`.

- `edgar_xbrl`: Whited-Wu-Index der Finanzrestriktion (GW1-04) mit Branchenwachstum des Vorjahres.
- `UEBERGABE.md`: Stand, Prüfliste der Annahmen für den ersten echten Lauf, empfohlene Reihenfolge.
- 102 Offline-Tests, unter pandas 2.3.3 und 3.0.

## Lieferung 4 – 2026-11-10 (Rollen, Gesamtwirtschaft, Web und Register)

Diff zur Lieferung 3: `AENDERUNGEN_lieferung-4.diff`.

- `edgar_rollen`: betroffene Firma aus dem Meldungskopf für Schedule 13D und Form 144 → IH5-01, IH5-02, IH1-14.
- `fred`: Zinsen, Leitzinsänderungen, Ölpreis, Produktionslücke und Inflationsänderung mit Datenständen aus
  ALFRED, Termine von Fed und Statistik → GW2-01, GW2-03, GW1-06, GW3-01, GW2-04, GW2-06, GW1-05.
- `wikipedia`: Zuordnung über Wikidata, Wochenaufrufe → WS3-05.
- Kernmodul Namensabgleich mit Konfidenz und Trefferquote.
- `cfpb`: Verbraucherbeschwerden je Firma und Monat → GA3-01.
- `klinik`: Studienergebnisse im Register und Erstzulassungen, Änderungsprotokoll → GA1-04, GA1-08.
- Workflow: zwei weitere Jobgruppen, Kettenzähler für Fortsetzungen; Releases nach Gruppen.
- Abruf: Teilabruf von Dateianfängen (`hole_anfang`).
- 101 Offline-Tests, unter pandas 2.3.3 und 3.0.

## Lieferung 3 – 2026-11-10 (Abschlüsse, laufende Insider-Ergänzung)

Diff zur Lieferung 2: `AENDERUNGEN_lieferung-3.diff`.

- Neue Quelle `edgar_xbrl`: Abschlüsse aus `companyfacts.zip`, Berichtszeilen nach der Logik des
  Insider-Monitors, daraus UA1-01 bis UA1-07, UA2-01, UA3-01, GA1-02, GA1-06, GA3-03, PR2-03.
- Insiderdaten: Quartale ohne amtlichen Datensatz werden aus den einzelnen Form-4-Dateien ergänzt
  (fortsetzbar, jede Meldung nur einmal, vom amtlichen Datensatz später ersetzt).
- Bereinigte Insidertabelle mit Spalte `herkunft`.
- Workflow: `edgar_xbrl` als dritter paralleler Job; Stand der laufenden Ergänzung wird mitgeführt.
- 62 Offline-Tests, unter pandas 2.3.3 und 3.0.

## Lieferung 2 – 2026-11-10 (Abgleich mit dem Insider-Monitor)

Diff zur Lieferung 1: `AENDERUNGEN_lieferung-2.diff`.

- pandas 2.3.3 und numpy 2.3.5 wie im Insider-Monitor; Tests laufen unter pandas 2.3.3 und 3.0.
- Kontaktadresse aus `KONTAKT_EMAIL` oder `MAIL_USER`.
- Insider-Quartalsdateien: Adressen von der SEC-Datenseite, feste Pfade als Rückfall.
- `IH1-01`, `IH1-18`: nur firmeneigene Käufer (wie `n_cluster_1m`).
- `IH1-04`: Definition des Insider-Monitors (`f_routine`, `f_opportun`).
- `IH1-06`: Verkäufe aus Meldungen mit Optionsausübung zählen zu 25 % (wie `sale_oe_weight`).
- `KD1-11`: zusätzlich Insolvenz (8-K 1.03), Übernahmeunterlagen der Zielfirma, 8-K 3.01 und Form-15-Nachträge
  (wie `classify_filings`).
- Speicher: Berechnung liest nur Käufe, Verkäufe und benötigte Formulare.
- Zeitplan Di–Sa 11:20 UTC, nach dem Tageslauf des Insider-Monitors.
- 44 Offline-Tests.

## Lieferung 1 – 2026-11-10

Erstlieferung, kein Diff zu einer Vorversion.

- Kern: Schema und Registratur, NYSE-Handelskalender mit `verfuegbar_ab`-Regel, Abruf mit
  Anfragegrenze und Wiederholung, Ablage als Parquet, Zustand und Zeitbudget, Prüfungen mit Bericht.
- EDGAR-Meldungsverzeichnis aus `submissions.zip` mit Prüfung der Zeitzone der Annahmezeit.
- Insidergeschäfte aus den SEC-Quartalsdatensätzen: IH1-01 bis IH1-07, IH1-09, IH1-10, IH1-16,
  IH1-17, IH1-18 (neu), WS3-01.
- Ereignisse aus dem Verzeichnis: WS2-04, UA1-10, UA2-03, UA2-04, IH6-04, UA4-05, GA2-03, UA4-01,
  UA3-03, UA3-04, KD1-11, WS3-02.
- Workflows `abruf` (Zeitplan und manueller Start) und `pruefen` (Tests bei jedem Push).
- 41 Offline-Tests gegen Beispieldateien im Format der Quellen.

Noch nicht gegen die echten Quellen gelaufen.
