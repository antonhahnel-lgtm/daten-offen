"""Rückrufe und Sicherheitsmeldungen aus drei amtlichen Quellen → GA3-02.

* NHTSA (Fahrzeuge, Ausrüstung, Reifen, Kindersitze): Sammeldateien aller Rückrufkampagnen seit 1967; eine Kampagne
  je Hersteller, bekannt mit der Erfassung des Herstellerberichts (Part 573).
* CPSC (Verbraucherprodukte): Schnittstelle der Rückrufmitteilungen seit 1973; Firma aus dem Titel („X Recalls …“)
  und den genannten Herstellern, Importeuren und Händlern.
* FDA (Arzneimittel, Medizinprodukte, Lebensmittel): Enforcement Reports über openFDA seit 2012; ein Ereignis je
  zurückrufender Firma, bekannt mit dem wöchentlichen Bericht.

  rueckrufe_ereignisse__alle   quelle, kennung, tag, firma, art, klasse, stueck
  rueckrufe_fda__alle          Bestand der FDA-Ereignisse (wird jahresweise fortgeschrieben)
  rueckrufe_zuordnung__alle    firma -> cik, konfidenz, art (je Zeitraum bei Töchtern)
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.namen import Namensabgleich, bereinige, trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab
from .uspto_patente import STUFEN as PATENT_STUFEN

NHTSA_URL = "https://static.nhtsa.gov/odi/ffdd/rcl/{datei}"
NHTSA_DATEIEN = ("FLAT_RCL_PRE_2010.zip", "FLAT_RCL_POST_2010.zip")
NHTSA_SPALTEN = ["RECORD_ID", "CAMPNO", "MAKETXT", "MODELTXT", "YEARTXT", "MFGCAMPNO", "COMPNAME", "MFGNAME", "BGMAN", "ENDMAN",
                 "RCLTYPECD", "POTAFF", "ODATE", "INFLUENCED_BY", "MFGTXT", "RCDATE", "DATEA", "RPNO", "FMVSS", "DESC_DEFECT",
                 "CONEQUENCE_DEFECT", "CORRECTIVE_ACTION", "NOTES", "RCL_CMPT_ID", "MFR_COMP_NAME", "MFR_COMP_DESC",
                 "MFR_COMP_PTNO", "DO_NOT_DRIVE", "PARK_OUTSIDE"]
NHTSA_VERZUG_TAGE = 6           # Erfassung bei der Behörde: 95 % binnen sechs Tagen nach Eingang des Herstellerberichts
CPSC_URL = "https://www.saferproducts.gov/RestWebServices/Recall?format=json"
FDA_URL = "https://api.fda.gov/{bereich}/enforcement.json?search=report_date:[{jahr}0101+TO+{jahr}1231]&limit={seite}&skip={skip}"
FDA_BEREICHE = {"drug": 3, "device": 4, "food": 5}
FDA_AB_JAHR, FDA_SEITE, FDA_NEU_LADEN = 2004, 1000, 2      # laufend werden nur die beiden jüngsten Jahre neu gelesen
ARTEN = {1: "nhtsa", 2: "cpsc", 3: "fda_drug", 4: "fda_device", 5: "fda_food"}
TABELLE, TABELLE_FDA, TABELLE_ZUORDNUNG = "rueckrufe_ereignisse", "rueckrufe_fda", "rueckrufe_zuordnung"
SPALTEN = ["quelle", "kennung", "tag", "firma", "art", "klasse", "stueck"]
MINDEST_KONFIDENZ = 0.90
MINDESTENS = {"nhtsa": 10_000, "cpsc": 5_000, "fda": 20_000}      # weniger Ereignisse: Aufbau der Quelle geändert?
TITEL = re.compile(r"^(.*?)\s+(?:Recalls?|Expands?\s+Recall|Reannounces?|Announces?)\b")
ORT = re.compile(r",\s+of\s+")
ZAHL = re.compile(r"\d[\d,]*")
KLASSE = {"Class I": 1, "Class II": 2, "Class III": 3}

# Hersteller, die unter dem Namen einer Tochter melden: Name -> [(gilt bis, Mutter bis dahin) …] + heutige Mutter.
# Mutter: Name bei EDGAR, None = der Meldende selbst. Ergänzt die Töchterliste der Patente. Von Hand, Stand 11/2026.
TOCHTER_NAMEN = {
    "Chrysler (FCA US, LLC)": "Stellantis N.V.", "Chrysler (FCA US LLC)": "Stellantis N.V.", "FCA US LLC": "Stellantis N.V.",
    "Honda (American Honda Motor Co.)": "HONDA MOTOR CO LTD", "American Honda Motor Co., Inc.": "HONDA MOTOR CO LTD",
    "Toyota Motor Engineering & Manufacturing": "TOYOTA MOTOR CORP/", "Toyota Motor North America, Inc.": "TOYOTA MOTOR CORP/",
    "General Motors LLC": "General Motors Co", "Subaru of America, Inc.": "Subaru Corporation/ADR",
    "PACCAR Incorporated": "PACCAR INC", "Kenworth Truck Company": "PACCAR INC", "Peterbilt Motors Company": "PACCAR INC",
    "Jayco, Inc.": "THOR INDUSTRIES INC", "Keystone RV Company": "THOR INDUSTRIES INC", "Thor Motor Coach": "THOR INDUSTRIES INC",
    "Airstream, Inc.": "THOR INDUSTRIES INC", "Heartland Recreational Vehicles, LLC": "THOR INDUSTRIES INC",
    "Tiffin Motorhomes, Inc.": "THOR INDUSTRIES INC", "Grand Design RV, LLC": "WINNEBAGO INDUSTRIES INC",
    "Newmar Corporation": "WINNEBAGO INDUSTRIES INC", "Forest River, Inc.": "BERKSHIRE HATHAWAY INC",
    "Blue Bird Body Company": "Blue Bird Corp", "Navistar, Inc.": "NAVISTAR INTERNATIONAL CORP",
    "Harley-Davidson Motor Company": "HARLEY-DAVIDSON, INC.",
    "Baxter Healthcare Corporation": "BAXTER INTERNATIONAL INC", "Baxter Healthcare Corp.": "BAXTER INTERNATIONAL INC",
    "Teva Pharmaceuticals USA": "TEVA PHARMACEUTICAL INDUSTRIES LTD", "Hospira Inc.": "PFIZER INC",
    "Dr. Reddy's Laboratories, Inc.": "DR REDDYS LABORATORIES LTD",
    # ergänzt nach dem ersten echten Lauf (größte nicht zugeordnete Namen ab 2010)
    "Mazda North American Operations": "Mazda Motor Corp",
    "Pierce Manufacturing": "OSHKOSH CORP", "E-One Incorporated": "REV Group, Inc.",
    "Textron Specialized Vehicles": "TEXTRON INC", "John Deere": "DEERE & CO", "American Honda": "HONDA MOTOR CO LTD",
    "Fisher-Price": "MATTEL INC /DE/", "TJX": "TJX COMPANIES INC /DE/", "Amazon": "AMAZON COM INC", "BRP U.S. Inc.": "BRP Inc.",
    "GE Healthcare, LLC": "GE HealthCare Technologies Inc.", "Medtronic Neuromodulation": "Medtronic plc",
    "Teleflex Medical": "TELEFLEX INC", "Synthes (USA) Products LLC": "JOHNSON & JOHNSON", "Synthes USA HQ, Inc.": "JOHNSON & JOHNSON",
    "DePuy Orthopaedics, Inc.": "JOHNSON & JOHNSON", "Smiths Medical ASD Inc.": "ICU MEDICAL INC/DE",
    "Cardinal Health 200, LLC": "CARDINAL HEALTH INC", "Stryker Howmedica Osteonics Corp.": "STRYKER CORP",
    "Stryker Instruments Div. of Stryker Corporation": "STRYKER CORP", "Bard Peripheral Vascular Inc": "BECTON DICKINSON & CO",
    "CooperSurgical, Inc.": "COOPER COMPANIES, INC.", "Philips Medical Systems (Cleveland) Inc": "KONINKLIJKE PHILIPS NV",
    "Philips North America Llc": "KONINKLIJKE PHILIPS NV", "Philips Electronics North America Corporation": "KONINKLIJKE PHILIPS NV",
    "Philips Medical Systems Nederland B.V.": "KONINKLIJKE PHILIPS NV", "Mylan Pharmaceuticals Inc.": "Viatris Inc",
    "Taro Pharmaceuticals U.S.A., Inc.": "TARO PHARMACEUTICAL INDUSTRIES LTD", "American Health Packaging": "Cencora, Inc.",
    "Amerisource Health Services LLC": "Cencora, Inc.", "Pharmedium Services, LLC": "Cencora, Inc.",
    "Frito-Lay, Inc.": "PEPSICO INC", "Frito-Lay, Inc. Headquarters": "PEPSICO INC", "B&G Foods North America, Inc": "B&G Foods, Inc.",
    "Whole Foods Market": "AMAZON COM INC", "Whole Food Market": "AMAZON COM INC", "Whole Foods Market Brand 365, Llc": "AMAZON COM INC",
}
TOCHTER_FRUEHER = {
    "Jayco, Inc.": [("2016-06-30", None)], "Heartland Recreational Vehicles, LLC": [("2010-09-17", None)],
    "Tiffin Motorhomes, Inc.": [("2020-12-18", None)], "Grand Design RV, LLC": [("2016-11-08", None)],
    "Newmar Corporation": [("2019-11-08", None)], "Forest River, Inc.": [("2005-08-31", None)],
    "Blue Bird Body Company": [("2015-02-24", None)], "Hospira Inc.": [("2015-09-03", None)],
    "E-One Incorporated": [("2017-01-27", None)], "GE Healthcare, LLC": [("2023-01-04", "GENERAL ELECTRIC CO")],
    "Medtronic Neuromodulation": [("2015-01-26", 64670)], "Synthes (USA) Products LLC": [("2012-06-14", None)],
    "Synthes USA HQ, Inc.": [("2012-06-14", None)], "Smiths Medical ASD Inc.": [("2022-01-06", None)],
    "Bard Peripheral Vascular Inc": [("2017-12-29", 9892)], "Mylan Pharmaceuticals Inc.": [("2020-11-16", None)],
    "Pharmedium Services, LLC": [("2015-11-06", None)], "Whole Foods Market": [("2017-08-28", None)],
    "Whole Food Market": [("2017-08-28", None)], "Whole Foods Market Brand 365, Llc": [("2017-08-28", None)],
}


def _stufen() -> dict:
    stufen = {bereinige(n): [(None, None, m)] for n, m in TOCHTER_NAMEN.items()}
    for name, frueher in TOCHTER_FRUEHER.items():
        grenzen = [pd.Timestamp(bis) for bis, _ in frueher]
        stufen[bereinige(name)] = list(zip([None] + grenzen, grenzen + [None], [m for _, m in frueher] + [TOCHTER_NAMEN.get(name)]))
    return stufen


STUFEN = {**PATENT_STUFEN, **_stufen()}

registriere(Parameter(
    id="GA3-02", name="Rückrufe und Sicherheitsmeldungen",
    definition="Eine Zeile je Rückruf der Firma oder einer bekannten Tochter; wert = Quelle: 1 = NHTSA (Fahrzeuge, "
               "Ausrüstung), 2 = CPSC (Verbraucherprodukte), 3 = FDA Arzneimittel, 4 = FDA Medizinprodukte, 5 = FDA "
               "Lebensmittel. Schwere (FDA-Klasse) und betroffene Stückzahl stehen in rueckrufe_ereignisse",
    einheit="Art (1–5)", frequenz="je Rückruf",
    offenlegung="gesetzlich: 49 CFR Part 573 (NHTSA), Consumer Product Safety Act § 15 (CPSC), 21 CFR Part 7 (FDA)",
    quelle="NHTSA Recalls-Sammeldatei (static.nhtsa.gov/odi/ffdd/rcl), CPSC Recalls-Schnittstelle (saferproducts.gov), "
           "openFDA Enforcement Reports (api.fda.gov)",
    lizenz="gemeinfrei (US-Behörden)", historie_ab="1967 (NHTSA), 1973 (CPSC), 2012 (FDA)",
    verzoegerung="Eröffnung des ersten Handelstags nach der Veröffentlichung: Erfassung bei der NHTSA, Mitteilung der "
                 "CPSC, wöchentlicher Bericht der FDA",
    schwaechen="Zuordnung über Firmennamen und eine kurze Liste von Töchtern (Trefferquote im Prüfbericht); viele "
               "Hersteller sind ausländisch oder privat. Der FDA-Bericht erscheint im Mittel sieben Wochen nach Beginn "
               "des Rückrufs, die Pressemitteilung der Firma ist früher. Beschwerden und Vorkommnisse fehlen"))


# --------------------------------------------------------------------------- NHTSA
def lies_nhtsa(inhalt: bytes) -> pd.DataFrame:
    """Eine Zeile je Rückrufkampagne aus einer Sammeldatei."""
    with zipfile.ZipFile(io.BytesIO(inhalt)) as z, z.open(z.namelist()[0]) as f:
        t = pd.read_csv(f, sep="\t", header=None, names=NHTSA_SPALTEN, dtype="string", quoting=3, encoding="latin-1",
                        on_bad_lines="skip", usecols=["CAMPNO", "MFGNAME", "POTAFF", "RCDATE", "DATEA"])
    t["stueck"] = pd.to_numeric(t["POTAFF"], errors="coerce")
    for spalte in ("RCDATE", "DATEA"):
        t[spalte] = pd.to_datetime(t[spalte], format="%Y%m%d", errors="coerce")
    k = t.dropna(subset=["CAMPNO", "RCDATE"]).groupby("CAMPNO", as_index=False).agg(
        firma=("MFGNAME", "first"), stueck=("stueck", "max"), eingang=("RCDATE", "min"), erfasst=("DATEA", "min"))
    abstand = (k["erfasst"] - k["eingang"]).dt.days
    k["tag"] = k["erfasst"].where((abstand >= 0) & (abstand <= 60), k["eingang"] + pd.Timedelta(days=NHTSA_VERZUG_TAGE))
    return pd.DataFrame({"quelle": "nhtsa", "kennung": k["CAMPNO"].astype(str), "tag": k["tag"], "firma": k["firma"].astype("object"),
                         "art": 1, "klasse": 0, "stueck": k["stueck"]})[SPALTEN].dropna(subset=["firma"])


# --------------------------------------------------------------------------- CPSC
def cpsc_firmen(eintrag: dict) -> list[str]:
    """Firmen eines Rückrufs: aus dem Titel („X Recalls …“) und den genannten Herstellern, Importeuren, Händlern."""
    namen = []
    m = TITEL.match(eintrag.get("Title") or "")
    if m:
        namen.append(m.group(1))
    for feld in ("Manufacturers", "Importers", "Distributors"):
        for e in eintrag.get(feld) or []:
            namen.append(ORT.split(e.get("Name") or "")[0])
    aus = []
    for n in namen:
        n = " ".join(n.split())
        if n and len(n) <= 80 and n not in aus:
            aus.append(n)
    return aus


def lies_cpsc(eintraege: list[dict]) -> pd.DataFrame:
    zeilen = []
    for e in eintraege:
        tag = pd.to_datetime(e.get("RecallDate"), errors="coerce")
        if pd.isna(tag) or e.get("RecallID") is None:
            continue
        stueck = [int(z.group(0).replace(",", "")) for p in e.get("Products") or [] if (z := ZAHL.search(p.get("NumberOfUnits") or ""))]
        for name in cpsc_firmen(e):
            zeilen.append(("cpsc", str(e["RecallID"]), tag.normalize(), name, 2, 0, float(max(stueck)) if stueck else np.nan))
    return pd.DataFrame(zeilen, columns=SPALTEN)


# --------------------------------------------------------------------------- FDA
def lies_fda(ergebnisse: list[dict], bereich: str) -> pd.DataFrame:
    """Ein Ereignis je zurückrufender Firma aus den Zeilen (je Produkt) eines Enforcement Reports."""
    if not ergebnisse:
        return pd.DataFrame(columns=SPALTEN)
    t = pd.DataFrame(ergebnisse)
    t["tag"] = pd.to_datetime(t["report_date"], format="%Y%m%d", errors="coerce")
    t["klasse"] = t["classification"].map(KLASSE).fillna(0).astype("int64")
    t = t.dropna(subset=["tag", "event_id", "recalling_firm"])
    schwer = t["klasse"].where(t["klasse"] > 0, 9)                      # schwerste Klasse des Ereignisses
    g = t.assign(schwer=schwer).groupby(["event_id", "recalling_firm"], as_index=False).agg(tag=("tag", "min"), klasse=("schwer", "min"))
    return pd.DataFrame({"quelle": f"fda_{bereich}", "kennung": g["event_id"].astype(str), "tag": g["tag"],
                         "firma": g["recalling_firm"].astype("object"), "art": FDA_BEREICHE[bereich],
                         "klasse": g["klasse"].where(g["klasse"] < 9, 0), "stueck": np.nan})[SPALTEN]


def hole_fda(abruf, bereich: str, jahre: list[int]) -> pd.DataFrame:
    teile = []
    for jahr in jahre:
        skip, zeilen = 0, []
        while True:
            antwort = abruf.hole(FDA_URL.format(bereich=bereich, jahr=jahr, seite=FDA_SEITE, skip=skip), erlaube_404=True)
            if antwort is None:                                         # keine Treffer in diesem Jahr
                break
            js = antwort.json()
            zeilen += js.get("results") or []
            skip += FDA_SEITE
            if skip >= int(((js.get("meta") or {}).get("results") or {}).get("total", 0)):
                break
        teile.append(lies_fda(zeilen, bereich))
    teile = [t for t in teile if len(t)]
    return pd.concat(teile, ignore_index=True) if teile else pd.DataFrame(columns=SPALTEN)


# --------------------------------------------------------------------------- Zuordnung und Parameter
def ordne_zu(namen: pd.DataFrame, firmen: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """CIK je Firmenname: Töchterliste mit Zeiträumen, sonst Namensabgleich (exakt, früherer Name, Kernname)."""
    abgleich = Namensabgleich(firmen)
    bekannt, unbekannt = set(firmen["cik"].astype(int)), set()

    def selbst(name):
        cik, konfidenz, art = abgleich.finde(name, aehnlich=False)
        return (cik, konfidenz, art) if cik is not None and konfidenz >= MINDEST_KONFIDENZ else (None, 0.0, art if cik is None else "keiner")

    def mutter(m, name):
        if m is None:
            return selbst(name)
        cik = (m if m in bekannt else None) if isinstance(m, int) else abgleich.finde(m, aehnlich=False)[0]
        if cik is None:
            unbekannt.add(str(m))
            return None, 0.0, "keiner"
        return cik, 0.95, "tochter"

    zeilen = []
    for name, anzahl in zip(namen["firma"], namen["rueckrufe"]):
        stufen = STUFEN.get(bereinige(name))
        if stufen is None:
            zeilen.append((name, anzahl, *selbst(name), None, None))
        else:
            zeilen += [(name, anzahl, *mutter(m, name), ab, bis) for ab, bis, m in stufen]
    z = pd.DataFrame(zeilen, columns=["firma", "rueckrufe", "cik", "konfidenz", "art", "gilt_ab", "gilt_bis"])
    z["cik"] = z["cik"].astype("Int64")
    for spalte in ("gilt_ab", "gilt_bis"):
        z[spalte] = pd.to_datetime(z[spalte]).astype("datetime64[ns]")
    return z, sorted(unbekannt)


def baue_parameter(ereignisse: pd.DataFrame, zuordnung: pd.DataFrame) -> pd.DataFrame:
    treffer = zuordnung[zuordnung["cik"].notna()][["firma", "cik", "gilt_ab", "gilt_bis"]]
    z = ereignisse.merge(treffer, on="firma", how="inner")
    z = z[(z["gilt_ab"].isna() | (z["tag"] >= z["gilt_ab"])) & (z["gilt_bis"].isna() | (z["tag"] < z["gilt_bis"]))]
    z = z.drop_duplicates(["cik", "quelle", "kennung"])
    if z.empty:
        return leer()
    zeit = {}
    for tag in z["tag"].drop_duplicates():
        d = pd.Timestamp(tag).date()
        zeit[tag] = (pd.Timestamp(datetime.combine(d, time(0, 0), tzinfo=ET)).tz_convert("UTC"),
                     pd.Timestamp(handelbar_ab(datetime.combine(d, time(18, 0), tzinfo=ET))))
    return als_parameter(pd.DataFrame({
        "cik": z["cik"].astype("int64").to_numpy(), "parameter_id": "GA3-02",
        "ereignis_zeit": [zeit[t][0] for t in z["tag"]], "verfuegbar_ab": [zeit[t][1] for t in z["tag"]],
        "wert": z["art"].to_numpy(dtype="float64"), "stand": (z["quelle"] + ":" + z["kennung"]).to_numpy()}))


# --------------------------------------------------------------------------- Lauf
def lauf(ablage: Ablage, abruf=None, heute: date | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    hinweise: list[str] = []
    firmen = ablage.lies_bereinigt("edgar_firmen")
    if firmen.empty:
        raise RuntimeError("Firmentabelle fehlt (Quelle edgar_index zuerst ausführen)")
    firmen = firmen[firmen["sic"].notna() | firmen["tickers"].notna()]
    heute = heute or datetime.now(ET).date()
    abruf = abruf or Abruf(anfragen_pro_sekunde=2, kontakt_noetig=False)

    nhtsa = pd.concat([lies_nhtsa(abruf.hole(NHTSA_URL.format(datei=d)).content) for d in NHTSA_DATEIEN], ignore_index=True)
    nhtsa = nhtsa.drop_duplicates("kennung", keep="last")
    cpsc = lies_cpsc(abruf.hole(CPSC_URL).json())

    # FDA: Bestand fortschreiben, nur die jüngsten Jahre neu lesen (ohne Bestand alles)
    fda = ablage.lies_bereinigt(TABELLE_FDA)
    jahre = list(range(heute.year - FDA_NEU_LADEN + 1, heute.year + 1)) if len(fda) else list(range(FDA_AB_JAHR, heute.year + 1))
    neu, gestoert = [], []
    for bereich in FDA_BEREICHE:
        try:
            neu.append(hole_fda(abruf, bereich, jahre))
        except QuelleNichtErreichbar as stoerung:
            gestoert.append(bereich)
            hinweise.append(f"FDA {bereich} nicht gelesen ({str(stoerung)[:100]}); Bestand bleibt")
    neu = [t for t in neu if len(t)]
    if neu:
        frisch = pd.concat(neu, ignore_index=True)
        if len(fda):
            fda["tag"] = pd.to_datetime(fda["tag"])
            gelesen = set(frisch["quelle"])
            alt = fda[~(fda["quelle"].isin(gelesen) & fda["tag"].dt.year.isin(jahre))]
            frisch = pd.concat([alt, frisch], ignore_index=True)
        fda = frisch.drop_duplicates(["quelle", "kennung", "firma"], keep="last").sort_values(["tag", "quelle", "kennung"]).reset_index(drop=True)
        ablage.schreibe_bereinigt(TABELLE_FDA, "alle", fda)

    ereignisse = pd.concat([t for t in (nhtsa, cpsc, fda) if len(t)], ignore_index=True)
    ereignisse["tag"] = pd.to_datetime(ereignisse["tag"])
    ereignisse = ereignisse[ereignisse["tag"] <= pd.Timestamp(heute)].sort_values(["tag", "quelle", "kennung", "firma"]).reset_index(drop=True)
    ablage.schreibe_bereinigt(TABELLE, "alle", ereignisse)
    je_firma = ereignisse.groupby("firma", as_index=False).agg(rueckrufe=("kennung", "nunique"))
    zuordnung, unbekannt = ordne_zu(je_firma, firmen)
    ablage.schreibe_bereinigt(TABELLE_ZUORDNUNG, "alle", zuordnung)
    parameter = baue_parameter(ereignisse, zuordnung)
    ablage.schreibe_parameter("rueckrufe", parameter)

    if unbekannt:
        hinweise.append("Mütter der Töchterliste ohne eindeutigen Treffer bei EDGAR: " + ", ".join(unbekannt))
    heutig = zuordnung[zuordnung["gilt_bis"].isna()].reset_index(drop=True)
    quote = trefferquote(heutig, gewicht=heutig["rueckrufe"].astype("float64"))
    je_quelle = ereignisse.groupby("quelle")["kennung"].nunique().to_dict()
    info = {"ereignisse": {k: int(v) for k, v in je_quelle.items()}, "fda_jahre_gelesen": [jahre[0], jahre[-1]],
            "fda_gestoert": gestoert, "juengster_tag": ereignisse["tag"].max().date().isoformat(),
            "firmen": int(parameter["cik"].nunique()) if len(parameter) else 0, "trefferquote": quote}
    hinweise.append(f"Zuordnung: {quote.get('quote', 0):.1%} der Firmennamen, {quote.get('quote_gewichtet', 0):.1%} der Rückrufe")
    return parameter, info, hinweise
