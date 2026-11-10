"""Rollen in Meldungen mit zwei Beteiligten: Schedule 13D (Aktivisten) und Form 144 (Verkaufsabsicht).

Diese Formulare stehen im Meldungsverzeichnis unter dem Einreicher und unter der betroffenen Firma.
Wer welche Rolle hat, steht nur im Meldungskopf. Je Meldung wird deshalb einmal der Anfang der
Einreichungsdatei gelesen (betroffene Firma = SUBJECT COMPANY). Der Stand je Aktenzeichen wird
gespeichert; neue Meldungen kommen zuerst, die Historie wird rückwärts aufgefüllt.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zustand import Zeitbudget, merke_fortsetzung

TABELLE = "edgar_rollen"
KOPF_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt"
FORM_13D = {"SC 13D", "SCHEDULE 13D"}
FORM_13DA = {"SC 13D/A", "SCHEDULE 13D/A"}
FORM_144 = {"144", "144/A"}
FORMEN = sorted(FORM_13D | FORM_13DA | FORM_144)
ABSCHNITT = re.compile(r"^(SUBJECT COMPANY|ISSUER|FILED BY|REPORTING-OWNER|FILER):", re.M)
CIK = re.compile(r"CENTRAL INDEX KEY:\s*(\d+)")
BETROFFEN = ("SUBJECT COMPANY", "ISSUER")
LAUFEND_MINUTEN = 45   # im Tagesbetrieb höchstens so lange Historie nachholen

_Q = "SEC EDGAR, Kopf der Einreichungsdatei je Meldung"
_L = "gemeinfrei (US-Behörde)"


def _p(id_, name, definition, offen, schwaechen=""):
    return Parameter(id=id_, name=name, definition=definition, einheit="Kennzeichen (1 = Ereignis)",
                     frequenz="je Meldung", offenlegung=offen, quelle=_Q, lizenz=_L, historie_ab="2006",
                     verzoegerung="Annahmezeit der Meldung", schwaechen=schwaechen)


registriere(
    _p("IH5-01", "13D-Einstieg", "Erstmeldung Schedule 13D zur betroffenen Firma",
       "gesetzlich: Section 13(d) Exchange Act, seit 02/2024 Frist 5 Geschäftstage",
       schwaechen="Beteiligungshöhe und erklärtes Ziel fehlen (Text der Meldung)"),
    _p("IH5-02", "13D-Nachtrag", "Nachtrag Schedule 13D/A zur betroffenen Firma",
       "gesetzlich: Section 13(d), seit 02/2024 Frist 2 Geschäftstage",
       schwaechen="Richtung (Aufstockung oder Abbau) fehlt (Text der Meldung)"),
    _p("IH1-14", "Verkaufsabsicht Form 144", "Form 144 oder 144/A zur betroffenen Firma",
       "gesetzlich: Rule 144, elektronische Einreichung Pflicht seit 13.04.2023",
       schwaechen="Stückzahl und Wert fehlen (Datei der Meldung); vor 04/2023 kaum elektronische Meldungen"),
)


def lies_kopf(text: str) -> tuple[int | None, int | None]:
    """(betroffene Firma, erster Einreicher) aus dem Kopf einer Einreichungsdatei."""
    marken = list(ABSCHNITT.finditer(text))
    betroffen, einreicher = None, None
    for i, m in enumerate(marken):
        ende = marken[i + 1].start() if i + 1 < len(marken) else len(text)
        nummer = CIK.search(text, m.end(), ende)
        if not nummer:
            continue
        if m.group(1) in BETROFFEN:
            betroffen = betroffen or int(nummer.group(1))
        else:
            einreicher = einreicher or int(nummer.group(1))
    return betroffen, einreicher


def baue_parameter(rollen: pd.DataFrame, meldungen: pd.DataFrame) -> pd.DataFrame:
    if rollen.empty:
        return leer()
    r = rollen[rollen["subject_cik"].notna()].drop_duplicates("accession")
    zeit = meldungen.sort_values("annahme_utc").drop_duplicates("accession")[["accession", "annahme_utc", "verfuegbar_ab"]]
    r = r.merge(zeit, on="accession", how="inner")
    if r.empty:
        return leer()
    pid = pd.Series("", index=r.index)
    pid[r["form"].isin(FORM_13D)] = "IH5-01"
    pid[r["form"].isin(FORM_13DA)] = "IH5-02"
    pid[r["form"].isin(FORM_144)] = "IH1-14"
    r = r[pid != ""]
    return als_parameter(pd.DataFrame({
        "cik": r["subject_cik"].astype("int64").to_numpy(), "parameter_id": pid[pid != ""].to_numpy(),
        "ereignis_zeit": r["annahme_utc"].values, "verfuegbar_ab": r["verfuegbar_ab"].values,
        "wert": 1.0, "stand": r["accession"].to_numpy()}))


def lauf(ablage: Ablage, modus: str = "laufend", abruf: Abruf | None = None, budget: Zeitbudget | None = None,
         max_fehler: int = 25) -> tuple[pd.DataFrame, dict, list[str]]:
    hinweise: list[str] = []
    meldungen = ablage.lies_bereinigt(
        "edgar_meldungen", spalten=["cik", "accession", "form", "filing_date", "annahme_utc", "verfuegbar_ab"],
        filter=[("form", "in", FORMEN)])
    if meldungen.empty:
        raise RuntimeError("Meldungsverzeichnis fehlt (Quelle edgar_index zuerst ausführen)")
    if budget is None:
        budget = Zeitbudget() if modus == "rueckwaerts" else Zeitbudget(LAUFEND_MINUTEN)
    bestand = ablage.lies_bereinigt(TABELLE)
    if bestand.empty:
        bestand = pd.DataFrame(columns=["accession", "form", "filing_date", "subject_cik", "filer_cik", "status"])
    offen = (meldungen.sort_values("annahme_utc", ascending=False).drop_duplicates("accession"))
    offen = offen[~offen["accession"].isin(set(bestand["accession"]))]
    neu, fehler_in_folge, abgebrochen = [], 0, False
    for z in offen.itertuples(index=False):
        if budget.abgelaufen():
            abgebrochen = True
            break
        abruf = abruf or Abruf()
        try:
            roh = abruf.hole_anfang(KOPF_URL.format(cik=int(z.cik), accession=z.accession), erlaube_404=True)
        except QuelleNichtErreichbar:
            fehler_in_folge += 1
            if fehler_in_folge >= max_fehler:
                raise
            continue
        fehler_in_folge = 0
        if roh is None:
            neu.append((z.accession, z.form, z.filing_date, None, None, "fehlt"))
            continue
        betroffen, einreicher = lies_kopf(roh.decode("latin-1", errors="replace"))
        neu.append((z.accession, z.form, z.filing_date, betroffen, einreicher,
                    "gelesen" if betroffen is not None else "ohne_rolle"))
    if neu:
        zusatz = pd.DataFrame(neu, columns=bestand.columns)
        bestand = pd.concat([bestand, zusatz], ignore_index=True) if len(bestand) else zusatz
    bestand["subject_cik"] = pd.to_numeric(bestand["subject_cik"], errors="coerce").astype("Int64")
    bestand["filer_cik"] = pd.to_numeric(bestand["filer_cik"], errors="coerce").astype("Int64")
    bestand["filing_date"] = pd.to_datetime(bestand["filing_date"], errors="coerce")
    for alt in ablage.bereinigt.glob(f"bereinigt__{TABELLE}__*.parquet"):
        alt.unlink()
    for jahr, teil in bestand.groupby(bestand["filing_date"].dt.year):
        ablage.schreibe_bereinigt(TABELLE, str(int(jahr)), teil)
    rest = int(len(offen) - len(neu))
    if abgebrochen and modus == "rueckwaerts":
        merke_fortsetzung(ablage.wurzel, "edgar_rollen")
    if rest:
        hinweise.append(f"{rest} Meldungen noch ohne Rolle (Historie wird im Modus rueckwaerts aufgefüllt)")
    status = bestand["status"].value_counts().to_dict()
    parameter = baue_parameter(bestand, meldungen)
    ablage.schreibe_parameter("edgar_rollen", parameter)
    info = {"meldungen": int(meldungen["accession"].nunique()), "neu_gelesen": len(neu), "offen": rest, **status}
    return parameter, info, hinweise
