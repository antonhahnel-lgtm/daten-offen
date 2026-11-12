# Schnittstelle zum privaten Repo

## Releases

| Release | Dateien | Inhalt |
|---|---|---|
| `parameter-edgar` | `parameter__edgar_<quelle>__<jahr>.parquet` | Parameter aus EDGAR: `edgar_insider`, `edgar_ereignisse`, `edgar_xbrl`, `edgar_rollen`, `edgar_13f` |
| `parameter-makro` | `parameter__fred__<jahr>.parquet` | Parameter der Gesamtwirtschaft (cik = 0) |
| `parameter-web` | `parameter__<quelle>__<jahr>.parquet` | `wikipedia`, `cfpb`, `klinik`, `usaspending`, `uspto_patente` |
| `bereinigt-edgar` | `bereinigt__edgar_meldungen__<jahr>.parquet` | Meldungsverzeichnis: Firma, Aktenzeichen, Formular, Annahmezeit, `verfuegbar_ab` |
| | `bereinigt__edgar_firmen__alle.parquet` | Stammdaten je CIK: Name, Ticker, SIC, Sitz |
| | `bereinigt__insider_transaktionen__<jahr>q<q>.parquet` | Alle nicht-derivativen Insidergeschäfte je Quartal; Spalte `herkunft`: `datensatz` (amtlich) oder `xml` (laufende Ergänzung) |
| | `bereinigt__edgar_abschluesse__<jahr>.parquet` | Eine Zeile je 10-K/10-Q mit den Abschlussposten (Wert, Vorjahreswert `_py`, abgedeckte Quartale `_q`), geteilt nach Einreichungsjahr |
| | `bereinigt__edgar_rollen__<jahr>.parquet` | Betroffene Firma und Einreicher je 13D- und 144-Meldung |
| | `bereinigt__edgar_13f_firmen__alle.parquet` | Je Firma (CIK) und Berichtsquartal: `halter`, `beste_idee`, `breite_aenderung`, `manager`, `manager_beide`; `herkunft`: `datensatz` (amtlich) oder `einzelmeldungen` (jüngstes Quartal, bis der Datensatz der SEC erscheint) |
| | `bereinigt__edgar_13f_quartal__alle.parquet` | Je CUSIP und Berichtsquartal: `halter`, `stueck` (alle Wertpapiere, auch Fonds) |
| | `bereinigt__edgar_13f_bestaende__<jahr>q<q>.parquet` | Je Manager (`filer_cik`) und CUSIP: Stückzahl und Portfoliogewicht (fristgerechte Erstmeldungen) |
| | `bereinigt__edgar_13f_dateien__alle.parquet` | Gelesene Datensätze mit Zahl der Meldungen; Zeile `einzel-<jahr>q<q>` für ein Quartal aus Einzelmeldungen |
| `bereinigt-makro` | `bereinigt__fred_<reihe>__alle.parquet` | Rohreihen mit allen Ständen (`von`, `bis`) und Termine |
| `bereinigt-web` | `bereinigt__wiki_wochen__alle.parquet`, `bereinigt__wiki_zuordnung__alle.parquet` | Wochenaufrufe je CIK und Zuordnung CIK → Artikel |
| | `bereinigt__cfpb_zuordnung__alle.parquet` | Firmenname → CIK mit Konfidenz |
| | `bereinigt__klinik_studien__alle.parquet`, `…_aenderungen__<jahr>`, `…_zulassungen__alle` | Studienstand, Änderungsprotokoll, Zulassungen |
| | `bereinigt__usaspending_monat__fy<jahr>.parquet` | Bundesaufträge je Konzernfamilie (`familie` = UEI der Mutter), heutigem Mutternamen, gemeldetem Namen und Monat des Bekanntwerdens: `betrag`, `zeilen`; eine Datei je Haushaltsjahr der Quelle (ein Monat kann in zweien stehen) |
| | `bereinigt__usaspending_zuordnung__alle.parquet` | Familie, Mutternamen, gemeldeter Name → CIK mit Konfidenz und Art (`exakt`, `frueher`, `kern`, `familie`, `marke`, `ungestuetzt`, `mehrdeutig`, `keiner`), dazu Betrag und Umfang |
| | `bereinigt__usaspending_dateien__alle.parquet` | Gelesene Sammeldateien je Haushaltsjahr mit Stand und Zeilenzahl |
| | `bereinigt__patente_erteilt__<jahr>.parquet` | Erteilte US-Patente je Ausgabetag (`tag`), Patentnummer, Art (`utility`, `design`, `plant`, `reissue`) und Inhaber wie gedruckt; ein Patent mit mehreren Inhabern steht mehrfach |
| | `bereinigt__patente_zuordnung__alle.parquet` | Inhabername → CIK mit Konfidenz und Art (`exakt`, `frueher`, `kern`, `tochter`, `mehrdeutig`, `keiner`), Zahl der Patente |
| | `bereinigt__patente_ausgaben__alle.parquet` | Gelesene Ausgaben des Amtsblatts mit Zahl der Patente |
| `parameter-markt` | `parameter__sec_ftd__<jahr>.parquet` | Lieferausfälle (`IH3-06`) |
| `bereinigt-markt` | `bereinigt__ftd_tage__<jahr>.parquet` | Lieferausfälle je CUSIP und Abwicklungstag (alle Wertpapiere, auch unter 10.000 Stück), Spalte `datei` |
| | `bereinigt__ftd_wertpapiere__alle.parquet` | CUSIP → CIK mit Konfidenz, Art der Zuordnung und Kennzeichen `stamm`; jüngstes Kürzel und Bezeichnung |
| | `bereinigt__ftd_dateien__alle.parquet` | Je Datei: Periodenende, Änderungszeitpunkt, Veröffentlichungszeitpunkt |
| `pruefbericht` | `pruefbericht__<quelle>.md/.json`, `manifest__<quelle>.json` | Prüfergebnis und Dateiliste des letzten Laufs |

## Schema der Parameter-Tabellen

| Spalte | Typ | Bedeutung |
|---|---|---|
| `cik` | int64 | SEC-Firmenschlüssel; `0` für marktweite Größen |
| `parameter_id` | Text | ID aus dem Parameterkatalog, z. B. `IH1-01` |
| `ereignis_zeit` | Zeitstempel UTC | Zeitpunkt, auf den sich der Wert bezieht |
| `verfuegbar_ab` | Zeitstempel UTC | frühester Zeitpunkt, zu dem ein Anleger den Wert nutzen konnte |
| `wert` | float64 | Wert; Bedeutung und Einheit stehen in `DATENBLAETTER.md` |
| `stand` | Text | Herkunft des Werts (Aktenzeichen der Meldung oder Zeitraum); bei 13F mit Zusatz „Einzelmeldungen“, solange der Datensatz der SEC fehlt |

Regel für `verfuegbar_ab`: Annahmezeit der Meldung, wenn sie an einem Handelstag vor
Börsenschluss liegt (16:00 ET, an verkürzten Tagen 13:00 ET); sonst 09:30 ET des nächsten
Handelstags.

## Lesebeispiel

Für eine Prognose zum Zeitpunkt `t` darf nur der letzte Wert mit `verfuegbar_ab <= t` verwendet werden.

```python
import pandas as pd

BASIS = "https://github.com/<konto>/daten-offen/releases/download"

def lade(quelle: str, jahre: range) -> pd.DataFrame:
    teile = [pd.read_parquet(f"{BASIS}/parameter-edgar/parameter__{quelle}__{j}.parquet") for j in jahre]   # Release je Gruppe
    return pd.concat(teile, ignore_index=True)

parameter = lade("edgar_insider", range(2023, 2027))
cluster = parameter[parameter["parameter_id"] == "IH1-01"].sort_values("verfuegbar_ab")

# Tabelle mit den Prognosezeitpunkten je Firma (Spalten: cik, zeitpunkt als UTC-Zeitstempel)
anfragen = pd.DataFrame({"cik": [320193], "zeitpunkt": pd.to_datetime(["2026-11-10 15:00"], utc=True)})
anfragen["zeitpunkt"] = anfragen["zeitpunkt"].astype("datetime64[us, UTC]")

stichtagsecht = pd.merge_asof(
    anfragen.sort_values("zeitpunkt"), cluster[["cik", "verfuegbar_ab", "wert"]],
    left_on="zeitpunkt", right_on="verfuegbar_ab", by="cik", direction="backward")
```

Für Fenstergrößen (z. B. alle Käufe der letzten 60 Tage) gilt dieselbe Bedingung
`verfuegbar_ab <= zeitpunkt`.

## Verknüpfung mit dem Insider-Monitor

- Firmenschlüssel: `issuer_cik` in `data/trades.parquet` ist eine Gleitkommazahl; vor dem Verknüpfen
  in eine Ganzzahl wandeln (`issuer_cik.astype("Int64")`).
- Zeitbezug: `filing_dt` im Insider-Monitor ist ohne Zeitzone in Ostküstenzeit gespeichert. Für den
  Vergleich mit `verfuegbar_ab`: `filing_dt.dt.tz_localize("America/New_York").dt.tz_convert("UTC")`.
- Gleich definiert wie im Insider-Monitor: `IH1-01` (= `n_cluster_1m`), `IH1-04` (= `f_routine` 1 /
  `f_opportun` 0), Verkaufsgewicht 0,25 in `IH1-06`, Einstufung in `KD1-11` (= `classify_filings`),
  `UA1-02` (= `fin_lage_roh`: +1 positiv, 0 gemischt, −1 negativ), `UA1-07` (= `fin_runway_q`).
- Die Spalten von `edgar_abschluesse` heißen wie in `data/fundamentals.csv` (`revenue`, `revenue_py`,
  `revenue_q`, `net_income`, `op_cf`, `cash`, `sti`, `debt`, `assets`, `equity`, `shares`, `rev_src`).
