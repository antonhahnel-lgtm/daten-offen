"""Aufmerksamkeit aus Wikipedia-Seitenaufrufen (Wikimedia, frei lizenziert).

Zuordnung Firma -> Artikel über Wikidata (Eigenschaft P5531 = SEC-Firmenschlüssel CIK), danach
tägliche Aufrufe je Artikel aus der Pageviews-Schnittstelle (ab 07/2015), zu Wochen summiert.
Kennzahl nach Da, Engelberg & Gao (2011): Logarithmus der Wochenaufrufe minus Logarithmus des
Medians der acht Vorwochen.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import handelbar_ab_serie
from ..kern.zustand import Zeitbudget, merke_fortsetzung

SPARQL_URL = "https://query.wikidata.org/sparql"
SPARQL = """SELECT ?cik ?titel WHERE {
  ?firma wdt:P5531 ?cik .
  ?artikel schema:about ?firma ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?titel .
}"""
AUFRUFE_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
               "{artikel}/daily/{von}/{bis}")
ANFANG = date(2015, 7, 1)
ZUORDNUNG, WOCHEN = "wiki_zuordnung", "wiki_wochen"
MINDEST_ZUORDNUNGEN = 500

registriere(Parameter(
    id="WS3-05", name="Wikipedia-Seitenaufrufe (abnormal)",
    definition="ln(Aufrufe der Woche) − ln(Median der Aufrufe der acht Vorwochen) für den englischen Artikel der Firma; "
               "Woche Montag bis Sonntag, nur menschliche Zugriffe",
    einheit="Log-Abweichung", frequenz="wöchentlich",
    offenlegung="frei im Web: Wikimedia Pageviews (CC0), Zuordnung über Wikidata (CC0)",
    quelle="https://wikimedia.org/api/rest_v1/ und https://query.wikidata.org", lizenz="CC0",
    historie_ab="09/2015", verzoegerung="Dienstag der Folgewoche, Eröffnung",
    schwaechen="Nur Firmen mit Wikidata-Eintrag samt CIK; die heutige Zuordnung gilt rückwirkend; "
               "Artikelumbenennungen können Reihen unterbrechen"))


def lade_zuordnung(abruf: Abruf, mindestens: int = MINDEST_ZUORDNUNGEN) -> pd.DataFrame:
    antwort = abruf.hole_json(SPARQL_URL, params={"query": SPARQL, "format": "json"},
                              headers={"Accept": "application/sparql-results+json"})
    zeilen = []
    for b in antwort.get("results", {}).get("bindings", []):
        cik, titel = b.get("cik", {}).get("value", ""), b.get("titel", {}).get("value", "")
        if cik.strip().isdigit() and titel:
            zeilen.append((int(cik), titel))
    df = pd.DataFrame(zeilen, columns=["cik", "titel"]).sort_values(["cik", "titel"])
    df = df.drop_duplicates("cik").drop_duplicates("titel").reset_index(drop=True)
    if len(df) < mindestens:
        raise RuntimeError(f"Wikidata lieferte nur {len(df)} Zuordnungen (erwartet mindestens {mindestens})")
    return df


def lade_aufrufe(abruf: Abruf, titel: str, von: date, bis: date) -> pd.Series:
    """Tägliche Aufrufe eines Artikels (Index: Datum); leer, wenn der Artikel keine Daten hat."""
    url = AUFRUFE_URL.format(artikel=quote(titel.replace(" ", "_"), safe=""), von=von.strftime("%Y%m%d"),
                             bis=bis.strftime("%Y%m%d"))
    antwort = abruf.hole(url, erlaube_404=True)
    if antwort is None:
        return pd.Series(dtype="float64")
    punkte = antwort.json().get("items", [])
    tage = pd.to_datetime([str(p.get("timestamp", ""))[:8] for p in punkte], format="%Y%m%d", errors="coerce")
    s = pd.Series([p.get("views", 0) for p in punkte], index=tage, dtype="float64")
    return s[s.index.notna()]


def _wochen(taeglich: pd.Series, bis_montag: pd.Timestamp) -> pd.DataFrame:
    """Summen je Woche (Montag bis Sonntag); nur Wochen, die vor ``bis_montag`` enden."""
    if taeglich.empty:
        return pd.DataFrame(columns=["woche", "aufrufe"])
    montag = taeglich.index - pd.to_timedelta(taeglich.index.weekday, unit="D")
    w = taeglich.groupby(montag).sum()
    w = w[w.index < bis_montag]
    return pd.DataFrame({"woche": w.index, "aufrufe": w.to_numpy()})


def baue_parameter(wochen: pd.DataFrame) -> pd.DataFrame:
    if wochen.empty:
        return leer()
    w = wochen.sort_values(["cik", "woche"], kind="stable").reset_index(drop=True)
    g = w.groupby("cik", sort=False)
    median = g["aufrufe"].transform(lambda s: s.shift(1).rolling(8).median())
    spanne = (w["woche"] - g["woche"].shift(8)).dt.days
    gueltig = (w["aufrufe"] > 0) & (median > 0) & (spanne <= 70)     # acht Vorwochen ohne große Lücke
    w = w[gueltig].assign(wert=np.log(w["aufrufe"][gueltig]) - np.log(median[gueltig]))
    ende = (w["woche"] + pd.Timedelta(days=6, hours=23, minutes=59)).dt.tz_localize("UTC")
    bekannt = handelbar_ab_serie((w["woche"] + pd.Timedelta(days=8)).dt.tz_localize("UTC"))
    kalender = w["woche"].dt.isocalendar()
    stand = kalender["year"].astype(str) + "-W" + kalender["week"].astype(str).str.zfill(2)
    return als_parameter(pd.DataFrame({"cik": w["cik"].to_numpy(), "parameter_id": "WS3-05", "ereignis_zeit": ende.values,
                                       "verfuegbar_ab": bekannt.values, "wert": w["wert"].to_numpy(),
                                       "stand": stand.to_numpy()}))


def lauf(ablage: Ablage, abruf: Abruf | None = None, heute: date | None = None, budget: Zeitbudget | None = None,
         mindestens: int = MINDEST_ZUORDNUNGEN, max_fehler: int = 25) -> tuple[pd.DataFrame, dict, list[str]]:
    abruf = abruf or Abruf(anfragen_pro_sekunde=15)
    heute = heute or date.today()
    budget = budget or Zeitbudget()
    hinweise: list[str] = []
    zuordnung = lade_zuordnung(abruf, mindestens)
    ablage.schreibe_bereinigt(ZUORDNUNG, "alle", zuordnung)
    bestand = ablage.lies_bereinigt(WOCHEN)
    if bestand.empty:
        bestand = pd.DataFrame({"cik": pd.Series(dtype="int64"), "woche": pd.Series(dtype="datetime64[ns]"),
                                "aufrufe": pd.Series(dtype="float64")})
    bestand["woche"] = pd.to_datetime(bestand["woche"])
    gestern = heute - timedelta(days=1)
    dieser_montag = pd.Timestamp(heute - timedelta(days=heute.weekday()))   # die laufende Woche ist unvollständig
    letzte = bestand.groupby("cik")["woche"].max().to_dict()
    neu, fehler_in_folge, abgebrochen, gelesen = [], 0, False, 0
    for z in zuordnung.itertuples(index=False):
        von = (letzte[z.cik] + pd.Timedelta(days=7)).date() if z.cik in letzte else ANFANG
        if pd.Timestamp(von) >= dieser_montag:
            continue                                   # schon bis zur letzten vollständigen Woche vorhanden
        if budget.abgelaufen():
            abgebrochen = True
            break
        try:
            taeglich = lade_aufrufe(abruf, z.titel, von, gestern)
        except QuelleNichtErreichbar:
            fehler_in_folge += 1
            if fehler_in_folge >= max_fehler:
                raise
            continue
        fehler_in_folge = 0
        gelesen += 1
        w = _wochen(taeglich, dieser_montag)
        if len(w):
            neu.append(w.assign(cik=z.cik))
    if neu:
        bestand = pd.concat([bestand] + neu, ignore_index=True).drop_duplicates(["cik", "woche"], keep="last")
    bestand["cik"] = bestand["cik"].astype("int64")
    bestand = bestand.sort_values(["cik", "woche"], kind="stable")[["cik", "woche", "aufrufe"]]
    ablage.schreibe_bereinigt(WOCHEN, "alle", bestand)
    if abgebrochen:
        merke_fortsetzung(ablage.wurzel, "wikipedia")
        hinweise.append("Zeitbudget erreicht; Lauf wird fortgesetzt")
    parameter = baue_parameter(bestand)
    ablage.schreibe_parameter("wikipedia", parameter)
    info = {"zuordnungen": int(len(zuordnung)), "artikel_gelesen": gelesen, "firmen_mit_daten": int(bestand["cik"].nunique()),
            "wochen": int(len(bestand))}
    return parameter, info, hinweise
