"""Ereignis-Parameter aus dem EDGAR-Meldungsverzeichnis (ohne Abruf einzelner Meldungen).

Genutzt werden nur Formulare, die die Firma selbst einreicht (8-K, Form D, 424B, S-3) oder die
eindeutig eine Firma betreffen (Form 25, Form 15). Formulare mit zwei Beteiligten (Schedule 13D,
Form 144) brauchen die Rollen aus dem Meldungskopf und folgen in einem eigenen Modul.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.schema import MARKT_CIK, Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab_serie

_Q = "SEC EDGAR, Sammeldatei submissions.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces)"
_L = "gemeinfrei (US-Behörde)"
_G8K = "gesetzlich: Form 8-K, Frist 4 Geschäftstage"


def _p(id_, name, definition, einheit="Kennzeichen (1 = Ereignis)", offen=_G8K, schwaechen="", frequenz="je Meldung"):
    return Parameter(id=id_, name=name, definition=definition, einheit=einheit, frequenz=frequenz,
                     offenlegung=offen, quelle=_Q, lizenz=_L, historie_ab="2006",
                     verzoegerung="Annahmezeit der Meldung", schwaechen=schwaechen)


registriere(
    _p("WS2-04", "8-K-Meldungen nach Item", "Eine Zeile je Item einer 8-K; wert = Item-Nummer (z. B. 2.02)",
       einheit="Item-Nummer", schwaechen="8-K/A (Nachträge) sind nicht enthalten"),
    _p("UA1-10", "Veröffentlichungszeitpunkt der Zahlen",
       "8-K mit Item 2.02; wert = Wochentag (0 = Montag) + Stunde/24 der Annahmezeit in Ostküstenzeit",
       einheit="Wochentag + Tagesbruchteil"),
    _p("UA2-03", "Restatement / Non-Reliance", "8-K mit Item 4.02"),
    _p("UA2-04", "Prüferwechsel", "8-K mit Item 4.01"),
    _p("IH6-04", "Neue Schulden", "8-K mit Item 2.03"),
    _p("UA4-05", "Führungswechsel", "8-K mit Item 5.02",
       schwaechen="Item 5.02 umfasst auch Vergütungsänderungen und Direktorenwechsel"),
    _p("GA2-03", "Entlassungs- und Restrukturierungsmeldung", "8-K mit Item 2.05",
       schwaechen="WARN-Meldungen der Bundesstaaten fehlen noch"),
    _p("UA4-01", "Übernahme oder Veräußerung abgeschlossen", "8-K mit Item 2.01",
       schwaechen="Zahlungsart und Käuferbewertung fehlen (Text der Meldung)"),
    _p("UA3-03", "Kapitalerhöhung / Privatplatzierung",
       "wert 1 = 8-K Item 3.02, 2 = Prospekt 424B1–424B8, 3 = Form D", einheit="Art (1, 2, 3)",
       offen="gesetzlich: 8-K 3.02, Rule 424(b), Regulation D", schwaechen="Volumen und Abschlag fehlen (Text)"),
    _p("UA3-04", "Shelf-Registrierung", "Einreichung S-3 oder S-3ASR (ohne Nachträge)",
       offen="gesetzlich: Form S-3", schwaechen="Restvolumen fehlt (Text)"),
    _p("KD1-11", "Delisting, Abmeldung, Insolvenz, Übernahme",
       "wert 1 = Form 25 / 25-NSE (Börsenabmeldung), 2 = Form 15 (Abmeldung bei der SEC), 3 = 8-K Item 1.03 "
       "(Insolvenz), 4 = Übernahmeunterlage der Zielfirma (PREM14A/C, DEFM14A/C, SC 14D9), 5 = 8-K Item 3.01 "
       "(Hinweis der Börse auf Delisting); Einstufung wie classify_filings im Insider-Monitor",
       einheit="Art (1–5)",
       offen="gesetzlich: Rule 12d2-2 (Form 25), Rule 12g-4 / 15d-6 (Form 15), Form 8-K, Schedule 14A/14C, Rule 14d-9",
       schwaechen="Form 25 betrifft teils einzelne Wertpapierklassen; SC TO-T und SC 13E3 fehlen, weil sie unter "
                  "Bieter und Zielfirma stehen und die Rollen noch nicht gelesen werden"),
    Parameter(id="WS3-02", name="Zahl gleichzeitiger Zahlenmeldungen",
              definition="Anzahl der 8-K mit Item 2.02 aller Firmen je Annahmetag (Ostküstenzeit)",
              einheit="Anzahl", frequenz="täglich", offenlegung=_G8K, quelle=_Q, lizenz=_L, historie_ab="2006",
              verzoegerung="bekannt zur Eröffnung des nächsten Handelstags",
              schwaechen="Marktweite Größe (cik = 0); zählt Meldungen, nicht Firmen"),
)

ITEM_PARAMETER = {"4.02": "UA2-03", "4.01": "UA2-04", "2.03": "IH6-04", "5.02": "UA4-05",
                  "2.05": "GA2-03", "2.01": "UA4-01"}
PROSPEKT = {f"424B{i}" for i in range(1, 9)}
FORM25 = {"25", "25-NSE"}
FORM15 = {"15-12B", "15-12G", "15-15D", "15-12B/A", "15-12G/A", "15-15D/A"}
UEBERNAHME = {"PREM14A", "PREM14C", "DEFM14A", "DEFM14C", "SC 14D9"}
BOERSEN_SCHWELLE = 200  # wer mehr Form-25-Meldungen hat, ist eine Börse, keine betroffene Firma


def _zeilen(df: pd.DataFrame, pid: str, wert) -> pd.DataFrame:
    return pd.DataFrame({"cik": df["cik"].to_numpy(), "parameter_id": pid,
                         "ereignis_zeit": df["annahme_utc"].values, "verfuegbar_ab": df["verfuegbar_ab"].values,
                         "wert": wert, "stand": df["accession"].to_numpy()})


def baue_parameter(meldungen: pd.DataFrame, boersen_schwelle: int = BOERSEN_SCHWELLE) -> pd.DataFrame:
    teile = []
    k8 = meldungen[meldungen["form"] == "8-K"].copy()
    if not k8.empty:
        k8["item"] = k8["items"].fillna("").str.split(",")
        je_item = k8.explode("item")
        je_item["item"] = je_item["item"].str.strip()
        je_item = je_item[je_item["item"].str.match(r"^\d+\.\d+$", na=False)]
        teile.append(_zeilen(je_item, "WS2-04", je_item["item"].astype(float).to_numpy()))
        for item, pid in ITEM_PARAMETER.items():
            t = je_item[je_item["item"] == item]
            teile.append(_zeilen(t, pid, 1.0))
        t = je_item[je_item["item"] == "3.02"]
        teile.append(_zeilen(t, "UA3-03", 1.0))
        teile.append(_zeilen(je_item[je_item["item"] == "1.03"], "KD1-11", 3.0))
        teile.append(_zeilen(je_item[je_item["item"] == "3.01"], "KD1-11", 5.0))
        zahlen = je_item[je_item["item"] == "2.02"]
        lokal = zahlen["annahme_utc"].dt.tz_convert(ET)
        bruch = (lokal.dt.hour * 3600 + lokal.dt.minute * 60 + lokal.dt.second) / 86400.0
        teile.append(_zeilen(zahlen, "UA1-10", (lokal.dt.weekday + bruch).round(4).to_numpy()))
        # Marktweite Tageszahl; erst nach Tagesende bekannt
        tag = lokal.dt.normalize()
        anzahl = tag.groupby(tag).size()
        if len(anzahl):
            tagesende = (anzahl.index + pd.Timedelta(hours=23, minutes=59)).tz_convert("UTC")
            teile.append(pd.DataFrame({
                "cik": MARKT_CIK, "parameter_id": "WS3-02",
                "ereignis_zeit": tagesende, "verfuegbar_ab": handelbar_ab_serie(pd.Series(tagesende)).values,
                "wert": anzahl.to_numpy(dtype="float64"),
                "stand": [t.strftime("%Y-%m-%d") for t in anzahl.index]}))
    teile.append(_zeilen(meldungen[meldungen["form"].isin(PROSPEKT)], "UA3-03", 2.0))
    teile.append(_zeilen(meldungen[meldungen["form"] == "D"], "UA3-03", 3.0))
    teile.append(_zeilen(meldungen[meldungen["form"].isin({"S-3", "S-3ASR"})], "UA3-04", 1.0))
    f25 = meldungen[meldungen["form"].isin(FORM25)]
    haeufig = f25["cik"].value_counts()
    boersen = set(haeufig[haeufig > boersen_schwelle].index)
    teile.append(_zeilen(f25[~f25["cik"].isin(boersen)], "KD1-11", 1.0))
    teile.append(_zeilen(meldungen[meldungen["form"].isin(FORM15)], "KD1-11", 2.0))
    teile.append(_zeilen(meldungen[meldungen["form"].isin(UEBERNAHME)], "KD1-11", 4.0))
    teile = [t for t in teile if len(t)]
    if not teile:
        return leer()
    return als_parameter(pd.concat(teile, ignore_index=True))


FORMEN = sorted({"8-K", "D", "S-3", "S-3ASR"} | PROSPEKT | FORM25 | FORM15 | UEBERNAHME)


def lauf(ablage: Ablage, boersen_schwelle: int = BOERSEN_SCHWELLE) -> pd.DataFrame:
    spalten = ["cik", "accession", "form", "items", "annahme_utc", "verfuegbar_ab"]
    meldungen = ablage.lies_bereinigt("edgar_meldungen", spalten=spalten, filter=[("form", "in", FORMEN)])
    if meldungen.empty:
        raise RuntimeError("Meldungsverzeichnis fehlt (Quelle edgar_index zuerst ausführen)")
    parameter = baue_parameter(meldungen, boersen_schwelle)
    ablage.schreibe_parameter("edgar_ereignisse", parameter)
    return parameter
