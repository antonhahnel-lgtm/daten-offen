"""Ausübungen von Optionen durch Insider (Formulare 4 und 5) → UA6-02.

Quelle wie bei edgar_insider: die amtlichen Quartalsdatensätze der SEC, hier die Tabelle der derivativen
Geschäfte (DERIV_TRANS) mit Basispreis und Verfalltag. Für Quartale ohne Datensatz werden die Form-4-Dateien
gelesen, die edgar_insider schon als Meldung mit Ausübung (Code M, X oder O) kennt.

Der Kurs am Ausübungstag stammt aus derselben Meldung: Verkäufe (S) und Einbehalt für Basispreis oder Steuer (F)
am selben Tag, nach Stück gewichtet. Eine Kursreihe wird nicht verwendet.

  insider_ausuebungen__<jahr>q<q>        eine Zeile je ausgeübter Tranche
  insider_ausuebungen_stand__<jahr>q<q>  gelesene Form-4-Dateien (Quartale ohne Datensatz)
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET_XML
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab_serie
from ..kern.zustand import Zeitbudget, merke_fortsetzung
from .edgar_insider import (DATEN_SEITE, DATEN_URLS, TABELLE as TABELLE_INSIDER, _datum, _lies_tsv, _sp, _text,
                            links_aus_seite, quartale, xml_adresse)

TABELLE, STAND = "insider_ausuebungen", "insider_ausuebungen_stand"
SPALTEN = ["accession", "zeile", "form", "filing_date", "issuer_cik", "owner_cik", "owner_name", "ist_direktor",
           "ist_officer", "ist_zehn_prozent", "titel", "ist_ceo", "trans_date", "code", "wertpapier", "basis", "stueck",
           "verfall", "restlaufzeit", "kurs", "kurs_zu_basis", "quartal", "herkunft"]
CODES = ("M", "X", "O")           # Ausübung nach Rule 16b-3, im Geld, aus dem Geld
OPTION = re.compile(r"option|appreciation right|\bsars?\b|qualified stock", re.I)
KEINE_OPTION = re.compile(r"warrant|note|subscription|restricted|phantom|unit|convertible|preferred|debenture", re.I)
CEO = re.compile(r"\b(?:ceo|chief executive|principal executive)\b", re.I)
FORMEN = ("4", "4/A", "5", "5/A")
MINDESTENS_JE_QUARTAL = 1_000     # weniger Ausübungen im jüngsten Datensatz: Aufbau geändert?

registriere(Parameter(
    id="UA6-02", name="Optionen bis nahe Verfall gehalten",
    definition="Je Meldung, in der der CEO Optionen oder Wertsteigerungsrechte ausübt (Code M, X oder O): kürzeste "
               "Restlaufzeit der ausgeübten Tranchen bis zum Verfall, in Jahren. Kleine Werte (unter 1) entsprechen "
               "dem „Longholder“ von Malmendier & Tate (2005), große einer frühen Ausübung. Alle Insider, Basispreis "
               "und Kurs am Ausübungstag (aus Verkäufen und Einbehalt derselben Meldung) stehen in insider_ausuebungen",
    einheit="Jahre", frequenz="je Ausübungsmeldung",
    offenlegung="gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage",
    quelle="SEC Insider Transactions Data Sets (Tabelle DERIV_TRANS); für Quartale ohne Datensatz die Form-4-Dateien",
    lizenz="gemeinfrei (US-Behörde)", historie_ab="2006",
    verzoegerung="Annahmezeit der Meldung (aus edgar_index)",
    schwaechen="CEO nur über den Freitext des Titels erkennbar; Malmendier & Tate verlangen zusätzlich, dass die Option "
               "zu Beginn ihres letzten Jahres mindestens 40 % im Geld war – hier ist nur das Verhältnis von Kurs und "
               "Basispreis am Ausübungstag bekannt (Spalte kurs_zu_basis). Gehaltene, nicht ausgeübte Optionen fehlen"))


# --------------------------------------------------------------------------- gemeinsame Aufbereitung
def baue_tabelle(kopf: pd.DataFrame, person: pd.DataFrame, deriv: pd.DataFrame, nonderiv: pd.DataFrame,
                 teil: str, herkunft: str) -> pd.DataFrame:
    """``deriv``: accession, zeile, trans_date, code, erwerb, wertpapier, basis, stueck, verfall;
    ``nonderiv``: accession, trans_date, code, erwerb, stueck, preis."""
    d = deriv[deriv["code"].isin(CODES) & (deriv["erwerb"] == "D") & (deriv["basis"] > 0) & deriv["verfall"].notna()
              & deriv["trans_date"].notna() & deriv["wertpapier"].fillna("").str.contains(OPTION)
              & ~deriv["wertpapier"].fillna("").str.contains(KEINE_OPTION)].copy()
    d["restlaufzeit"] = (d["verfall"] - d["trans_date"]).dt.days / 365.25
    d = d[d["restlaufzeit"] >= 0]
    n = nonderiv[nonderiv["code"].isin(["S", "F"]) & (nonderiv["erwerb"] == "D") & (nonderiv["preis"] > 0)
                 & (nonderiv["stueck"] > 0)]
    kurs = (n.assign(w=n["stueck"] * n["preis"]).groupby(["accession", "trans_date"])[["w", "stueck"]].sum())
    kurs = (kurs["w"] / kurs["stueck"]).rename("kurs").reset_index()
    d = d.merge(kurs, on=["accession", "trans_date"], how="left")
    d["kurs_zu_basis"] = d["kurs"] / d["basis"]
    df = d.merge(kopf, on="accession", how="inner").merge(person, on="accession", how="left")
    df = df[df["issuer_cik"].notna() & df["owner_cik"].notna()].copy()
    for s in ("issuer_cik", "owner_cik"):
        df[s] = df[s].astype("int64")
    for s in ("ist_direktor", "ist_officer", "ist_zehn_prozent"):
        df[s] = df[s].fillna(False).astype(bool)
    df["ist_ceo"] = (df["ist_officer"] & df["titel"].fillna("").str.contains(CEO)).astype(bool)
    df["quartal"], df["herkunft"] = teil, herkunft
    for s in ("trans_date", "verfall", "filing_date"):
        df[s] = pd.to_datetime(df[s]).astype("datetime64[ns]")
    return df[SPALTEN].sort_values(["filing_date", "accession", "zeile"], kind="stable").reset_index(drop=True)


def _person(own: pd.DataFrame) -> pd.DataFrame:
    erster = own.assign(_acc=own["ACCESSION_NUMBER"].str.strip()).drop_duplicates("_acc")
    bez = _sp(erster, "RPTOWNER_RELATIONSHIP").astype("string").str.lower().fillna("")
    return pd.DataFrame({
        "accession": erster["_acc"].to_numpy(),
        "owner_cik": pd.to_numeric(_sp(erster, "RPTOWNERCIK"), errors="coerce").to_numpy(),
        "owner_name": _sp(erster, "RPTOWNERNAME").astype("string").str.strip().to_numpy(),
        "ist_direktor": bez.str.contains("director").to_numpy(), "ist_officer": bez.str.contains("officer").to_numpy(),
        "ist_zehn_prozent": bez.str.contains("ten").to_numpy(),
        "titel": _sp(erster, "RPTOWNER_TITLE").astype("string").str.strip().to_numpy()})


def lies_quartal(zip_pfad: Path, teil: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_pfad) as archiv:
        sub = _lies_tsv(archiv, "SUBMISSION.tsv")
        own = _lies_tsv(archiv, "REPORTINGOWNER.tsv")
        dt = _lies_tsv(archiv, "DERIV_TRANS.tsv")
        nd = _lies_tsv(archiv, "NONDERIV_TRANS.tsv")
    for name, df, spalten in (("DERIV_TRANS", dt, ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "CONV_EXERCISE_PRICE",
                                                     "EXPIRATION_DATE", "SECURITY_TITLE", "TRANS_ACQUIRED_DISP_CD"]),
                              ("SUBMISSION", sub, ["ACCESSION_NUMBER", "FILING_DATE", "ISSUERCIK"])):
        fehlend = [c for c in spalten if c not in df.columns]
        if fehlend:
            raise KeyError(f"{name}: Pflichtspalten fehlen {fehlend} (vorhanden: {list(df.columns)})")
    kopf = pd.DataFrame({
        "accession": sub["ACCESSION_NUMBER"].str.strip(),
        "form": _sp(sub, "DOCUMENT_TYPE").astype("string").str.strip(),
        "filing_date": _datum(_sp(sub, "FILING_DATE")),
        "issuer_cik": pd.to_numeric(_sp(sub, "ISSUERCIK"), errors="coerce")}).drop_duplicates("accession")
    gross = lambda df, s: _sp(df, s).astype("string").str.strip().str.upper()
    deriv = pd.DataFrame({
        "accession": dt["ACCESSION_NUMBER"].str.strip(), "zeile": np.arange(len(dt)),
        "trans_date": _datum(_sp(dt, "TRANS_DATE")), "code": gross(dt, "TRANS_CODE"), "erwerb": gross(dt, "TRANS_ACQUIRED_DISP_CD"),
        "wertpapier": _sp(dt, "SECURITY_TITLE").astype("string").str.strip(),
        "basis": pd.to_numeric(_sp(dt, "CONV_EXERCISE_PRICE"), errors="coerce"),
        "stueck": pd.to_numeric(_sp(dt, "TRANS_SHARES"), errors="coerce").fillna(pd.to_numeric(_sp(dt, "UNDLYNG_SEC_SHARES"), errors="coerce")),
        "verfall": _datum(_sp(dt, "EXPIRATION_DATE"))})
    nonderiv = pd.DataFrame({
        "accession": nd["ACCESSION_NUMBER"].str.strip(), "trans_date": _datum(_sp(nd, "TRANS_DATE")),
        "code": gross(nd, "TRANS_CODE"), "erwerb": gross(nd, "TRANS_ACQUIRED_DISP_CD"),
        "stueck": pd.to_numeric(_sp(nd, "TRANS_SHARES"), errors="coerce"),
        "preis": pd.to_numeric(_sp(nd, "TRANS_PRICEPERSHARE"), errors="coerce")})
    return baue_tabelle(kopf, _person(own), deriv, nonderiv, teil, "datensatz")


def _tag(text: str | None) -> pd.Timestamp:
    return pd.to_datetime((text or "")[:10], format="%Y-%m-%d", errors="coerce")


def lies_xml(inhalt: bytes, accession: str, filing_date, teil: str) -> pd.DataFrame:
    """Derivative und nicht-derivative Geschäfte einer Form-4-Rohdatei."""
    wurzel = ET_XML.fromstring(inhalt)
    if wurzel.tag != "ownershipDocument":
        raise ValueError(f"unerwartetes Wurzelelement {wurzel.tag}")
    personen = wurzel.findall("reportingOwner")
    erste = personen[0] if personen else None
    bez = erste.find("reportingOwnerRelationship") if erste is not None else None
    ja = lambda t: str(t or "").strip().lower() in ("1", "true", "y", "yes")
    kopf = pd.DataFrame([{"accession": accession, "form": _text(wurzel, "documentType"), "filing_date": pd.Timestamp(filing_date),
                          "issuer_cik": pd.to_numeric(_text(wurzel, "issuer/issuerCik"), errors="coerce")}])
    person = pd.DataFrame([{"accession": accession, "owner_cik": pd.to_numeric(_text(erste, "reportingOwnerId/rptOwnerCik"), errors="coerce"),
                            "owner_name": _text(erste, "reportingOwnerId/rptOwnerName"),
                            "ist_direktor": ja(_text(bez, "isDirector")), "ist_officer": ja(_text(bez, "isOfficer")),
                            "ist_zehn_prozent": ja(_text(bez, "isTenPercentOwner")), "titel": _text(bez, "officerTitle")}])
    zahl = lambda knoten, pfad: pd.to_numeric(_text(knoten, pfad), errors="coerce")
    deriv = pd.DataFrame([{
        "accession": accession, "zeile": i, "trans_date": _tag(_text(t, "transactionDate")),
        "code": (_text(t, "transactionCoding/transactionCode") or "").upper() or None,
        "erwerb": (_text(t, "transactionAmounts/transactionAcquiredDisposedCode") or "").upper() or None,
        "wertpapier": _text(t, "securityTitle"), "basis": zahl(t, "conversionOrExercisePrice"),
        "stueck": zahl(t, "transactionAmounts/transactionShares"), "verfall": _tag(_text(t, "expirationDate"))}
        for i, t in enumerate(wurzel.findall("derivativeTable/derivativeTransaction"))],
        columns=["accession", "zeile", "trans_date", "code", "erwerb", "wertpapier", "basis", "stueck", "verfall"])
    nonderiv = pd.DataFrame([{
        "accession": accession, "trans_date": _tag(_text(t, "transactionDate")),
        "code": (_text(t, "transactionCoding/transactionCode") or "").upper() or None,
        "erwerb": (_text(t, "transactionAmounts/transactionAcquiredDisposedCode") or "").upper() or None,
        "stueck": zahl(t, "transactionAmounts/transactionShares"), "preis": zahl(t, "transactionAmounts/transactionPricePerShare")}
        for t in wurzel.findall("nonDerivativeTable/nonDerivativeTransaction")],
        columns=["accession", "trans_date", "code", "erwerb", "stueck", "preis"])
    for df, spalten in ((deriv, ("basis", "stueck")), (nonderiv, ("stueck", "preis"))):
        for s in spalten:
            df[s] = df[s].astype("float64")
        for s in ("trans_date",) + (("verfall",) if "verfall" in df else ()):
            df[s] = pd.to_datetime(df[s])
    return baue_tabelle(kopf, person, deriv, nonderiv, teil, "xml")


# --------------------------------------------------------------------------- Quartale ohne Datensatz
def ergaenze_aus_xml(ablage: Ablage, abruf, budget: Zeitbudget, teil: str, kandidaten: pd.DataFrame,
                     max_fehler: int = 25) -> dict:
    """``kandidaten``: accession, cik, filing_date, primary_document der Meldungen mit Ausübung im Quartal."""
    stand_pfad = ablage.bereinigt / f"bereinigt__{STAND}__{teil}.parquet"
    daten_pfad = ablage.bereinigt / f"bereinigt__{TABELLE}__{teil}.parquet"
    gesehen = pd.read_parquet(stand_pfad) if stand_pfad.exists() else pd.DataFrame(columns=["accession", "status"])
    alt = pd.read_parquet(daten_pfad) if daten_pfad.exists() else pd.DataFrame(columns=SPALTEN)
    offen = kandidaten.drop_duplicates("accession")
    offen = offen[~offen["accession"].isin(set(gesehen["accession"]))]
    neu, status, fehler_in_folge, abgebrochen = [], [], 0, False
    for z in offen.itertuples(index=False):
        if budget.abgelaufen():
            abgebrochen = True
            break
        url = xml_adresse(z.cik, z.accession, z.primary_document)
        if url is None:
            status.append((z.accession, "keine_xml"))
            continue
        try:
            antwort = abruf.hole(url, erlaube_404=True)
        except QuelleNichtErreichbar:
            fehler_in_folge += 1
            if fehler_in_folge >= max_fehler:
                raise
            continue
        fehler_in_folge = 0
        if antwort is None:
            status.append((z.accession, "fehlt"))
            continue
        try:
            df = lies_xml(antwort.content, z.accession, z.filing_date, teil)
        except (ET_XML.ParseError, ValueError):
            status.append((z.accession, "unlesbar"))
            continue
        status.append((z.accession, "gelesen" if len(df) else "ohne_option"))
        if len(df):
            neu.append(df)
    if neu:
        teile = [t for t in [alt] + neu if len(t)]
        ablage.schreibe_bereinigt(TABELLE, teil, pd.concat(teile, ignore_index=True))
    if status:
        ablage.schreibe_bereinigt(STAND, teil, pd.concat([gesehen, pd.DataFrame(status, columns=["accession", "status"])],
                                                         ignore_index=True))
    zaehlung = pd.Series([s for _, s in status]).value_counts().to_dict() if status else {}
    return {"quartal": teil, "offen": int(len(offen) - len(status)), "abgebrochen": abgebrochen, **zaehlung}


# --------------------------------------------------------------------------- Parameter
def baue_parameter(df: pd.DataFrame, meldungen: pd.DataFrame) -> pd.DataFrame:
    """Je Meldung des CEO die kürzeste Restlaufzeit; Nachträge (/A) entfallen, wenn das Original vorliegt.
    Wie bei edgar_insider zählen nur Ausübungen bis zum Einreichungstag und höchstens drei Jahre davor."""
    plausibel = (df["trans_date"] <= df["filing_date"]) & (df["trans_date"] >= df["filing_date"] - pd.Timedelta(days=3 * 366))
    c = df[df["ist_ceo"] & plausibel].copy()
    if c.empty:
        return leer()
    schluessel = ["issuer_cik", "owner_cik", "trans_date", "verfall", "basis", "stueck"]
    c["stueck"] = c["stueck"].fillna(-1.0)
    nachtrag = c["form"].astype("string").fillna("").str.endswith("/A").to_numpy()
    original = c.loc[~nachtrag, schluessel].drop_duplicates().assign(_orig=True)
    c = c.merge(original, on=schluessel, how="left")
    c = c[~(nachtrag & c["_orig"].notna().to_numpy())]
    c = c.sort_values(["accession", "restlaufzeit", "trans_date"], kind="stable").drop_duplicates("accession")
    zeit = pd.DataFrame(columns=["accession", "verfuegbar_ab"])
    if not meldungen.empty:
        zeit = meldungen[["accession", "annahme_utc", "verfuegbar_ab"]].sort_values("annahme_utc").drop_duplicates("accession")[["accession", "verfuegbar_ab"]]
    c = c.merge(zeit, on="accession", how="left")
    fehlt = c["verfuegbar_ab"].isna()
    c["verfuegbar_ab"] = pd.to_datetime(c["verfuegbar_ab"], utc=True).astype("datetime64[us, UTC]")
    if fehlt.any():
        ersatz = (c.loc[fehlt, "filing_date"] + pd.Timedelta(hours=17, minutes=30)).dt.tz_localize(
            ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
        c.loc[fehlt, "verfuegbar_ab"] = handelbar_ab_serie(ersatz).astype("datetime64[us, UTC]")
    c["ereignis_zeit"] = c["trans_date"].dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    c = c.dropna(subset=["ereignis_zeit", "verfuegbar_ab"])
    return als_parameter(pd.DataFrame({
        "cik": c["issuer_cik"].to_numpy(), "parameter_id": "UA6-02", "ereignis_zeit": c["ereignis_zeit"].to_numpy(),
        "verfuegbar_ab": c["verfuegbar_ab"].to_numpy(), "wert": c["restlaufzeit"].round(4).to_numpy(),
        "stand": c["accession"].to_numpy()}))


# --------------------------------------------------------------------------- Lauf
def _teile(ablage: Ablage, tabelle: str) -> set[str]:
    return {p.name.split("__")[2].removesuffix(".parquet") for p in ablage.bereinigt.glob(f"bereinigt__{tabelle}__*.parquet")}


def _schluessel(teil: str) -> tuple[int, int]:
    j, q = teil.split("q")
    return int(j), int(q)


def lauf(ablage: Ablage, arbeits: Path, ab_jahr: int = 2006, heute: date | None = None, abruf=None,
         budget: Zeitbudget | None = None, lokal: Path | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    """Liest fehlende Quartale aus den Datensätzen (einmalig je Quartal), danach die Form-4-Dateien der Quartale
    ohne Datensatz, und rechnet den Parameter neu. ``lokal``: Ordner mit Archiven statt Abruf (Tests)."""
    arbeits, heute = Path(arbeits), heute or date.today()
    budget = budget or Zeitbudget()
    hinweise: list[str] = []
    amtlich = set()                                   # Quartale aus einem Datensatz (auch ohne jede Ausübung)
    for teil in _teile(ablage, TABELLE) - _teile(ablage, STAND):
        h = pd.read_parquet(ablage.bereinigt / f"bereinigt__{TABELLE}__{teil}.parquet", columns=["herkunft"])["herkunft"]
        if (h == "datensatz").all():
            amtlich.add(teil)
    seitenlinks, gelesen, unveroeffentlicht = None, [], []
    for jahr, q in quartale(ab_jahr, heute):
        teil = f"{jahr}q{q}"
        if teil in amtlich:
            continue
        if budget.abgelaufen():
            merke_fortsetzung(ablage.wurzel, "edgar_ausuebungen")
            hinweise.append("Zeitbudget erreicht; Lauf wird fortgesetzt")
            return leer(), {"unvollstaendig": True, "gelesen": gelesen}, hinweise
        if lokal is not None:
            pfad = Path(lokal) / f"{teil}_form345.zip"
            pfad = pfad if pfad.exists() else None
        else:
            abruf = abruf or Abruf()
            if seitenlinks is None:
                try:
                    seitenlinks = links_aus_seite(abruf.hole(DATEN_SEITE).text)
                except Exception as fehler:  # Seite nicht lesbar: feste Pfade versuchen
                    seitenlinks = {}
                    hinweise.append(f"SEC-Datenseite nicht lesbar ({type(fehler).__name__}); feste Pfade versucht")
            pfad = None
            for url in dict.fromkeys(([seitenlinks[teil]] if teil in seitenlinks else []) + [m.format(jahr=jahr, q=q) for m in DATEN_URLS]):
                pfad = abruf.hole_datei(url, arbeits / f"{teil}_form345.zip", erlaube_404=True)
                if pfad is not None:
                    break
        if pfad is None:
            unveroeffentlicht.append(teil)
            continue
        ablage.schreibe_bereinigt(TABELLE, teil, lies_quartal(pfad, teil))
        (ablage.bereinigt / f"bereinigt__{STAND}__{teil}.parquet").unlink(missing_ok=True)
        amtlich.add(teil)
        gelesen.append(teil)
        if lokal is None:
            pfad.unlink(missing_ok=True)

    # Quartale nach dem letzten Datensatz: Form-4-Dateien der Meldungen mit Ausübung
    xml_info = []
    letzter = max(amtlich, key=_schluessel) if amtlich else None
    spaeter = sorted((t for t in _teile(ablage, TABELLE_INSIDER) if letzter is None or _schluessel(t) > _schluessel(letzter)), key=_schluessel)
    if spaeter:
        j, q = _schluessel(spaeter[0])
        verzeichnis = ablage.lies_bereinigt("edgar_meldungen", spalten=["cik", "accession", "form", "filing_date", "primary_document"],
                                            filter=[("form", "in", ["4", "4/A"]),
                                                    ("filing_date", ">=", pd.Timestamp(j, 3 * q - 2, 1).to_pydatetime())])
        for teil in spaeter:
            ausuebung = pd.read_parquet(ablage.bereinigt / f"bereinigt__{TABELLE_INSIDER}__{teil}.parquet", columns=["accession", "code"])
            konten = set(ausuebung.loc[ausuebung["code"].isin(CODES), "accession"])
            kandidaten = verzeichnis[verzeichnis["accession"].isin(konten)] if len(verzeichnis) else verzeichnis
            if len(konten) and kandidaten.empty:
                hinweise.append(f"{teil}: {len(konten)} Meldungen mit Ausübung, aber keine im Meldungsverzeichnis")
                continue
            if kandidaten.empty:
                continue
            abruf = abruf or Abruf()
            ergebnis = ergaenze_aus_xml(ablage, abruf, budget, teil, kandidaten)
            xml_info.append(ergebnis)
            if ergebnis["abgebrochen"]:
                merke_fortsetzung(ablage.wurzel, "edgar_ausuebungen")
                hinweise.append(f"Zeitbudget erreicht bei {teil} ({ergebnis['offen']} Meldungen offen); Lauf wird fortgesetzt")
                return leer(), {"unvollstaendig": True, "gelesen": gelesen, "xml": xml_info}, hinweise

    df = ablage.lies_bereinigt(TABELLE)
    if df.empty:
        raise RuntimeError("Keine Ausübungen gelesen")
    meldungen = ablage.lies_bereinigt("edgar_meldungen", spalten=["accession", "form", "annahme_utc", "verfuegbar_ab"],
                                      filter=[("form", "in", list(FORMEN))])
    if meldungen.empty:
        hinweise.append("Meldungsverzeichnis fehlt; Annahmezeiten werden aus dem Einreichungsdatum geschätzt")
    parameter = baue_parameter(df, meldungen)
    ablage.schreibe_parameter("edgar_ausuebungen", parameter)
    je_quartal = df.groupby("quartal").size()
    letzter = max(amtlich, key=_schluessel) if amtlich else None
    ceo = df[df["ist_ceo"]]
    info = {"quartale_datensatz": len(amtlich), "letzter_datensatz": letzter, "gelesen": gelesen,
            "unveroeffentlicht": unveroeffentlicht, "xml": xml_info, "tranchen": int(len(df)),
            "tranchen_letzter_datensatz": int(je_quartal.get(letzter, 0)) if letzter else 0,
            "anteil_mit_kurs": round(float(df["kurs"].notna().mean()), 4), "tranchen_ceo": int(len(ceo)),
            "ceo_unter_1_jahr": round(float((ceo["restlaufzeit"] < 1).mean()), 4) if len(ceo) else 0.0,
            "firmen": int(parameter["cik"].nunique()) if len(parameter) else 0}
    info["fehlende_quartale"] = [f"{j}q{q}" for j, q in quartale(ab_jahr, heute)
                                 if f"{j}q{q}" not in amtlich and letzter and (j, q) < _schluessel(letzter)]
    return parameter, info, hinweise
