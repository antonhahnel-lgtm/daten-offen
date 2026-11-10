# Übergabe

Stand 10.11.2026, Lieferung 5. Diese Datei reicht zusammen mit dem Repo-Zip, `PARAMETERKATALOG.md`
und dem Auftragstext, um in einem neuen Chat weiterzuarbeiten.

## Ziel

Möglichst hohe Renditen erwirtschaften; dafür Muster erkennen, die überdurchschnittliche Renditen
vorhersagen. Dieses Repo liefert die stichtagsechten Daten, Score und Auswertung liegen im privaten
Insider-Monitor.

## Was gebaut ist

| Quelle | Parameter | Offline getestet | Echter Lauf |
|---|---|---|---|
| `edgar_index` | – (Zeitbasis) | ja | nein |
| `edgar_insider` | IH1-01 bis IH1-07, IH1-09, IH1-10, IH1-16, IH1-17, IH1-18, WS3-01 | ja | nein |
| `edgar_ereignisse` | WS2-04, UA1-10, UA2-03, UA2-04, IH6-04, UA4-05, GA2-03, UA4-01, UA3-03, UA3-04, KD1-11, WS3-02 | ja | nein |
| `edgar_xbrl` | UA1-01 bis UA1-07, UA2-01, UA3-01, GA1-02, GA1-06, GA3-03, PR2-03, GW1-04 | ja | nein |
| `edgar_rollen` | IH5-01, IH5-02, IH1-14 | ja | nein |
| `fred` | GW2-01, GW2-03, GW1-06, GW3-01, GW2-04, GW2-06, GW1-05 | ja | nein |
| `wikipedia` | WS3-05 | ja | nein |
| `cfpb` | GA3-01 | ja | nein |
| `klinik` | GA1-04, GA1-08 | ja | nein |

53 Parameter, 102 Tests (pandas 2.3.3 und 3.0). Kein Modul hat bisher die echte Schnittstelle gesehen:
Die Testdateien bilden die Formate nach, wie sie dokumentiert oder im Insider-Monitor erprobt sind.

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

## Empfohlene Reihenfolge

1. Repo anlegen, Secrets `KONTAKT_EMAIL` und `FRED_API_KEY` setzen, Workflow `abruf` im Modus `laufend` starten.
2. Log bzw. Prüfberichte auswerten, Abweichungen von der Prüfliste beheben, bis alle neun Quellen grün sind.
3. Einmal im Modus `rueckwaerts` starten (Historie der 13D- und 144-Meldungen; setzt sich selbst fort).
4. Erst danach die offenen Bausteine (Tabelle „Noch offen“ in `ENTSCHEIDUNGEN.md`), beginnend mit den
   Quellen, die den Namensabgleich nutzen, weil dessen Trefferquote dann bekannt ist.
5. Anbindung im Insider-Monitor (eigener Auftrag; `SCHNITTSTELLE.md` beschreibt das Lesen).

## Dateien für einen neuen Chat

- neuestes Repo-Zip (`daten-offen_lieferung-<n>.zip`)
- `PARAMETERKATALOG.md` (IH1-18 „Tagescluster“ dort nachtragen)
- Auftragstext „Öffentliches Datenrepo bauen (selbstständig)“
- nach dem ersten Lauf: Log oder die Dateien des Release `pruefbericht`
- nur bei Bedarf: Repo-Zip des Insider-Monitors (Abgleich ist erfolgt, siehe `ENTSCHEIDUNGEN.md` Nr. 27–35)
