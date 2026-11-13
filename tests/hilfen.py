"""Erzeugt kleine Beispieldateien im Format der Quellen (für Offline-Tests)."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path


def _block(zeilen: list[dict]) -> dict:
    felder = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "items",
              "primaryDocument", "isXBRL"]
    return {f: [z.get(f, "") for z in zeilen] for f in felder}


def m(acc, form, datum, annahme, items="", doc="d.htm", report=""):
    return {"accessionNumber": acc, "form": form, "filingDate": datum, "acceptanceDateTime": annahme,
            "items": items, "primaryDocument": doc, "reportDate": report, "isXBRL": 0}


ALPHA = [
    m("0001000-24-000001", "8-K", "2024-03-28", "2024-03-28T16:05:10.000Z", "2.02,9.01"),
    m("0001000-24-000002", "8-K", "2024-05-06", "2024-05-03T17:45:00.000Z", "4.01"),
    m("0001000-24-000003", "10-Q", "2024-05-08", "2024-05-08T07:01:00.000Z"),
    m("0001999-24-000010", "4", "2024-05-15", "2024-05-15T19:30:00.000Z", doc="xslF345X05/f4.xml"),
    m("0001000-24-000004", "8-K", "2024-06-03", "2024-06-03T08:00:00.000Z", "2.03,3.02,5.02"),
    m("0001000-24-000005", "D", "2024-06-10", "2024-06-10T10:00:00.000Z"),
    m("0001000-24-000006", "S-3", "2024-06-11", "2024-06-11T16:30:00.000Z"),
    m("0001000-24-000007", "424B5", "2024-06-12", "2024-06-12T17:00:00.000Z"),
    m("0005000-24-000900", "25-NSE", "2024-07-01", "2024-07-01T09:00:00.000Z"),
    m("0001000-24-000008", "8-K/A", "2024-07-02", "2024-07-02T09:00:00.000Z", "2.02"),
    m("0001000-24-000009", "8-K", "2024-07-05", "", "2.05"),
    # 2023: Prüfjahr für die Zeitzonen-Erkennung
    m("0001000-23-000001", "8-K", "2023-08-01", "2023-08-01T08:30:00.000Z", "2.02"),
    m("0001000-23-000002", "8-K", "2023-08-02", "2023-08-01T18:00:00.000Z", "8.01"),
    m("0001000-23-000003", "10-Q", "2023-08-04", "2023-08-03T19:15:00.000Z"),
    m("0001000-23-000004", "8-K", "2023-11-06", "2023-11-03T17:31:00.000Z", "2.02,4.02"),
    m("0001000-23-000005", "10-K", "2023-03-01", "2023-03-01T16:59:00.000Z"),
    m("0001000-23-000006", "8-K", "2023-03-10", "2023-03-10T17:29:00.000Z", "5.02"),
]
ALPHA_ALT = [
    m("0001000-07-000001", "10-K", "2007-03-01", "2007-03-01T12:00:00.000Z"),
    m("0001000-05-000001", "10-K", "2005-03-01", "2005-03-01T12:00:00.000Z"),
]


def baue_submissions_zip(pfad: Path) -> Path:
    alpha = {"cik": "1000", "entityType": "operating", "sic": "2834", "sicDescription": "Pharma",
             "name": "ALPHA CORP", "tickers": ["ALPH"], "exchanges": ["Nasdaq"], "category": "Accelerated filer",
             "fiscalYearEnd": "1231", "stateOfIncorporation": "DE",
             "addresses": {"business": {"stateOrCountry": "CA", "zipCode": "94000"}},
             "formerNames": [{"name": "ALPHA OLD", "from": "2001-01-01", "to": "2010-01-01"}],
             "filings": {"recent": _block(ALPHA), "files": [{"name": "CIK0000001000-submissions-001.json"}]}}
    person = {"cik": "1999", "entityType": "other", "sic": "", "name": "DOE JANE", "tickers": [], "exchanges": [],
              "addresses": {}, "formerNames": [],
              "filings": {"recent": _block([ALPHA[3]]), "files": []}}
    boerse = {"cik": "5000", "entityType": "other", "sic": "", "name": "BOERSE LLC", "tickers": [], "exchanges": [],
              "addresses": {}, "formerNames": [],
              "filings": {"recent": _block(
                  [m(f"0005000-24-{i:06d}", "25-NSE", "2024-07-01", "2024-07-01T09:00:00.000Z") for i in range(900, 905)]),
                  "files": []}}
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("CIK0000001000.json", json.dumps(alpha))
        z.writestr("CIK0000001000-submissions-001.json", json.dumps(_block(ALPHA_ALT)))
        z.writestr("CIK0000001999.json", json.dumps(person))
        z.writestr("CIK0000005000.json", json.dumps(boerse))
        z.writestr("placeholder.txt", "x")
    return pfad


def tsv(kopf: list[str], zeilen: list[list]) -> str:
    aus = io.StringIO()
    aus.write("\t".join(kopf) + "\n")
    for z in zeilen:
        aus.write("\t".join("" if v is None else str(v) for v in z) + "\n")
    return aus.getvalue()


SUB_KOPF = ["ACCESSION_NUMBER", "FILING_DATE", "PERIOD_OF_REPORT", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME",
            "ISSUERTRADINGSYMBOL", "AFF10B5ONE"]
OWN_KOPF = ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"]
TR_KOPF = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "SECURITY_TITLE", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
           "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS", "DIRECT_INDIRECT_OWNERSHIP"]


def baue_form345_zip(pfad: Path, sub: list[list], own: list[list], tr: list[list]) -> Path:
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SUBMISSION.tsv", tsv(SUB_KOPF, sub))
        z.writestr("REPORTINGOWNER.tsv", tsv(OWN_KOPF, own))
        z.writestr("NONDERIV_TRANS.tsv", tsv(TR_KOPF, tr))
        z.writestr("FORM_345_readme.htm", "x")
    return pfad


# --------------------------------------------------------------------------- Abschlüsse (companyfacts)
QE = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
QS = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}


class Fakten:
    """Sammelt Fakten im Aufbau der SEC-Datei companyfacts (facts -> Gruppe -> Posten -> units -> Einträge)."""

    def __init__(self):
        self.gruppen: dict = {"us-gaap": {}, "dei": {}}

    def plus(self, posten, wert, accn, form, filed, ende, start=None, einheit="USD", gruppe="us-gaap"):
        e = {"end": ende, "val": wert, "accn": accn, "form": form, "filed": filed}
        if start:
            e["start"] = start
        self.gruppen[gruppe].setdefault(posten, {"units": {}})["units"].setdefault(einheit, []).append(e)

    def json(self, cik, name="TESTFIRMA"):
        return {"cik": cik, "entityName": name, "facts": self.gruppen}


def musterfirma() -> Fakten:
    """Drei Geschäftsjahre (2021–2023) mit bekannten Quartalswerten; Kapitalfluss nur aufgelaufen."""
    import datetime as dt
    ni = {2021: [10, 12, 14, 16], 2022: [11, 15, 13, 21], 2023: [14, 16, 18, 20]}
    um = {2021: [100, 100, 100, 100], 2022: [110, 120, 90, 130], 2023: [120, 125, 95, 140]}
    cf = {2021: [4, 6, 8, 10], 2022: [5, 7, 9, 11], 2023: [6, 8, 10, 12]}
    aktiva = {2021: [800, 820, 840, 860], 2022: [880, 900, 920, 940], 2023: [960, 1000, 1020, 1040]}
    aktien = {2021: [1000] * 4, 2022: [1000] * 4, 2023: [1050, 1100, 3500, 3500]}
    jahr = {2022: dict(GrossProfit=180, SellingGeneralAndAdministrativeExpense=90, DepreciationDepletionAndAmortization=20,
                       AdvertisingExpense=10, IncomeTaxExpenseBenefit=15, pretax=75,
                       AssetsCurrent=400, LiabilitiesCurrent=200, AccountsReceivableNetCurrent=90,
                       PropertyPlantAndEquipmentNet=300, LongTermDebtNoncurrent=150),
            2023: dict(GrossProfit=200, SellingGeneralAndAdministrativeExpense=92, DepreciationDepletionAndAmortization=22,
                       AdvertisingExpense=12, IncomeTaxExpenseBenefit=17, pretax=85,
                       AssetsCurrent=450, LiabilitiesCurrent=210, AccountsReceivableNetCurrent=100,
                       PropertyPlantAndEquipmentNet=320, LongTermDebtNoncurrent=140)}
    PRETAX = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
    f = Fakten()
    for y in (2021, 2022, 2023):
        for k in (1, 2, 3, 4):
            ende = f"{y}-{QE[k]}"
            if k < 4:
                accn, form = f"Q-{y}-{k}", "10-Q"
                filed = (dt.date.fromisoformat(ende) + dt.timedelta(days=40)).isoformat()
            else:
                accn, form, filed = f"K-{y}", "10-K", f"{y + 1}-02-20"
            def zeitraum(posten, tabelle, nur_aufgelaufen=False):
                for jahr_, vergleich in ((y, False), (y - 1, True)):
                    if jahr_ not in tabelle:
                        continue
                    e = f"{jahr_}-{QE[k]}"
                    if k < 4 and not nur_aufgelaufen:
                        f.plus(posten, tabelle[jahr_][k - 1], accn, form, filed, e, start=f"{jahr_}-{QS[k]}")
                    if k > 1 or nur_aufgelaufen or k == 4:
                        if k == 1 and not nur_aufgelaufen:
                            continue
                        f.plus(posten, sum(tabelle[jahr_][:k]), accn, form, filed, e, start=f"{jahr_}-01-01")
            zeitraum("Revenues", um)
            zeitraum("NetIncomeLoss", ni)
            zeitraum("ResearchAndDevelopmentExpense", {j: [5, 5, 5, 5] for j in (2021, 2022, 2023)})
            zeitraum("NetCashProvidedByUsedInOperatingActivities", cf, nur_aufgelaufen=True)
            f.plus("Assets", aktiva[y][k - 1], accn, form, filed, ende)
            if y > 2021:
                f.plus("Assets", aktiva[y - 1][3], accn, form, filed, f"{y - 1}-12-31")
            f.plus("CashAndCashEquivalentsAtCarryingValue", 50, accn, form, filed, ende)
            f.plus("ShortTermInvestments", 30, accn, form, filed, ende)
            deckblatt = (dt.date.fromisoformat(ende) + dt.timedelta(days=25)).isoformat()
            f.plus("EntityCommonStockSharesOutstanding", aktien[y][k - 1], accn, form, filed, deckblatt,
                   einheit="shares", gruppe="dei")
            if k == 4 and y in jahr:
                for posten, wert in jahr[y].items():
                    name = PRETAX if posten == "pretax" else posten
                    if posten in ("AssetsCurrent", "LiabilitiesCurrent", "AccountsReceivableNetCurrent",
                                  "PropertyPlantAndEquipmentNet", "LongTermDebtNoncurrent"):
                        f.plus(name, wert, accn, form, filed, ende)
                    else:
                        f.plus(name, wert, accn, form, filed, ende, start=f"{y}-01-01")
    return f


def baue_companyfacts_zip(pfad: Path) -> Path:
    verbrenner = Fakten()      # Firma mit Mittelabfluss
    verbrenner.plus("NetCashProvidedByUsedInOperatingActivities", -20, "V-1", "10-Q", "2024-05-10", "2024-03-31",
                    start="2024-01-01")
    verbrenner.plus("CashAndCashEquivalentsAtCarryingValue", 100, "V-1", "10-Q", "2024-05-10", "2024-03-31")
    verbrenner.plus("NetIncomeLoss", -25, "V-1", "10-Q", "2024-05-10", "2024-03-31", start="2024-01-01")
    bank = Fakten()            # Bank ohne Umsatzposten
    for posten, wert, vorjahr in (("InterestIncomeExpenseNet", 70, 60), ("NoninterestIncome", 30, 25)):
        bank.plus(posten, wert, "B-1", "10-Q", "2024-05-10", "2024-03-31", start="2024-01-01")
        bank.plus(posten, vorjahr, "B-1", "10-Q", "2024-05-10", "2023-03-31", start="2023-01-01")
    bank.plus("NetIncomeLoss", 0, "B-1", "10-Q", "2024-05-10", "2024-03-31", start="2024-01-01")
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("CIK0000000042.json", json.dumps(musterfirma().json(42)))
        z.writestr("CIK0000000043.json", json.dumps(verbrenner.json(43)))
        z.writestr("CIK0000000044.json", json.dumps(bank.json(44)))
        z.writestr("CIK0000000045.json", json.dumps({"cik": 45, "facts": {}}))
        z.writestr("CIK0000000046.json", "{kaputt")
    return pfad


# --------------------------------------------------------------------------- PatentsView (Sammeldateien des USPTO)
PV_PATENT_KOPF = ["patent_id", "patent_type", "patent_date", "patent_title", "wipo_kind", "num_claims", "withdrawn", "filename"]
PV_INHABER_KOPF = ["patent_id", "assignee_sequence", "assignee_id", "raw_assignee_individual_name_first",
                   "raw_assignee_individual_name_last", "raw_assignee_organization", "assignee_type", "rawlocation_id"]
PV_ZITAT_KOPF = ["patent_id", "citation_sequence", "citation_patent_id", "citation_date", "record_name", "wipo_kind",
                 "citation_category"]
# Nummer, Art, Ausgabetag, zurückgezogen, Inhaber (leer = Privatperson)
PV_PATENTE = [
    ("6000001", "utility", "1999-12-28", 0, ["Alpha Corp"]),                  # vor dem Beginn der Parameter-Historie
    ("7000001", "utility", "2006-02-21", 0, ["Alpha  Corp", "Boeing Co"]),    # zwei Inhaber, doppeltes Leerzeichen
    ("7000002", "utility", "2006-02-21", 1, ["Alpha Corp"]),                  # zurückgezogen
    ("7000003", "utility", "2006-02-28", 0, [""]),                            # gehört einer Privatperson
    ("D500001", "design", "2006-02-21", 0, ["Alpha Corp"]),
    ("H2000", "statutory invention registration", "2006-02-21", 0, ["Alpha Corp"]),
    ("11000001", "utility", "2020-03-31", 0, ["Raytheon Company"]),           # vor der Fusion zu RTX
    ("11000002", "utility", "2020-04-07", 0, ["Raytheon Company"]),           # danach
    ("11500000", "utility", "2022-11-08", 0, ["Alpha Corp"]),
    ("11999000", "utility", "2026-11-03", 0, ["Alpha Corp"]),
    ("11999001", "utility", "2026-11-03", 0, ["BOEING CO"]),
]


def pv_tsv(kopf: list[str], zeilen: list[list]) -> str:
    """Tabulatorgetrennt mit Zeichenketten in Anführungszeichen, wie PatentsView liefert."""
    def feld(v):
        return f'"{v}"' if isinstance(v, str) else str(v)
    return "\n".join(["\t".join(feld(k) for k in kopf)] + ["\t".join(feld(v) for v in z) for z in zeilen]) + "\n"


def baue_patentsview(ordner: Path, roh: bool = True, gepackt: bool = False, zitate: list[tuple] | None = None) -> Path:
    """Legt die Sammeldateien in ``ordner`` an: Patente, Inhaber (wie gedruckt oder vereinheitlicht) und Zitate."""
    ordner.mkdir(parents=True, exist_ok=True)
    patente = pv_tsv(PV_PATENT_KOPF, [[n, art, tag, f"Titel {n}", "B2", 3, zurueck, "ipg.xml"] for n, art, tag, zurueck, _ in PV_PATENTE])
    kopf = PV_INHABER_KOPF if roh else [k.replace("raw_assignee", "disambig_assignee").replace("rawlocation", "location")
                                        for k in PV_INHABER_KOPF]
    inhaber = pv_tsv(kopf, [[n, i, f"a{n}{i}", "" if name else "Kim", "" if name else "Lee", name, 2 if name else 4, "ort"]
                            for n, _, _, _, namen in PV_PATENTE for i, name in enumerate(namen)])
    dateien = {"g_patent.tsv": patente,
               ("g_assignee_not_disambiguated.tsv" if roh else "g_assignee_disambiguated.tsv"): inhaber}
    if zitate is not None:
        dateien["g_us_patent_citation.tsv"] = pv_tsv(PV_ZITAT_KOPF, [[von, i, auf, "2000-01-01", "Name", "B2", "cited by examiner"]
                                                                    for i, (von, auf) in enumerate(zitate)])
    for name, text in dateien.items():
        if gepackt:
            with zipfile.ZipFile(ordner / (name + ".zip"), "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(name, text)
        else:
            (ordner / name).write_text(text, encoding="utf-8")
    return ordner
