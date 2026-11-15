# Datenblätter

Automatisch aus dem Code erzeugt. Jede Zeile der Parameter-Tabellen trägt eine dieser IDs.

## GA1-01 Erteilte Patente

| Angabe | Inhalt |
|---|---|
| Definition | Zahl der an einem Ausgabetag an die Firma und ihre bekannten Patent-Töchter erteilten Erfindungspatente (utility). Ein Patent mit mehreren Inhabern zählt bei jedem. Wochen ohne Zeile zählen null; das Verhältnis zum F&E-Aufwand (Katalog: Innovationseffizienz) bildet der Nutzer |
| Einheit | Anzahl |
| Frequenz | wöchentlich (Dienstag) |
| Offenlegung | amtlich offen: 35 U.S.C. 153; das Amtsblatt erscheint am Tag der Erteilung (jeder Dienstag) |
| Quelle | https://www.uspto.gov/learning-and-resources/official-gazette/official-gazette-patents; Historie: https://data.uspto.gov/bulkdata/datasets/pvgpatdis |
| Lizenz | gemeinfrei (US-Behörde); Historie aus PatentsView (USPTO), CC BY 4.0 |
| Historie ab | 01/2001 |
| Verzögerung | Eröffnung des ersten Handelstags nach dem Ausgabetag |
| Bekannte Schwächen | Die Historie stammt aus von Hand geladenen Sammeldateien (PatentsView) und reicht bis zu deren Stand, danach das Amtsblatt; rund 0,4 % der Patente einer Ausgabe fehlen in PatentsView. Zuordnung über Firmennamen und eine von Hand geprüfte Liste von Patent-Töchtern mit Zeiträumen (Trefferquote im Prüfbericht), weitere Töchter mit eigenem Namen fehlen; ein Patent zählt bei der Firma, der der Inhaber am Ausgabetag gehörte, spätere Übertragungen bleiben unberücksichtigt; Zitationen stehen in GA1-09 |

## GA1-02 F&E-Aufwand (12 Monate)

| Angabe | Inhalt |
|---|---|
| Definition | Forschungs- und Entwicklungsaufwand der letzten zwölf Monate |
| Einheit | US-Dollar |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Verhältnis zum Marktwert wird im privaten Repo gebildet |

## GA1-03 F&E-Erfolgsbilanz

| Angabe | Inhalt |
|---|---|
| Definition | Mittel der fünf Steigungen aus Regressionen des Umsatzwachstums eines Jahres auf ln(1 + F&E / Umsatz) ein bis fünf Jahre zuvor, je über die letzten acht Jahre (mindestens sechs Jahre, mindestens die Hälfte mit F&E); nach Cohen, Diether & Malloy (2013) |
| Einheit | Steigung |
| Frequenz | je Jahresbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Braucht elf Jahresberichte in Folge, Werte deshalb erst ab etwa 2020; die Studie wertet die Erfolgsbilanz nur unter forschungsstarken Firmen aus (GA1-02 dazunehmen) |

## GA1-04 Studienergebnis im Register veröffentlicht

| Angabe | Inhalt |
|---|---|
| Definition | Ergebnisse einer Phase-2- oder Phase-3-Studie mit Industrie-Sponsor erstmals in ClinicalTrials.gov eingestellt; wert = 3 bei Phase 3, sonst 2 |
| Einheit | Phase (2, 3) |
| Frequenz | je Studie |
| Offenlegung | gesetzlich: FDAAA 801, Ergebnisse spätestens 12 Monate nach primärem Abschluss |
| Quelle | https://clinicaltrials.gov/api/v2/studies |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2008 |
| Verzögerung | nächster Handelstag nach dem Einstelldatum |
| Bekannte Schwächen | Der Registereintrag folgt der Pressemitteilung meist mit Monaten Abstand; Zuordnung über Sponsornamen; Termine und Statuswechsel erst ab dem ersten Lauf über das Änderungsprotokoll |

## GA1-06 Organisationskapital

| Angabe | Inhalt |
|---|---|
| Definition | Fortgeschriebener Vertriebs- und Verwaltungsaufwand (15 % Abschreibung je Jahr, Startwert Aufwand / 0,25) / Bilanzsumme, nach Eisfeldt & Papanikolaou (2013) |
| Einheit | Verhältnis |
| Frequenz | je Jahresbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Ohne Preisbereinigung; Startwert hängt vom ersten verfügbaren Jahr ab |

## GA1-08 Arzneimittelzulassung

| Angabe | Inhalt |
|---|---|
| Definition | Erstzulassung eines Antrags (Einreichung ORIG mit Status AP) laut Drugs@FDA; wert = 2 bei vorrangiger Prüfung, sonst 1 |
| Einheit | Art (1, 2) |
| Frequenz | je Zulassung |
| Offenlegung | amtlich offen: FDA, Drugs@FDA |
| Quelle | https://api.fda.gov/download.json (drug/drugsfda) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 1939 |
| Verzögerung | nächster Handelstag nach dem Zulassungsdatum |
| Bekannte Schwächen | Künftige Zieltermine (PDUFA) stehen nicht in den Daten der FDA; Zuordnung über den Antragsteller, der vom heutigen Rechteinhaber abweichen kann |

## GA1-09 Zitationen der Patente

| Angabe | Inhalt |
|---|---|
| Definition | Zahl der Zitationen, die die an einem Ausgabetag neu erteilten Erfindungspatente auf Erfindungspatente der Firma enthalten, die höchstens fünf Jahre zuvor erteilt wurden (Selbstzitate eingeschlossen). Das zitierte Patent zählt bei der Firma, die es bei der Erteilung erhielt (Zuordnung wie GA1-01). Wochen ohne Zeile zählen null; das Verhältnis zum F&E-Aufwand (Katalog: Innovationseffizienz) bildet der Nutzer |
| Einheit | Anzahl |
| Frequenz | wöchentlich (Dienstag) |
| Offenlegung | amtlich offen: Die Patentschrift nennt die zitierten Schriften und erscheint am Tag der Erteilung |
| Quelle | https://data.uspto.gov/bulkdata/datasets/pvgpatdis |
| Lizenz | PatentsView (USPTO), CC BY 4.0 |
| Historie ab | 01/2001 |
| Verzögerung | Eröffnung des ersten Handelstags nach dem Ausgabetag des zitierenden Patents |
| Bekannte Schwächen | Nur aus von Hand geladenen Sammeldateien: Die Reihe endet mit deren Stand und wächst erst mit einer neu geladenen Datei (das Amtsblatt nennt keine Zitate). Rohe Zahl ohne Bereinigung um Technikfeld und Jahrgang; Zuordnung und ihre Lücken wie GA1-01 |

## GA2-03 Entlassungs- und Restrukturierungsmeldung

| Angabe | Inhalt |
|---|---|
| Definition | 8-K mit Item 2.05 |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | WARN-Meldungen der Bundesstaaten fehlen noch |

## GA3-01 Verbraucherbeschwerden

| Angabe | Inhalt |
|---|---|
| Definition | Zahl der beim CFPB eingegangenen Beschwerden über die Firma je Kalendermonat |
| Einheit | Anzahl |
| Frequenz | monatlich |
| Offenlegung | amtlich offen: CFPB Consumer Complaint Database (Dodd-Frank Act) |
| Quelle | https://www.consumerfinance.gov/data-research/consumer-complaints/ |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 12/2011 |
| Verzögerung | 30 Tage nach Monatsende |
| Bekannte Schwächen | Nur Finanzfirmen; Zuordnung über Firmennamen (Trefferquote im Prüfbericht); Tochterfirmen mit eigenem Namen werden der Mutter nicht zugerechnet; als Signal ungeprüft |

## GA3-02 Rückrufe und Sicherheitsmeldungen

| Angabe | Inhalt |
|---|---|
| Definition | Eine Zeile je Rückruf der Firma oder einer bekannten Tochter; wert = Quelle: 1 = NHTSA (Fahrzeuge, Ausrüstung), 2 = CPSC (Verbraucherprodukte), 3 = FDA Arzneimittel, 4 = FDA Medizinprodukte, 5 = FDA Lebensmittel. Schwere (FDA-Klasse) und betroffene Stückzahl stehen in rueckrufe_ereignisse |
| Einheit | Art (1–5) |
| Frequenz | je Rückruf |
| Offenlegung | gesetzlich: 49 CFR Part 573 (NHTSA), Consumer Product Safety Act § 15 (CPSC), 21 CFR Part 7 (FDA) |
| Quelle | NHTSA Recalls-Sammeldatei (static.nhtsa.gov/odi/ffdd/rcl), CPSC Recalls-Schnittstelle (saferproducts.gov), openFDA Enforcement Reports (api.fda.gov) |
| Lizenz | gemeinfrei (US-Behörden) |
| Historie ab | 1967 (NHTSA), 1973 (CPSC), 2012 (FDA) |
| Verzögerung | Eröffnung des ersten Handelstags nach der Veröffentlichung: Erfassung bei der NHTSA, Mitteilung der CPSC, wöchentlicher Bericht der FDA |
| Bekannte Schwächen | Zuordnung über Firmennamen und eine kurze Liste von Töchtern (Trefferquote im Prüfbericht); viele Hersteller sind ausländisch oder privat. Der FDA-Bericht erscheint im Mittel sieben Wochen nach Beginn des Rückrufs, die Pressemitteilung der Firma ist früher. Beschwerden und Vorkommnisse fehlen |

## GA3-03 Werbeausgaben-Änderung

| Angabe | Inhalt |
|---|---|
| Definition | Werbeaufwand des Jahres / Vorjahr − 1 |
| Einheit | Verhältnis |
| Frequenz | je Jahresbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Viele Firmen weisen Werbeaufwand nicht gesondert aus |

## GW1-01 Zinsüberraschung

| Angabe | Inhalt |
|---|---|
| Definition | Überraschende Änderung des Leitzinsziels zur laufenden Sitzung, abgeleitet aus Fed-Funds-Futures im 30-Minuten-Fenster um die Erklärung des Offenmarktausschusses (MP1 der USMPD) |
| Einheit | Prozentpunkte |
| Frequenz | je Erklärung (rund acht im Jahr) |
| Offenlegung | amtlich: Datei der Federal Reserve Bank of San Francisco, fortgeschrieben nach jeder Sitzung |
| Quelle | https://www.frbsf.org/research-and-insights/data-and-indicators/us-monetary-policy-event-study-database/ (Acosta, Ajello, Bauer, Loria & Miranda-Agrippino 2025) |
| Lizenz | Federal Reserve Bank of San Francisco, frei abrufbar; als Quelle zu nennen |
| Historie ab | 02/1994 |
| Verzögerung | Eröffnung des dritten Handelstags nach der Erklärung (die Datei erscheint rund zwei Tage danach) |
| Bekannte Schwächen | Der Wert ist am Markt sofort ablesbar, in dieser Datei aber erst Tage später; die Wirkung am Tag selbst lässt sich damit nur rückblickend messen. Vor 1994 keine Werte |

## GW1-02 Pfad-Anteil der Zinsreaktion (Forward Guidance)

| Angabe | Inhalt |
|---|---|
| Definition | Änderung des vierten Zinsfutures (Eurodollar, ab 2022 SOFR) im 30-Minuten-Fenster um die Erklärung minus der Teil, den die Zinsüberraschung GW1-01 erklärt (Regression über alle Erklärungen bis dahin, mindestens 20) |
| Einheit | Prozentpunkte |
| Frequenz | je Erklärung |
| Offenlegung | amtlich: Datei der Federal Reserve Bank of San Francisco |
| Quelle | https://www.frbsf.org/research-and-insights/data-and-indicators/us-monetary-policy-event-study-database/ |
| Lizenz | Federal Reserve Bank of San Francisco, frei abrufbar; als Quelle zu nennen |
| Historie ab | 1996 |
| Verzögerung | wie GW1-01 |
| Bekannte Schwächen | Näherung an den zweiten Faktor nach Gürkaynak, Sack & Swanson (2005): ein Future statt der ganzen Zinskurve, laufend neu geschätzt |

## GW1-04 Finanzrestriktion (Whited-Wu-Index)

| Angabe | Inhalt |
|---|---|
| Definition | −0,091·Cashflow/Bilanzsumme − 0,062·Dividendenzahler + 0,021·langfristige Schulden/Bilanzsumme − 0,044·ln(Bilanzsumme in Mio. $) + 0,102·Branchenwachstum − 0,035·Umsatzwachstum, aus dem Jahresabschluss; höher = stärker finanziell beschränkt (Whited & Wu 2006) |
| Einheit | Indexwert |
| Frequenz | je Jahresbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Jahres- statt Quartalswerte; Bilanzsumme nicht preisbereinigt; Branchenwachstum (dreistelliger SIC, mindestens drei Firmen) aus dem Vorjahr, weil das laufende Jahr am Stichtag noch nicht vollständig gemeldet ist |

## GW1-05 Termine von Fed und Statistik

| Angabe | Inhalt |
|---|---|
| Definition | wert 1 = FOMC-Entscheidung, 2 = Arbeitsmarktbericht, 3 = Verbraucherpreise; ereignis_zeit = Termin |
| Einheit | Art (1–3) |
| Frequenz | je Termin |
| Offenlegung | amtlich: Federal Reserve Board, Bureau of Labor Statistics |
| Quelle | FRED/ALFRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org) |
| Lizenz | gemeinfrei (US-Behörde), Quellenangabe erbeten |
| Historie ab | 2000 |
| Verzögerung | gilt als 28 Tage vor dem Termin bekannt |
| Bekannte Schwächen | Der wahre Bekanntgabezeitpunkt des Terminplans liegt meist früher |

## GW1-06 Zinsregime

| Angabe | Inhalt |
|---|---|
| Definition | Änderung des Leitzinsziels der Fed (obere Grenze, vor 2009 Zielsatz); Vorzeichen = Richtung der letzten Änderung |
| Einheit | Prozentpunkte |
| Frequenz | je Änderung |
| Offenlegung | amtlich: Federal Reserve Board |
| Quelle | FRED/ALFRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org) |
| Lizenz | gemeinfrei (US-Behörde), Quellenangabe erbeten |
| Historie ab | 1982 |
| Verzögerung | Tag des Inkrafttretens (Folgetag der Ankündigung) |
| Bekannte Schwächen | – |

## GW2-01 Laufzeitspanne

| Angabe | Inhalt |
|---|---|
| Definition | Rendite 10-jähriger minus 3-monatiger US-Staatspapiere (DGS10 − DGS3MO) |
| Einheit | Prozentpunkte |
| Frequenz | täglich |
| Offenlegung | amtlich: US-Treasury, H.15 der Fed |
| Quelle | FRED/ALFRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org) |
| Lizenz | gemeinfrei (US-Behörde), Quellenangabe erbeten |
| Historie ab | 1982 |
| Verzögerung | nächster Handelstag |
| Bekannte Schwächen | – |

## GW2-03 Kurzer Zins

| Angabe | Inhalt |
|---|---|
| Definition | Rendite 3-monatiger US-Staatspapiere (DGS3MO) |
| Einheit | Prozent |
| Frequenz | täglich |
| Offenlegung | amtlich: US-Treasury, H.15 der Fed |
| Quelle | FRED/ALFRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org) |
| Lizenz | gemeinfrei (US-Behörde), Quellenangabe erbeten |
| Historie ab | 1982 |
| Verzögerung | nächster Handelstag |
| Bekannte Schwächen | – |

## GW2-04 Produktionslücke

| Angabe | Inhalt |
|---|---|
| Definition | Abweichung der Industrieproduktion (log) vom quadratischen Trend seit 1960, gerechnet mit dem Datenstand des Veröffentlichungstags (nach Cooper & Priestley 2009) |
| Einheit | Log-Punkte |
| Frequenz | je Veröffentlichung oder Revision |
| Offenlegung | amtlich: Federal Reserve Board, G.17 |
| Quelle | FRED/ALFRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org) |
| Lizenz | gemeinfrei (US-Behörde), Quellenangabe erbeten |
| Historie ab | 2000 |
| Verzögerung | Veröffentlichungstag 09:15 ET |
| Bekannte Schwächen | Echtzeit-Trend statt Trend über die ganze Stichprobe wie in der Studie |

## GW2-06 Änderung der Jahresinflation

| Angabe | Inhalt |
|---|---|
| Definition | Jahresrate der Verbraucherpreise des jüngsten Monats minus Jahresrate des Vormonats, mit dem Datenstand des Veröffentlichungstags (CPIAUCSL) |
| Einheit | Prozentpunkte (als Anteil) |
| Frequenz | je Veröffentlichung oder Revision |
| Offenlegung | amtlich: Bureau of Labor Statistics |
| Quelle | FRED/ALFRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org) |
| Lizenz | gemeinfrei (US-Behörde), Quellenangabe erbeten |
| Historie ab | 2000 |
| Verzögerung | Veröffentlichungstag 08:30 ET |
| Bekannte Schwächen | Ersatz für die unerwartete Inflation; Markterwartungen sind nicht offen verfügbar |

## GW3-01 Ölpreisänderung (Vormonat)

| Angabe | Inhalt |
|---|---|
| Definition | Logarithmische Änderung des WTI-Spotpreises zum Monatsende (DCOILWTICO) |
| Einheit | Log-Änderung |
| Frequenz | monatlich |
| Offenlegung | amtlich: Energy Information Administration |
| Quelle | FRED/ALFRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org) |
| Lizenz | gemeinfrei (US-Behörde), Quellenangabe erbeten |
| Historie ab | 1986 |
| Verzögerung | erster Handelstag nach Monatsende |
| Bekannte Schwächen | – |

## IH1-01 Clusterkauf (30 Tage)

| Angabe | Inhalt |
|---|---|
| Definition | Zahl verschiedener firmeneigener Insider (ohne 10-%-Eigner ohne Amt) mit Käufen am offenen Markt (Code P) bei derselben Firma in den 30 Tagen bis zum Kauf, einschließlich des Käufers; nur zum Meldezeitpunkt bereits bekannte Käufe (entspricht n_cluster_1m im Insider-Monitor) |
| Einheit | Anzahl Personen |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | – |

## IH1-02 Rang des Käufers

| Angabe | Inhalt |
|---|---|
| Definition | 4 = CEO/CFO/Chair, 3 = sonstiger Officer, 2 = nur Direktor (externer Direktor), 1 = 10-%-Eigner ohne Amt, 0 = Sonstige |
| Einheit | Stufe 0–4 |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | Titel sind Freitext; bei mehreren Meldenden zählt die erstgenannte Person |

## IH1-03 Kaufsumme

| Angabe | Inhalt |
|---|---|
| Definition | Summe Stück × Preis der Käufe einer Meldung |
| Einheit | US-Dollar |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | Verhältnis zu Marktkapitalisierung und Gehalt wird im privaten Repo gebildet |

## IH1-04 Routine- oder opportunistischer Kauf

| Angabe | Inhalt |
|---|---|
| Definition | 1 = Routine (Kauf derselben Aktie im selben Kalendermonat in mindestens zwei Vorjahren), 0 = opportunistisch (Käufe in mindestens zwei Vorjahren, nie im selben Monat); externe Käufer und Käufer mit weniger Historie ohne Wert. Definition des Insider-Monitors (f_routine, f_opportun) |
| Einheit | Kennzeichen 0/1 |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2008 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | – |

## IH1-05 Tage seit letzter Zahlenmeldung

| Angabe | Inhalt |
|---|---|
| Definition | Kalendertage zwischen der letzten 8-K mit Item 2.02 der Firma und dem Kauftag |
| Einheit | Tage |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | Meldungen am Kauftag selbst zählen nicht; Abstand zum nächsten Termin fehlt (Terminschätzung im privaten Repo) |

## IH1-06 Netto-Kaufquote der Firma (6 Monate)

| Angabe | Inhalt |
|---|---|
| Definition | (Käufe − Verkäufe) / (Käufe + Verkäufe) in US-Dollar, Codes P und S aller Insider der Firma in den 182 Tagen bis zum Kauf; Verkäufe aus Meldungen mit Optionsausübung (Code M) zählen zu 25 % (wie sale_oe_weight im Insider-Monitor); nur zum Meldezeitpunkt bekannte Geschäfte |
| Einheit | Quote −1 bis +1 |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | Kurzfrist-Händler werden anders als im Insider-Monitor nicht abgewertet |

## IH1-07 10b5-1-Kennzeichen

| Angabe | Inhalt |
|---|---|
| Definition | 1 = Meldung als Geschäft unter einem 10b5-1-Plan gekennzeichnet, 0 = nicht |
| Einheit | Kennzeichen 0/1 |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 04/2023 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | vor 04/2023 nicht vorhanden |

## IH1-09 Vorlauf bis Meldung

| Angabe | Inhalt |
|---|---|
| Definition | Kalendertage zwischen letztem Kauftag und Einreichungsdatum |
| Einheit | Tage |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | – |

## IH1-10 Bestandsaufstockung

| Angabe | Inhalt |
|---|---|
| Definition | gekaufte Stück / Bestand vor dem Kauf |
| Einheit | Verhältnis |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | nur wenn der Bestand nach dem Kauf gemeldet ist und über der Kaufmenge liegt |

## IH1-14 Verkaufsabsicht Form 144

| Angabe | Inhalt |
|---|---|
| Definition | Form 144 oder 144/A zur betroffenen Firma |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Rule 144, elektronische Einreichung Pflicht seit 13.04.2023 |
| Quelle | SEC EDGAR, Kopf der Einreichungsdatei je Meldung |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Stückzahl und Wert fehlen (Datei der Meldung); vor 04/2023 kaum elektronische Meldungen |

## IH1-16 Insider-Kaufanteil des Marktes

| Angabe | Inhalt |
|---|---|
| Definition | Anteil der Kaufmeldungen an allen Kauf- und Verkaufsmeldungen ab 25.000 US-Dollar, je Monat der Verfügbarkeit |
| Einheit | Anteil 0–1 |
| Frequenz | monatlich |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Eröffnung des ersten Handelstags nach Monatsende |
| Bekannte Schwächen | Marktweite Größe (cik = 0) |

## IH1-17 Käufer verkauft binnen 30 Tagen

| Angabe | Inhalt |
|---|---|
| Definition | Verkauf (Code S) derselben Person höchstens 30 Tage nach einem eigenen Kauf; Zeile am Verkaufstag |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Verkaufsmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | – |

## IH1-18 Tagescluster

| Angabe | Inhalt |
|---|---|
| Definition | Zahl anderer firmeneigener Insider mit Käufen bei derselben Firma am Kauftag oder in den zwei Tagen davor; nur zum Meldezeitpunkt bekannte Käufe (Alldredge & Blank 2019). Neu vergebene ID, im Katalog nachzutragen |
| Einheit | Anzahl Personen |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | – |

## IH3-06 Lieferausfälle (Reg SHO)

| Angabe | Inhalt |
|---|---|
| Definition | Bestand nicht gelieferter Stücke der Firma am Abwicklungstag (Fails-to-Deliver im Clearing der NSCC). summiert über ihre Stammaktiengattungen mit jeweils mindestens 10.000 Stück |
| Einheit | Stück |
| Frequenz | je Abwicklungstag mit Bestand ab Schwelle; Veröffentlichung je Monatshälfte |
| Offenlegung | amtlich offen: SEC Fails-to-Deliver Data (Regulation SHO) |
| Quelle | https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 03/2004 |
| Verzögerung | Veröffentlichungstag der Datei, üblich 14–19 Tage nach Ende der Monatshälfte; ist er unbekannt, 30 Tage (Quartalsdateien bis 2009: 60 Tage) nach Periodenende |
| Bekannte Schwächen | Die Threshold-Liste verlangt zusätzlich 0,5 % der ausstehenden Aktien an fünf Abwicklungstagen in Folge; das Verhältnis (mit UA3-01) und die Dauer entstehen privat. Zuordnung über Kürzel, CUSIP und Bezeichnung (Trefferquote im Prüfbericht); die heutige Zuordnung gilt rückwirkend. Der Bestand ist kumuliert, kein Tageszugang. Als Signal ungeprüft |

## IH5-01 13D-Einstieg

| Angabe | Inhalt |
|---|---|
| Definition | Erstmeldung Schedule 13D zur betroffenen Firma |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Section 13(d) Exchange Act, seit 02/2024 Frist 5 Geschäftstage |
| Quelle | SEC EDGAR, Kopf der Einreichungsdatei je Meldung |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Beteiligungshöhe und erklärtes Ziel fehlen (Text der Meldung) |

## IH5-02 13D-Nachtrag

| Angabe | Inhalt |
|---|---|
| Definition | Nachtrag Schedule 13D/A zur betroffenen Firma |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Section 13(d), seit 02/2024 Frist 2 Geschäftstage |
| Quelle | SEC EDGAR, Kopf der Einreichungsdatei je Meldung |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Richtung (Aufstockung oder Abbau) fehlt (Text der Meldung) |

## IH5-03 Beste Ideen der Manager

| Angabe | Inhalt |
|---|---|
| Definition | Zahl der Manager mit 10 bis 200 zugeordneten Aktien, deren größtes Übergewicht (Gewicht im Aktienportfolio des Managers minus Gewicht im Aktienbestand aller Manager) diese Firma ist; nur Werte ab 1 |
| Einheit | Anzahl |
| Frequenz | je Berichtsquartal |
| Offenlegung | amtlich offen: Form 13F (§ 13(f) Exchange Act), Frist 45 Tage nach Quartalsende |
| Quelle | https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2013 |
| Verzögerung | Eröffnung des ersten Handelstags nach Ablauf der Meldefrist |
| Bekannte Schwächen | Vereinfachung von Anton, Cohen & Polk: Vergleich mit dem Gesamtbestand der 13F-Manager statt mit dem Marktgewicht, ohne Gewichtung mit der Kursschwankung. Nur Manager über 100 Mio. $ und nur gemeldete Long-Bestände; Nachträge und verspätete Meldungen bleiben außen vor; Zuordnung über die CUSIP-Tabelle der Lieferausfälle zum Zeitpunkt der Berechnung (Trefferquote im Prüfbericht); bis der Datensatz der SEC erscheint (Wochen nach der Frist), stammt das jüngste Quartal aus den Einzelmeldungen (Stand „… Einzelmeldungen“) und kann sich mit dem Datensatz geringfügig ändern |

## IH5-04 Eigentümerbreite (Änderung)

| Angabe | Inhalt |
|---|---|
| Definition | Halter der Firma im Quartal minus Halter im Vorquartal, geteilt durch die Zahl der Manager; gezählt werden nur Manager, die in beiden Quartalen gemeldet haben (Chen, Hong & Stein 2002). Die Zahl der Halter selbst steht in der bereinigten Tabelle edgar_13f_firmen |
| Einheit | Anteil der Manager |
| Frequenz | je Berichtsquartal |
| Offenlegung | amtlich offen: Form 13F (§ 13(f) Exchange Act), Frist 45 Tage nach Quartalsende |
| Quelle | https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2013 |
| Verzögerung | Eröffnung des ersten Handelstags nach Ablauf der Meldefrist |
| Bekannte Schwächen | Nur Manager über 100 Mio. $ und nur gemeldete Long-Bestände; Nachträge und verspätete Meldungen bleiben außen vor; Zuordnung über die CUSIP-Tabelle der Lieferausfälle zum Zeitpunkt der Berechnung (Trefferquote im Prüfbericht); bis der Datensatz der SEC erscheint (Wochen nach der Frist), stammt das jüngste Quartal aus den Einzelmeldungen (Stand „… Einzelmeldungen“) und kann sich mit dem Datensatz geringfügig ändern |

## IH6-04 Neue Schulden

| Angabe | Inhalt |
|---|---|
| Definition | 8-K mit Item 2.03 |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | – |

## KD1-11 Delisting, Abmeldung, Insolvenz, Übernahme

| Angabe | Inhalt |
|---|---|
| Definition | wert 1 = Form 25 / 25-NSE (Börsenabmeldung), 2 = Form 15 (Abmeldung bei der SEC), 3 = 8-K Item 1.03 (Insolvenz), 4 = Übernahmeunterlage der Zielfirma (PREM14A/C, DEFM14A/C, SC 14D9), 5 = 8-K Item 3.01 (Hinweis der Börse auf Delisting); Einstufung wie classify_filings im Insider-Monitor |
| Einheit | Art (1–5) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Rule 12d2-2 (Form 25), Rule 12g-4 / 15d-6 (Form 15), Form 8-K, Schedule 14A/14C, Rule 14d-9 |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Form 25 betrifft teils einzelne Wertpapierklassen; SC TO-T und SC 13E3 fehlen, weil sie unter Bieter und Zielfirma stehen und die Rollen noch nicht gelesen werden |

## PR2-01 Vergabevolumen je Firma

| Angabe | Inhalt |
|---|---|
| Definition | Summe der im Monat bekannt gewordenen Verpflichtungen des Bundes aus Verträgen mit der Firma und ihren Töchtern (federal_action_obligation aller Vertragstransaktionen, Rücknahmen negativ). Monate ohne Zeile zählen null; das Verhältnis zum Umsatz (Katalog: 12 Monate / Umsatz) bildet der Nutzer |
| Einheit | US-Dollar |
| Frequenz | monatlich |
| Offenlegung | gesetzlich: FFATA 2006 und DATA Act 2014; Vertragsmeldung an FPDS binnen 3 Werktagen (FAR 4.604) |
| Quelle | https://www.usaspending.gov/download_center/award_data_archive |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 10/2007 |
| Verzögerung | 15 Tage nach Monatsende; Verteidigungsaufträge zählen erst 90 Tage nach dem Auftragsdatum |
| Bekannte Schwächen | Zuordnung über Firmennamen und die gemeldete Konzernfamilie (Trefferquote im Prüfbericht); Töchter mit eigenem Namen außerhalb der gemeldeten Familie fehlen; die Quelle zeigt den heutigen Stand jeder Transaktion (spätere Korrekturen fließen in alte Monate ein); nur Hauptauftragnehmer, keine Unteraufträge; Rahmenverträge zählen erst mit den Abrufen; als Signal ungeprüft |

## PR2-03 Effektiver Steuersatz

| Angabe | Inhalt |
|---|---|
| Definition | Ertragsteueraufwand / Ergebnis vor Steuern des Jahres, nur bei Gewinn vor Steuern |
| Einheit | Verhältnis |
| Frequenz | je Jahresbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Latente Steuerpositionen fehlen noch |

## UA1-01 Gewinnüberraschung (SUE)

| Angabe | Inhalt |
|---|---|
| Definition | Quartalsgewinn minus Gewinn des Vorjahresquartals, geteilt durch die Streuung dieser Differenz über die acht Vorquartale (mindestens vier); saisonaler Random Walk ohne Analystendaten |
| Einheit | Standardabweichungen |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Nettogewinn statt Gewinn je Aktie; Sondereffekte nicht bereinigt |

## UA1-02 Zahlenlage

| Angabe | Inhalt |
|---|---|
| Definition | +1 positiv (Umsatz über 2 % über Vorjahr, Gewinn, operativer Cashflow nicht negativ), −1 negativ (Umsatz über 2 % unter Vorjahr, kein Gewinn), 0 gemischt; Definition fin_lage_roh des Insider-Monitors |
| Einheit | Stufe −1/0/+1 |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Die Sperren des Insider-Monitors (junger Börsengang, durch 8-K überholt) werden dort angewandt |

## UA1-03 Accruals

| Angabe | Inhalt |
|---|---|
| Definition | (Gewinn − operativer Cashflow) der letzten zwölf Monate / Bilanzsumme |
| Einheit | Verhältnis |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | – |

## UA1-04 Cash-Profitabilität

| Angabe | Inhalt |
|---|---|
| Definition | operativer Cashflow der letzten zwölf Monate / Bilanzsumme |
| Einheit | Verhältnis |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Näherung an Ball u. a. (2016): Cashflow statt operativem Gewinn ohne Accruals |

## UA1-05 Bilanzwachstum

| Angabe | Inhalt |
|---|---|
| Definition | Bilanzsumme / Bilanzsumme ein Jahr zuvor − 1 |
| Einheit | Verhältnis |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | – |

## UA1-06 F-Score

| Angabe | Inhalt |
|---|---|
| Definition | Summe von neun Ja/Nein-Signalen nach Piotroski (2000) aus zwei Jahresabschlüssen |
| Einheit | Punkte 0–9 |
| Frequenz | je Jahresbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Nur wenn alle neun Signale berechenbar sind; Renditen auf die Bilanzsumme zum Jahresende |

## UA1-07 Cash-Reichweite

| Angabe | Inhalt |
|---|---|
| Definition | (Zahlungsmittel + kurzfristige Anlagen) / Mittelabfluss je Quartal; nur bei Mittelabfluss, höchstens 40 (wie fin_runway_q im Insider-Monitor) |
| Einheit | Quartale |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Die Plausibilitätsschwelle gegen den Börsenwert wendet der Insider-Monitor an |

## UA1-08 Umsatzwachstum

| Angabe | Inhalt |
|---|---|
| Definition | Umsatz des Berichtszeitraums / Umsatz des Vorjahreszeitraums − 1 (Vergleichszahl aus demselben Bericht) |
| Einheit | Verhältnis |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Die beiden anderen Bausteine des Katalogs stehen in WR2-02 (Verschuldung) und UA1-02 (Gewinn); bei Banken Zinsüberschuss plus zinsunabhängige Erträge |

## UA1-10 Veröffentlichungszeitpunkt der Zahlen

| Angabe | Inhalt |
|---|---|
| Definition | 8-K mit Item 2.02; wert = Wochentag (0 = Montag) + Stunde/24 der Annahmezeit in Ostküstenzeit |
| Einheit | Wochentag + Tagesbruchteil |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | – |

## UA2-01 M-Score

| Angabe | Inhalt |
|---|---|
| Definition | Beneish (1999): −4,84 + 0,920·DSRI + 0,528·GMI + 0,404·AQI + 0,892·SGI + 0,115·DEPI − 0,172·SGAI + 4,679·TATA − 0,327·LVGI aus zwei Jahresabschlüssen |
| Einheit | Punktwert (über −1,78 auffällig) |
| Frequenz | je Jahresbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Nur wenn alle acht Bausteine berechenbar sind; nicht für Finanzfirmen |

## UA2-03 Restatement / Non-Reliance

| Angabe | Inhalt |
|---|---|
| Definition | 8-K mit Item 4.02 |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | – |

## UA2-04 Prüferwechsel

| Angabe | Inhalt |
|---|---|
| Definition | 8-K mit Item 4.01 |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | – |

## UA3-01 Netto-Aktienemission (12 Monate)

| Angabe | Inhalt |
|---|---|
| Definition | Aktienzahl / Aktienzahl ein Jahr zuvor − 1 |
| Einheit | Verhältnis |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Nicht splitbereinigt: Sprünge über Faktor 3 werden verworfen; kleinere Splits bleiben als Fehler |

## UA3-02 Aktienrückkäufe (12 Monate)

| Angabe | Inhalt |
|---|---|
| Definition | Auszahlungen für den Rückkauf eigener Aktien in den letzten zwölf Monaten laut Kapitalflussrechnung; nur über null |
| Einheit | US-Dollar |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Betrag aus der Kapitalflussrechnung statt Stückzahl und Preis je Monat (Item 703 steht nur im Text); enthält Rücknahmen zur Steuerabführung bei Mitarbeiteraktien |

## UA3-03 Kapitalerhöhung / Privatplatzierung

| Angabe | Inhalt |
|---|---|
| Definition | wert 1 = 8-K Item 3.02, 2 = Prospekt 424B1–424B8, 3 = Form D |
| Einheit | Art (1, 2, 3) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: 8-K 3.02, Rule 424(b), Regulation D |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Volumen und Abschlag fehlen (Text) |

## UA3-04 Shelf-Registrierung

| Angabe | Inhalt |
|---|---|
| Definition | Einreichung S-3 oder S-3ASR (ohne Nachträge) |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form S-3 |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Restvolumen fehlt (Text) |

## UA3-05 Potenzielle Verwässerung

| Angabe | Inhalt |
|---|---|
| Definition | (vom Ergebnis je Aktie ausgeschlossene Wandel- und Optionsrechte + verwässernde Aktien) / gewichtete Aktienzahl des Berichtszeitraums; höchstens 5 |
| Einheit | Verhältnis |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Nur Rechte, die die Firma in der Ergebnisrechnung nennt; Bedingungen und Ausübungspreise fehlen |

## UA4-01 Übernahme oder Veräußerung abgeschlossen

| Angabe | Inhalt |
|---|---|
| Definition | 8-K mit Item 2.01 |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Zahlungsart und Käuferbewertung fehlen (Text der Meldung) |

## UA4-02 Abspaltung (Spin-off)

| Angabe | Inhalt |
|---|---|
| Definition | wert 1 = erste Anmeldung Form 10-12B der abgespaltenen Firma, 2 = erste Wirksamkeitsmitteilung (EFFECT) danach binnen eines Jahres |
| Einheit | Art (1, 2) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 10 (Exchange Act § 12(b)) |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Zeile steht bei der abgespaltenen Firma, die Mutter nennt nur der Text; Form 10-12B dient vereinzelt anderen Zwecken (Neustart nach Insolvenz); der Tag der Zuteilung fehlt |

## UA4-03 Dividendenaufnahme oder -streichung

| Angabe | Inhalt |
|---|---|
| Definition | +1 = Dividende im Quartal nach mindestens sechs Quartalen ohne; −1 = keine Dividende im Quartal nach vier Quartalen mit; aus gezahlter Dividende (Kapitalflussrechnung) und erklärter Dividende je Aktie |
| Einheit | Kennzeichen (+1, −1) |
| Frequenz | je Ereignis |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Datiert auf den Quartalsbericht, die Ankündigung per 8-K liegt Wochen früher; Sonderdividenden zählen als Aufnahme; wechselt die Firma den Berichtsposten, kann eine Streichung vorgetäuscht sein |

## UA4-04 Lockup-Ablauf

| Angabe | Inhalt |
|---|---|
| Definition | Erwarteter Ablauf der Haltefrist nach einem Börsengang: 180 Tage nach dem Emissionsprospekt (erster 424B4 oder 424B1 einer Firma ohne früheren 10-K oder 10-Q); ereignis_zeit = Ablauftag, wert = angenommene Frist in Tagen |
| Einheit | Tage |
| Frequenz | je Börsengang |
| Offenlegung | gesetzlich: Rule 424(b) |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2008 |
| Verzögerung | Annahmezeit des Prospekts; der Ablauftag liegt in der Zukunft |
| Bekannte Schwächen | Frist als übliche 180 Tage angenommen, nicht aus dem Prospekt gelesen (abweichende und gestaffelte Fristen fehlen); enthält auch Börsengänge von Mantelgesellschaften (SPAC) |

## UA4-05 Führungswechsel

| Angabe | Inhalt |
|---|---|
| Definition | 8-K mit Item 5.02 |
| Einheit | Kennzeichen (1 = Ereignis) |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | Item 5.02 umfasst auch Vergütungsänderungen und Direktorenwechsel |

## WR2-02 Nettoverschuldung zur Bilanzsumme

| Angabe | Inhalt |
|---|---|
| Definition | (langfristige Schulden − Zahlungsmittel − kurzfristige Anlagen) / Bilanzsumme; negativ = mehr Kasse als Schulden |
| Einheit | Verhältnis |
| Frequenz | je Quartalsbericht |
| Offenlegung | gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht |
| Quelle | SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2009 (große Firmen), 2011 (alle) |
| Verzögerung | Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher |
| Bekannte Schwächen | Kurzfristige Schulden fehlen; ohne ausgewiesene Schulden zählt null |

## WS2-04 8-K-Meldungen nach Item

| Angabe | Inhalt |
|---|---|
| Definition | Eine Zeile je Item einer 8-K; wert = Item-Nummer (z. B. 2.02) |
| Einheit | Item-Nummer |
| Frequenz | je Meldung |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung |
| Bekannte Schwächen | 8-K/A (Nachträge) sind nicht enthalten |

## WS2-05 Nachrichtenstimmung des Marktes

| Angabe | Inhalt |
|---|---|
| Definition | Daily News Sentiment Index: Stimmung in Wirtschaftsartikeln von 24 US-Zeitungen, Tageswert |
| Einheit | Indexwert |
| Frequenz | täglich |
| Offenlegung | amtlich: Datei der Federal Reserve Bank of San Francisco, wöchentlich fortgeschrieben |
| Quelle | https://www.frbsf.org/research-and-insights/data-and-indicators/daily-news-sentiment-index/ (Shapiro, Sudhof & Wilson 2020) |
| Lizenz | Federal Reserve Bank of San Francisco, frei abrufbar; als Quelle zu nennen |
| Historie ab | 1980 |
| Verzögerung | Eröffnung des ersten Handelstags ab dem zwölften Tag nach dem Berichtstag |
| Bekannte Schwächen | Frühere Tageswerte können sich bei einer Neuschätzung ändern; gespeichert ist der jeweils jüngste Stand, nicht der Stand am Tag selbst |

## WS3-01 Wochentag und Tageszeit der Meldung

| Angabe | Inhalt |
|---|---|
| Definition | Für Kaufmeldungen: Wochentag (0 = Montag) + Stunde/24 der Annahmezeit in Ostküstenzeit |
| Einheit | Wochentag + Tagesbruchteil |
| Frequenz | je Kaufmeldung |
| Offenlegung | gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage |
| Quelle | SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | Annahmezeit der Meldung (aus edgar_index) |
| Bekannte Schwächen | nur bei bekannter Annahmezeit |

## WS3-02 Zahl gleichzeitiger Zahlenmeldungen

| Angabe | Inhalt |
|---|---|
| Definition | Anzahl der 8-K mit Item 2.02 aller Firmen je Annahmetag (Ostküstenzeit) |
| Einheit | Anzahl |
| Frequenz | täglich |
| Offenlegung | gesetzlich: Form 8-K, Frist 4 Geschäftstage |
| Quelle | SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| Lizenz | gemeinfrei (US-Behörde) |
| Historie ab | 2006 |
| Verzögerung | bekannt zur Eröffnung des nächsten Handelstags |
| Bekannte Schwächen | Marktweite Größe (cik = 0); zählt Meldungen, nicht Firmen |

## WS3-05 Wikipedia-Seitenaufrufe (abnormal)

| Angabe | Inhalt |
|---|---|
| Definition | ln(Aufrufe der Woche) − ln(Median der Aufrufe der acht Vorwochen) für den englischen Artikel der Firma; Woche Montag bis Sonntag, nur menschliche Zugriffe |
| Einheit | Log-Abweichung |
| Frequenz | wöchentlich |
| Offenlegung | frei im Web: Wikimedia Pageviews (CC0), Zuordnung über Wikidata (CC0) |
| Quelle | https://wikimedia.org/api/rest_v1/ und https://query.wikidata.org |
| Lizenz | CC0 |
| Historie ab | 09/2015 |
| Verzögerung | Dienstag der Folgewoche, Eröffnung |
| Bekannte Schwächen | Nur Firmen mit Wikidata-Eintrag samt CIK; die heutige Zuordnung gilt rückwirkend; Artikelumbenennungen können Reihen unterbrechen |

