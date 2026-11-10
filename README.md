# daten-offen

Ruft frei veröffentlichbare Daten für den Insider-Monitor ab, prüft sie und stellt sie als
stichtagsechte Tabellen bereit. Oberstes Ziel des Projekts ist, möglichst hohe Renditen zu
erwirtschaften; dieses Repo liefert dafür die Daten, in denen Muster gesucht werden. Score,
Kombination und Auswertung liegen im privaten Repo.

## Stand

| Baustein | Parameter | Stand |
|---|---|---|
| Kern: Schema, Handelskalender, Abruf, Ablage, Prüfung, Namensabgleich, Workflow | – | gebaut, offline getestet |
| EDGAR: Meldungsverzeichnis mit Annahmezeiten | – | gebaut, offline getestet |
| EDGAR: Insidergeschäfte, mit laufender Ergänzung aus Form-4-Dateien | 13 | gebaut, offline getestet |
| EDGAR: Ereignisse aus 8-K, Form D, 424B, S-3, Form 25/15, Übernahmeunterlagen | 12 | gebaut, offline getestet |
| EDGAR: Abschlüsse aus XBRL | 14 | gebaut, offline getestet |
| EDGAR: Rollen in Schedule 13D und Form 144 | 3 | gebaut, offline getestet |
| Gesamtwirtschaft: FRED/ALFRED mit Datenständen, Termine | 7 | gebaut, offline getestet |
| Aufmerksamkeit: Wikipedia-Aufrufe | 1 | gebaut, offline getestet |
| Register: CFPB-Beschwerden, klinische Studien, Zulassungen | 3 | gebaut, offline getestet |
| Weitere Quellen | – | offen, siehe `ENTSCHEIDUNGEN.md` |

Noch keine Quelle ist gegen die echten Schnittstellen gelaufen.

## Einrichten

1. Öffentliches Repo anlegen und den Inhalt dieses Ordners hochladen.
2. Unter *Settings → Secrets and variables → Actions* das Secret `KONTAKT_EMAIL` anlegen – dieselbe
   Adresse wie `MAIL_USER` im Insider-Monitor genügt (die SEC verlangt eine Kontaktadresse im
   User-Agent; sie steht nie im Code).
3. Das Secret `FRED_API_KEY` anlegen (kostenloser Schlüssel von fred.stlouisfed.org). Fehlt er,
   scheitert nur die Quelle `fred`.
4. Unter *Actions* den Workflow **abruf** starten – zuerst im Modus `laufend`, danach einmal im Modus
   `rueckwaerts` für die Historie der 13D- und 144-Meldungen.

Für spätere Bausteine: `DATA_GOV_API_KEY` (openFEC, Congress.gov), `USPTO_ODP_API_KEY`.

## Ablauf eines Laufs

`abruf.yml` läuft Dienstag bis Samstag um 11:20 UTC oder von Hand:

1. `edgar_index` baut das Meldungsverzeichnis aus der SEC-Sammeldatei.
2. Darauf laufen parallel `edgar_insider`, `edgar_ereignisse`, `edgar_xbrl`, `edgar_rollen`, `cfpb`, `klinik`.
3. Unabhängig davon laufen `fred` und `wikipedia`.
4. `abschluss` lädt alles als Release-Assets hoch und zeigt die Prüfberichte in der Zusammenfassung.

Erreicht ein Lauf das Zeitbudget, speichert er seinen Stand und startet sich selbst neu.
Scheitert eine Quelle, werden ihre Ergebnisse nicht veröffentlicht; die anderen laufen weiter.

## Dateien

| Datei | Inhalt |
|---|---|
| `SCHNITTSTELLE.md` | Release-Namen, Schema, Lesebeispiel |
| `DATENBLAETTER.md` | Definition, Quelle, Lizenz und Schwächen je Parameter (aus dem Code erzeugt) |
| `ENTSCHEIDUNGEN.md` | Getroffene Festlegungen mit Begründung |
| `UEBERGABE.md` | Stand, Prüfliste für den ersten echten Lauf, empfohlene Reihenfolge |
| `AENDERUNGEN.md` | Änderungen je Lieferung |

## Lokal prüfen

```
pip install -r requirements-test.txt
python -m pytest tests -q
```

Die Tests brauchen keinen Netzzugang; sie erzeugen kleine Beispieldateien im Format der Quellen.

## Lizenz der Daten

Die Daten stammen von US-Behörden (gemeinfrei) sowie aus Wikipedia und Wikidata (CC0). Kurse, FINRA-
und Optionsdaten sowie Reihen Dritter liegen bewusst nicht in diesem Repo.
