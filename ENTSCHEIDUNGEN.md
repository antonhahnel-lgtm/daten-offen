# Entscheidungen

Festlegungen, die beim Bau ohne Rückfrage getroffen wurden. Maßstab ist das Projektziel:
Muster erkennen, die überdurchschnittliche Renditen vorhersagen – also stichtagsechte,
lange und saubere Daten vor Vollständigkeit.

## Grundlagen

| Nr. | Entscheidung | Grund |
|---|---|---|
| 1 | Abgeglichen mit dem Insider-Monitor (Stand des Repo-Zips vom 10.11.2026): Python 3.12, pandas 2.3.3, Secret `MAIL_USER` als Kontaktadresse, Linksuche auf der SEC-Datenseite, Definitionen von Cluster, Routine, Verkaufsgewicht und Delisting-Einstufung übernommen (Nr. 27–33). | Beide Repos sollen dieselben Begriffe gleich messen; nur dann sind die Messergebnisse des Insider-Monitors auf diese Daten übertragbar. |
| 2 | Marktweite Größen tragen `cik = 0`. | Ein Schema für alle Parameter. |
| 3 | Rohdaten der SEC werden nicht gespiegelt, weil die SEC sie dauerhaft und vollständig bereitstellt. Gespeichert werden die bereinigte Schicht und die Parameter. | Spart mehrere Gigabyte je Lauf ohne Informationsverlust; EDGAR-Meldungen sind unveränderlich, Nachträge sind eigene Meldungen. |
| 4 | Python 3.12 mit fest angehefteten Paketversionen, pandas 2.3.3 wie im Insider-Monitor. Die Tests laufen zusätzlich unter pandas 3. | Gleiche Ergebnisse in Test und Betrieb; Parquet-Dateien in beiden Repos gleich lesbar. |
| 5 | Ticker-Historie gibt es bei der SEC nicht; verknüpft wird ausschließlich über die CIK. Die Firmentabelle führt den aktuellen Ticker und frühere Firmennamen. | Die CIK ist der einzige stabile Schlüssel. |

## Zeit und Stichtag

| Nr. | Entscheidung | Grund |
|---|---|---|
| 6 | `verfuegbar_ab` ist der früheste handelbare Zeitpunkt: die Annahmezeit, wenn sie an einem Handelstag vor Börsenschluss liegt, sonst 09:30 ET des nächsten Handelstags. Vorbörsliche Annahmen zählen mit ihrer Uhrzeit. | Vorgabe; vorbörslich bekannte Information ist zur Eröffnung handelbar. |
| 7 | Verkürzte Handelstage (Tag nach Thanksgiving, 24.12., 03.07.) schließen um 13:00 ET. Der NYSE-Kalender ist selbst gerechnet und gegen die amtlichen Feiertage 2020–2026 getestet; außerplanmäßige Schließungen sind als Liste hinterlegt. | Keine Abhängigkeit von einem Fremdpaket; neue Sonderschließungen müssen nachgetragen werden. |
| 8 | Die Annahmezeit der SEC-Sammeldatei trägt keine verlässliche Zeitzone. Jeder Lauf prüft am jüngsten vollständigen Jahr, ob Ostküstenzeit oder UTC das Einreichungsdatum besser trifft (Annahmeschluss 17:30 ET), wählt die bessere Lesart und meldet beide Trefferquoten. Unter 0,9 gilt der Lauf als fehlgeschlagen. | Ein Fehler von vier bis fünf Stunden würde Scheinmuster erzeugen. |
| 9 | Fehlt die Annahmezeit, gilt der Einreichungstag 17:30 ET; der Wert ist damit erst am nächsten Handelstag nutzbar und als geschätzt markiert. | Vorsichtige Seite. |
| 10 | Die Ereigniszeit eines Insidergeschäfts ist Mitternacht (ET) des Geschäftstags und nie später als die Annahme der Meldung. Geschäfte mit Datum nach der Einreichung oder mehr als drei Jahre davor werden verworfen und gezählt. | Schutz gegen Datumsfehler der Quelle. |

## EDGAR-Parameter

| Nr. | Entscheidung | Grund |
|---|---|---|
| 11 | Insiderdaten kommen aus den amtlichen Quartalsdatensätzen (ab 2006) statt aus Millionen einzelner Form-4-Abrufe. Die Annahmezeit je Meldung wird über das Aktenzeichen aus dem Meldungsverzeichnis ergänzt. Die jüngsten zwei Quartale werden bei jedem Lauf neu geladen. Quartale, für die es noch keinen Datensatz gibt, werden aus den einzelnen Form-4-Dateien ergänzt (Nr. 43). | Ein Lauf statt tagelangem Abruf, ohne dass das laufende Quartal fehlt. |
| 12 | Bei Nachträgen (4/A) werden nur Geschäfte übernommen, die im Original nicht schon stehen. | Sonst zählten korrigierte Meldungen doppelt. |
| 13 | Bei Meldungen mehrerer Personen zählt die erstgenannte Person; die Zahl der Meldenden wird mitgeführt. | Geschäfte gehören zur Meldung, nicht zu einer einzelnen Person. |
| 14 | Kauf = Code P mit Erwerb, Verkauf = Code S mit Veräußerung, jeweils Stück und Preis über null. Derivate, Zuteilungen und Optionsausübungen bleiben in der bereinigten Schicht bzw. außen vor. | Nur Geschäfte am offenen Markt tragen das Signal. |
| 15 | Cluster, Tagescluster und Netto-Kaufquote zählen nur Geschäfte, deren Meldung zum Zeitpunkt der betrachteten Kaufmeldung schon verfügbar war. | Stichtagsechtheit. |
| 16 | Neue ID `IH1-18` (Tagescluster), weil `IH1-01` den 30-Tage-Cluster trägt und eine ID nur eine Messgröße haben kann. Im Parameterkatalog nachzutragen. | IDs werden nie umgewidmet. |
| 17 | `IH1-04` folgt der Definition des Insider-Monitors (f_routine, f_opportun), nicht der strengeren Fassung von Cohen, Malloy & Pomorski (2012). | Der Insider-Monitor hat seine Messung (Stufe 4.1) mit dieser Definition gemacht. |
| 18 | `IH1-03` liefert die Kaufsumme in Dollar. Verhältnisse zu Marktkapitalisierung und Gehalt, die Trefferbilanz (`IH1-08`) und das Signalalter (`IH1-12`) entstehen im privaten Repo. | Sie brauchen Kurse oder sind reine Zeitdifferenzen zum Prognosezeitpunkt. |
| 19 | Ereignis-Parameter stammen nur aus Formularen, die die Firma selbst einreicht oder die sie eindeutig betreffen. 8-K/A zählen nicht. Bei Form 25 gelten Einreicher mit mehr als 200 solchen Meldungen als Börse und werden ausgeschlossen. | Vermeidet falsche Zuordnung und Doppelzählung. |
| 20 | Schedule 13D (`IH5-01`) und Form 144 (`IH1-14`) sind noch nicht gebaut: Beide Formulare stehen im Verzeichnis unter Einreicher und betroffener Firma; die Rollen müssen aus dem Meldungskopf gelesen werden. | Ohne Rollen würde der Einstieg eines Unternehmens bei einem anderen der falschen Firma zugeordnet. |
| 21 | Kodierungen: `IH1-02` Stufen 0–4, `UA3-03` Art 1–3, `KD1-11` Art 1–2, `UA1-10`/`WS3-01` Wochentag plus Tagesbruchteil. Details in `DATENBLAETTER.md`. | Das Schema kennt nur Zahlenwerte. |
| 22 | `WS3-01` wird für Kaufmeldungen geliefert, `UA1-10` für Zahlenmeldungen; für andere Formulare lässt sich die Größe aus dem Meldungsverzeichnis ableiten. | Hält die Parameter-Tabellen klein. |

## Betrieb

| Nr. | Entscheidung | Grund |
|---|---|---|
| 23 | Das Meldungsverzeichnis wird bei jedem Lauf vollständig neu aufgebaut. | Die SEC erzeugt die Sammeldatei jede Nacht neu; ein Pfad statt zweier. |
| 24 | Schwere Fehler einer Quelle: Ihre Ergebnisse werden nicht veröffentlicht, der letzte gute Stand bleibt im Release, der Job endet rot; andere Quellen laufen weiter. | Vorgabe. |
| 25 | Schwer sind: Abbruch, keine Zeilen, Stichtagsverstöße, unendliche Werte, über 1 % Dubletten, Einbruch der Zeilenzahl um mehr als 20 % zum Vorlauf, fehlende ältere Quartale, über 2 % unplausible Geschäftsdaten, über 5 % fehlende Annahmezeiten, unsichere Zeitzone. | Fehler sollen den Lauf anhalten, nicht die Daten verfälschen. |
| 26 | Der Modus `rueckwaerts` unterscheidet sich bisher nicht von `laufend`, weil die EDGAR-Sammeldateien die ganze Historie in einem Abruf liefern. Er wird für die Quellen mit Einzelabrufen gebraucht. | – |

## Abgleich mit dem Insider-Monitor (Lieferung 2)

| Nr. | Entscheidung | Grund |
|---|---|---|
| 27 | Kontaktadresse für den User-Agent aus `KONTAKT_EMAIL`, ersatzweise `MAIL_USER`. | Der Insider-Monitor nutzt `MAIL_USER`; dieselbe Adresse kann übernommen werden. |
| 28 | Die Adressen der Insider-Quartalsdateien werden wie im Insider-Monitor von der SEC-Datenseite gelesen; zwei feste Pfade sind Rückfall. | Die SEC hat den Ablageort bereits verlegt; die Seite ist die verlässlichste Angabe. |
| 29 | `IH1-01` und `IH1-18` zählen nur firmeneigene Käufer; externe Käufer (10-%-Eigner ohne Amt) zählen nicht mit, sehen aber den Cluster. `IH1-01` entspricht damit `n_cluster_1m` (30 Tage). Das 14-Tage-Fenster (`n_cluster`) entsteht bei Bedarf im privaten Repo aus den bereinigten Geschäften. | Definition des Insider-Monitors. |
| 30 | Routine zählt nur Käufe (nicht Verkäufe), wie `routine_years` und `vorjahre_mit_kauf`. | Wie Nr. 17. |
| 31 | `IH1-06` gewichtet Verkäufe aus Meldungen mit Optionsausübung (Code M) mit 0,25 wie `sale_oe_weight`. Kurzfrist-Händler werden nicht abgewertet, weil ihre Einstufung Kurse braucht. Das Warnsignal „Verkaufsdruck“ (`vd_ratio`) rechnet der Insider-Monitor weiter selbst; `IH1-06` ist eine zusätzliche, stetige Größe. | Gleiche Gewichtung, andere Fragestellung. |
| 32 | `KD1-11` übernimmt die Einstufung von `classify_filings`: Insolvenz (8-K 1.03), Übernahme, Abmeldung (Form 15/25), dazu 8-K 3.01 als Hinweis. Übernahme nur aus Unterlagen der Zielfirma (PREM14A/C, DEFM14A/C, SC 14D9); SC TO-T und SC 13E3 fehlen, bis die Rollen gelesen werden. | Die Zielgröße des Insider-Monitors bewertet Insolvenzen mit −100 %; dafür muss die Einstufung gleich sein. |
| 33 | Der Insider-Monitor lädt 8-K-Meldungen, Abschlüsse, 424B, 13D, Item 408 und Delistings bisher selbst, je Firma und nur mit Einreichungsdatum. Dieses Repo liefert dieselben Ereignisse für alle Firmen und mit Annahmezeit. Der Insider-Monitor wird nicht verändert; ob er später hierauf umstellt, ist eine eigene Entscheidung. | Vorgabe: privates Repo nicht verändern. |
| 34 | Zeitplan Di–Sa 11:20 UTC, nach dem Tageslauf des Insider-Monitors (10:45 UTC). | Keine gleichzeitige Last bei der SEC. |
| 35 | Für die Berechnung werden nur Käufe und Verkäufe sowie die benötigten Meldungsformulare gelesen. | Die vollständige Historie seit 2006 passt sonst nicht sicher in den Arbeitsspeicher eines GitHub-Runners. |

## Abschlüsse und laufende Ergänzung (Lieferung 3)

| Nr. | Entscheidung | Grund |
|---|---|---|
| 36 | Die Berichtszeilen der Abschlüsse folgen der Logik des Insider-Monitors (`xbrl_rows`, `FIN_TAGS`, Zeitraumklassen Q/H/T/Y), ergänzt um weitere Posten. Quelle ist die Sammeldatei `companyfacts.zip` statt eines Abrufs je Firma. Ausgewertet werden nur 10-K und 10-Q, keine Nachträge und keine ausländischen Formulare. | Die Logik ist an echten Daten erprobt; die Sammeldatei liefert alle Firmen in einem Abruf. |
| 37 | Abschlusskennzahlen gelten ab der Annahme des 10-Q/10-K, nicht ab der Ergebnis-Pressemitteilung. | Die Pressemitteilung enthält keine strukturierten Zahlen; lieber zu spät als zu früh datiert. Für die Drift nach Zahlen ist der Zeitpunkt der 8-K 2.02 (`UA1-10`) getrennt verfügbar. |
| 38 | Je Periodenende zählt die zuerst eingereichte Fassung. Spätere Vergleichszahlen in Folgeberichten ändern frühere Werte nicht. | Stichtagsechtheit: So sah der Anleger die Zahl damals. |
| 39 | Einzelquartale werden aus aufgelaufenen Werten abgeleitet (Halbjahr minus erstes Quartal usw., viertes Quartal aus dem Jahreswert). Fehlt ein Vorquartal, bleibt der Wert leer. | Die Kapitalflussrechnung im 10-Q ist immer aufgelaufen; ein falscher Wert wäre schlimmer als ein fehlender. |
| 40 | `UA1-01` nutzt den Nettogewinn und die saisonale Differenz zum Vorjahresquartal, geteilt durch die Streuung der acht Vorquartale (mindestens vier). | Analystenschätzungen sind nicht offen; das ist die Definition der Ursprungsstudien zur Drift nach Gewinnmeldungen. |
| 41 | `UA1-02` und `UA1-07` übernehmen die Definitionen `fin_lage_roh` und `fin_runway_q`. Die Sperren und Plausibilitätsschwellen, die Kurse oder den Kaufzeitpunkt brauchen, bleiben im Insider-Monitor. | Wie Nr. 1. |
| 42 | `UA1-04` ist eine Näherung (operativer Cashflow / Bilanzsumme). `UA1-06` und `UA2-01` entstehen nur, wenn alle Bausteine vorliegen. `GA1-06` ist nicht preisbereinigt. `GA1-02` liefert Dollarbeträge; das Verhältnis zum Marktwert entsteht privat. | Lieber weniger Werte als geschätzte Bausteine. |
| 43 | `UA3-01` ist nicht splitbereinigt: Veränderungen der Aktienzahl über Faktor 3 (oder unter ein Drittel) werden als Split-Verdacht verworfen und gezählt. Die Angabe vom Deckblatt hat Vorrang vor der Bilanzangabe. | Splitfaktoren brauchen Kursdaten; die saubere Bereinigung gehört ins private Repo. |
| 44 | Noch nicht gebaut: `UA1-08` (die Bausteine stehen in der bereinigten Schicht), `GA1-03`, `UA2-02`, `GW1-04` sowie alles, was Segment- oder Kundenangaben braucht (`WS3-03`, `GA4-05`) – die Sammeldatei enthält keine nach Segmenten gegliederten Angaben. `UA1-09` und `IH6-03` brauchen Kurse und entstehen privat. | Reihenfolge nach Nutzen; dimensionale Angaben verlangen die Einzelberichte. |
| 45 | Laufende Ergänzung der Insiderdaten: Für Quartale nach dem letzten amtlichen Datensatz wird jede Form-4-Meldung des Verzeichnisses einmal als Rohdatei gelesen (Stand je Aktenzeichen gespeichert, Abbruch am Zeitbudget mit Fortsetzung). Erscheint der amtliche Datensatz, ersetzt er das Quartal. | Früherkennung braucht die Käufe der letzten Wochen; die Quartalsdatensätze kommen erst nach Quartalsende. |
| 46 | Nach 25 Abruffehlern in Folge bricht die laufende Ergänzung als Fehler ab; einzelne Fehler werden beim nächsten Lauf erneut versucht. Nicht lesbare oder fehlende Dateien werden vermerkt und nicht wieder abgerufen. | Eine Sperre der Quelle soll auffallen, einzelne Ausfälle sollen nicht stören. |
| 47 | Abweichung vom Insider-Monitor bei der Aktienzahl: Sie bestimmt das Periodenende einer Berichtszeile nicht mit, und fehlt der Stichtagswert, tritt der gewichtete Durchschnitt an seine Stelle. | Manche Firmen weisen die Aktienzahl zum Deckblattdatum aus; die Zeile bliebe sonst bis auf die Aktienzahl leer. |

## Rollen, Gesamtwirtschaft, Web und Register (Lieferung 4)

| Nr. | Entscheidung | Grund |
|---|---|---|
| 48 | Schedule 13D und Form 144: Die betroffene Firma wird aus dem Kopf der Einreichungsdatei gelesen (nur die ersten 12 KB je Meldung). Neueste Meldungen zuerst; im Tagesbetrieb höchstens 45 Minuten Nachholen, die ganze Historie im Modus `rueckwaerts`. | Ohne Rollen würde der Einstieg einer Firma bei einer anderen der falschen zugeordnet (Nr. 20). Die Historie umfasst mehrere hunderttausend Meldungen. |
| 49 | `IH5-01`, `IH5-02`, `IH1-14` sind vorerst reine Ereigniskennzeichen. Beteiligungshöhe, Ziel und Stückzahl stehen im Text bzw. in der Datei der Meldung und folgen später. | Erst die sichere Zuordnung, dann die Inhalte. |
| 50 | FRED: nur Reihen amtlicher US-Stellen (Fed, Treasury, BLS, EIA). Nicht aufgenommen: Konsumklima (Universität Michigan), VIX (Cboe), Politikunsicherheit EPU (Autoren), Excess Bond Premium. | Urheber sind Dritte oder die Lizenz ist unklar. EPU und Zinskurve führt der Insider-Monitor bereits selbst (`marktlage_extern.csv`). |
| 51 | Zinsüberraschungen der San Francisco Fed (`GW1-01`, `GW1-02`) werden nicht hier abgerufen. | Reservebanken sind keine Bundesbehörden; die Weitergabe ist nicht eindeutig erlaubt. Der Abruf gehört ins private Repo. |
| 52 | Revidierte Monatsreihen kommen mit allen Ständen aus ALFRED. Jede Kennzahl wird mit dem Datenstand ihres Veröffentlichungstags gerechnet; Revisionen erzeugen neue Zeilen mit eigenem `stand`. | Die heute sichtbaren Werte waren damals nicht bekannt. |
| 53 | `GW2-04` nutzt einen Echtzeit-Trend (quadratisch, ab 1960, bis zum jeweiligen Stand). `GW2-06` ist die Änderung der Jahresinflation als Ersatz für die unerwartete Inflation. | Die Ursprungsstudie schätzt den Trend über die ganze Stichprobe, was in die Zukunft blickt; Markterwartungen sind nicht offen. |
| 54 | `GW1-06` setzt den früheren Zielsatz (bis 15.12.2008) und die obere Grenze der Zielspanne zusammen. | Eine durchgehende Reihe der Leitzinsänderungen. |
| 55 | `GW1-05` liest die Termine aus der Veröffentlichungsliste von FRED (auch künftige) und nimmt an, dass sie 28 Tage vorher bekannt waren. Fehlt eine der drei Veröffentlichungen unter ihrem Namen, steht das als Hinweis im Prüfbericht. | Die Terminpläne erscheinen Monate im Voraus; 28 Tage sind die vorsichtige Seite. |
| 56 | Wikipedia: Zuordnung Firma → Artikel über Wikidata (Eigenschaft P5531). Gespeichert werden Wochensummen, nicht Tageswerte. Kennzahl nach Da, Engelberg & Gao (2011). Die laufende Woche bleibt außen vor; ein Wert gilt ab Dienstag der Folgewoche. | Wochensummen halten die Tabelle klein (rund 5 statt 30 Millionen Zeilen) und entsprechen der Studie. |
| 57 | Die heutige Wikidata-Zuordnung gilt rückwirkend. | Frühere Zuordnungen sind nicht abrufbar; der Fehler betrifft umbenannte oder übernommene Firmen. |
| 58 | Namensabgleich als Kernmodul mit Konfidenz: exakt 1,00; früherer Name 0,95; ohne Zusätze wie HOLDINGS 0,90; ähnlich unter 0,90. Übernommen werden nur Zuordnungen ab 0,90. Mehrdeutige Namen bleiben offen, außer genau eine der Firmen ist börsennotiert. Verglichen wird nur mit Unternehmen (Branchenschlüssel oder Ticker), nicht mit Privatpersonen. | Eine falsche Zuordnung erzeugt Scheinmuster; eine fehlende kostet nur Abdeckung. Die Trefferquote steht je Quelle im Prüfbericht. |
| 59 | CFPB-Beschwerden (`GA3-01`) als erste Quelle mit Namensabgleich; ein Monatswert gilt 30 Tage nach Monatsende als bekannt. | Beschwerden werden erst nach der Antwort der Firma veröffentlicht, spätestens nach 15 Tagen. |
| 60 | Klinische Studien: Abruf aller Phase-2/3-Studien mit den im Insider-Monitor erprobten Feldern; Auswertung nur für Industrie-Sponsoren. Stichtagsecht ist allein das Einstelldatum der Ergebnisse (`GA1-04`). Termine und Statuswechsel werden ab dem ersten Lauf in einem Änderungsprotokoll festgehalten. | Das Register zeigt nur den heutigen Stand; rückwirkend lässt sich nicht sagen, wann ein Termin verschoben wurde. |
| 61 | `GA1-08` liefert tatsächliche Erstzulassungen aus Drugs@FDA, nicht künftige Zieltermine. | Zieltermine veröffentlicht nur die Firma (8-K, Pressemitteilung). |
| 62 | Selbst gestartete Fortsetzungen tragen einen Zähler; nach zwölf in Folge endet die Kette mit einer Warnung. | Schutz vor einer Endlosschleife, falls eine Quelle nicht vorankommt. |
| 63 | Releases nach Gruppen: `*-edgar`, `*-makro`, `*-web`. Das Veröffentlichungsskript bricht ab, wenn eine erzeugte Datei keinem Release zugeordnet ist. | Keine Datei soll unbemerkt liegen bleiben. |
| 64 | `GW1-04` (Whited-Wu-Index) aus Jahresabschlüssen statt Quartalswerten, Bilanzsumme nicht preisbereinigt; das Branchenwachstum (dreistelliger SIC, mindestens drei Firmen) stammt aus dem Vorjahr. | Das Branchenwachstum des laufenden Jahres ist am Stichtag eines einzelnen Jahresberichts noch nicht vollständig gemeldet. |

## Erster echter Lauf (Lieferung 6)

| Nr. | Entscheidung | Grund |
|---|---|---|
| 65 | Die Annahmezeit der Sammeldatei ist UTC (Lauf vom 10.11.2026: Trefferquote UTC 0,937, ET 0,392). Von Hand bestätigt an den Index-Seiten der SEC, die Ostküstenzeit zeigen: 8-K vom 30.07.2026 `20:30:28Z` = 16:30:28 EDT, Form 4 vom 26.02.2026 `23:33:14Z` = 18:33:14 EST. Die automatische Erkennung (Nr. 8) bleibt als Schutz. | Sommer- und Winterzeit stimmen; damit ist `verfuegbar_ab` richtig. |
| 66 | `GW2-06`: Der Vormonat ist der jüngste vorhandene Monat davor, höchstens zwei Monate zurück; die Vorjahreswerte müssen genau zwölf Monate zurück vorliegen, sonst entfällt der Stand. | Der Verbraucherpreisindex für Oktober 2025 wurde wegen des Shutdowns nie veröffentlicht. Die alte Regel verlangte 14 lückenlose Monate und verlor dadurch alle Stände ab Dezember 2025. Jetzt entfallen nur Oktober und November 2026 (Vorjahresmonat Oktober 2025 fehlt). |

## Lieferausfälle, Fondsbestände, Sponsoren (Lieferung 7)

| Nr. | Entscheidung | Grund |
|---|---|---|
| 67 | `IH3-06` kommt aus den Fails-to-Deliver-Dateien der SEC (ab 03/2004), nicht aus den Threshold-Listen der Börsen. Wert ist der Bestand in Stück je Abwicklungstag, nur ab 10.000 Stück je Gattung (erste Bedingung der Threshold-Liste). | Die Börsenlisten sind nur tagesaktuell abrufbar, die SEC-Dateien reichen 22 Jahre zurück. Bis 15.09.2008 enthält die Quelle ohnehin nur Bestände ab 10.000 Stück; so bleibt die Reihe durchgehend vergleichbar. |
| 68 | Das Verhältnis zu den ausstehenden Aktien (zweite Bedingung, 0,5 %) und die Dauer (fünf Abwicklungstage) entstehen privat aus `IH3-06` und `UA3-01`. | Wie bei `GA1-02` (Nr. 42): Verhältnisse über Quellen hinweg entstehen privat. |
| 69 | Die Preisspalte der SEC-Dateien wird nicht übernommen. | Keine Kurse im öffentlichen Repo. |
| 70 | Veröffentlichungstag einer Datei ist ihr Änderungszeitpunkt beim Server der SEC, wenn er höchstens 90 Tage nach dem Periodenende liegt; sonst gilt die feste Frist von 30 Tagen (Quartalsdateien bis 2009: 60 Tage). Der zuerst festgestellte Zeitpunkt bleibt bestehen. | Gemessen am 11.11.2026 an allen 437 Dateien: üblich sind 14–19 Tage, einzelne Dateien kamen bis zu 68 Tage später (z. B. nach dem Shutdown 2025). Der Änderungszeitpunkt liegt nie vor der Erstveröffentlichung; ältere Dateien wurden 2020 neu hochgeladen und tragen deshalb die Frist. |
| 71 | Zuordnung CUSIP → CIK in drei Stufen: jüngstes Kürzel der CUSIP gehört heute genau einer Firma und die Bezeichnung beginnt wie deren (auch früherer) Name (0,98); Kürzel passt und die CUSIP war in den letzten 400 Tagen aktiv (0,93); sonst Namensabgleich über die Bezeichnung (Nr. 58). Nur Stammaktien und Hinterlegungsscheine, keine Vorzüge, Optionsscheine, Units, Anleihen, Fonds (SIC 6726, 6221). | Ein neu vergebenes Kürzel darf alte Lieferausfälle nicht der heutigen Firma zuschreiben; delistete Firmen sollen erhalten bleiben (kein Überlebensfehler). |
| 72 | Die Tabelle `ftd_wertpapiere` (CUSIP → CIK) ist die gemeinsame Grundlage für alle Quellen, die nur die CUSIP nennen (13F, N-PORT). | Eine frei veröffentlichbare CUSIP-Zuordnung gibt es sonst nicht; die Lizenz der CUSIP-Stammdaten ist kostenpflichtig. |
| 74 | Als Stammaktie gilt ein Papier nur, wenn seine Gattungsangabe leer ist oder wie bei einer Aktie beginnt (COM, ORD, CL, ADR …) und kein Wort einer anderen Gattung enthält. Trägt es ein Kürzel der Firma, muss es zudem deren Hauptkürzel sein oder genau den Firmennamen tragen. Ohne Kürzel wird über den Namen nur zugeordnet, wenn er kein Fondsname ist und mit einer Rechtsform endet oder die Gattung eindeutig ist. | Am echten Bestand geprüft: Emittenten führen Zertifikate (z. B. 59 Papiere der Bank of Montreal), Vorzüge und Units unter eigenen Kürzeln; Fonds heißen oft wie ihre Verwaltungsfirma. Lieber eine Gattung weniger als fremde Lieferausfälle bei der Firma. |
| 75 | 13F: je Berichtsquartal zählen nur fristgerechte Erstmeldungen (13F-HR bis 47 Tage nach Quartalsende), ohne Optionen und Nennbeträge; je Manager die jüngste. Alle Werte eines Quartals gelten ab der Eröffnung des ersten Handelstags nach Fristablauf. | Dann sind alle gezählten Meldungen öffentlich; ein einheitlicher Stichtag je Quartal ist einfacher zu prüfen als einer je Meldung. Nachträge ändern die Vergangenheit und bleiben außen vor. |
| 76 | 13F: veröffentlicht werden Stückzahl und Portfoliogewicht je Position, nicht der gemeldete Kurswert. Das Vergleichsgewicht im Gesamtbestand nutzt intern den Median des gemeldeten Werts je Stück. | Wert geteilt durch Stück wäre der Schlusskurs (keine Kurse im öffentlichen Repo). Der Median fängt Manager ab, die in Tausend statt in Dollar melden. |
| 77 | `IH5-04` ist die Änderung der Eigentümerbreite nach Chen, Hong & Stein (nur Manager, die in beiden Quartalen melden); die Zahl der Halter steht in `edgar_13f_quartal`. `IH5-03` zählt Manager mit 10–200 Positionen, deren größtes Übergewicht gegenüber dem Gesamtbestand aller Manager die Aktie ist. | Die Änderung ist die Größe der Studie; neue Manager sollen die Breite nicht scheinbar erhöhen. Marktgewichte und Kursschwankung (Anton, Cohen & Polk) brauchen Kurse und entstehen privat. |
| 78 | Die Bestände früherer Quartale werden im Tagesbetrieb nicht heruntergeladen; kommt ein neuer Datensatz, holt das Modul das Vorquartal einmalig aus dem Release. | Rund 1 GB Bestandsdateien täglich zu bewegen wäre unnötig; ein neuer Datensatz erscheint viermal im Jahr. |
| 79 | Sponsoren und Antragsteller (`klinik`): nach dem gewöhnlichen Namensabgleich folgen drei Zusätze – Kurzformen der FDA ausschreiben, feste Töchter (Janssen → Johnson & Johnson, Lilly), eindeutiger Namensanfang unter börsennotierten Firmen der Branche (Konfidenz 0,90, Art `anfang`). Die Trefferquote der Zulassungen zählt ohne Generika (ANDA). | Gemessen am Lauf vom 10.11.2026: Studien 53 → 65 %, neue Wirkstoffe und Biologika 25 → 44 %. Generika stammen überwiegend von Firmen ohne CIK und drückten die Quote auf 10 %, knapp an der Fehlerschwelle. Nicht aufgenommen: Töchter mit wechselnder Mutter (Allergan, Wyeth) und Merck/MSD (die CIK gehörte bis 2009 Schering-Plough). |
| 73 | Neue Release-Gruppe `*-markt` für Marktstrukturdaten der SEC. Der Workflow `einzel` lässt eine einzelne Quelle von Hand laufen, ohne den Workflow `abruf` und seine Fortsetzungskette zu berühren. | Neue Module sollen erprobt werden können, während die Rückwärtsbefüllung läuft. |

## Noch offen

| Baustein | Parameter | Hinderungsgrund |
|---|---|---|
| Öffentliche Aufträge (USAspending) | PR2-01 | Sammeldateien im Gigabyte-Bereich; Abruf und Namensabgleich folgen |
| Wahlkampfspenden, Lobbying | PR3-01, PR3-02 | Schlüssel `DATA_GOV_API_KEY` nötig; Namensabgleich über Ausschuss- und Mandantennamen |
| H-1B-Anträge (DOL) | GA2-02 | Große Excel-Dateien je Quartal mit wechselnden Spalten |
| Patente (USPTO) | GA1-01 | Sammeldateien im Gigabyte-Bereich; Anmelder → CIK |
| Textänderung 10-K/10-Q, Ton der Meldungen | UA5-01, UA5-03, WS2-01, WS2-02 | Abruf aller Berichtstexte (Größenordnung 1 Terabyte); erst nach den ersten echten Läufen |
| Fondsflüsse (N-PORT) | KD3-01 | 13F ist gebaut (Nr. 75–78); N-PORT braucht die Monatsbestände der Fonds und ihre Mittelflüsse |
| 13F des laufenden Quartals | IH5-03, IH5-04 | Der Datensatz der SEC erscheint erst Wochen nach der Frist; für den Tagesbetrieb müssten die Einzelmeldungen (XML) gelesen werden, wie bei den Insidern (Nr. 45) |
| Geldpolitik-Exposition | GW1-03 | Braucht zusätzlich Cashflow-Duration und Volatilität; folgt (Finanzrestriktion GW1-04 ist gebaut) |
| Vergütung, Planadoption (Item 408) | UA6-03, IH1-13 | Im Insider-Monitor bereits vorhanden (`gehalt.py`, `plan_408`) |
| Segment- und Kundenangaben | WS3-03, GA4-01, GA4-05 | Nicht in der Sammeldatei der Abschlüsse; verlangt die Einzelberichte |
