"""Gesamtwirtschaft aus FRED und ALFRED (Federal Reserve Bank of St. Louis).

Nur Reihen amtlicher US-Stellen (Fed, Treasury, BLS, EIA), die gemeinfrei sind. Reihen Dritter
(z. B. Konsumklima der Universität Michigan, VIX) bleiben draußen.
Revidierte Monatsreihen kommen mit allen Ständen aus ALFRED: Jede Kennzahl wird so gerechnet,
wie sie am Veröffentlichungstag bekannt war; spätere Revisionen erzeugen neue Zeilen.
Alle Parameter sind marktweit (cik = 0). Zugang: Umgebungsvariable FRED_API_KEY.
"""
from __future__ import annotations

import os
from datetime import timedelta

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.schema import MARKT_CIK, Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab_serie, monatsende_handelbar

BASIS = "https://api.stlouisfed.org/fred"
OFFEN = "9999-12-31"
ANFANG = "1776-07-04"
TERMINE = {"FOMC Press Release": 1.0, "Employment Situation": 2.0, "Consumer Price Index": 3.0}
VORLAUF_TAGE = 28   # Termine gelten als so lange vorher bekannt (die Stellen veröffentlichen Jahrespläne)

_Q = "FRED/ALFRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org)"


def _p(id_, name, definition, einheit, frequenz, herkunft, verzoegerung, schwaechen="", vor=True, historie="2000"):
    return Parameter(id=id_, name=name, definition=definition, einheit=einheit, frequenz=frequenz,
                     offenlegung=f"amtlich: {herkunft}", quelle=_Q, lizenz="gemeinfrei (US-Behörde), Quellenangabe erbeten",
                     historie_ab=historie, verzoegerung=verzoegerung, schwaechen=schwaechen, ereignis_vor_verfuegbar=vor)


registriere(
    _p("GW2-01", "Laufzeitspanne", "Rendite 10-jähriger minus 3-monatiger US-Staatspapiere (DGS10 − DGS3MO)",
       "Prozentpunkte", "täglich", "US-Treasury, H.15 der Fed", "nächster Handelstag", historie="1982"),
    _p("GW2-03", "Kurzer Zins", "Rendite 3-monatiger US-Staatspapiere (DGS3MO)", "Prozent", "täglich",
       "US-Treasury, H.15 der Fed", "nächster Handelstag", historie="1982"),
    _p("GW1-06", "Zinsregime", "Änderung des Leitzinsziels der Fed (obere Grenze, vor 2009 Zielsatz); "
       "Vorzeichen = Richtung der letzten Änderung", "Prozentpunkte", "je Änderung", "Federal Reserve Board",
       "Tag des Inkrafttretens (Folgetag der Ankündigung)", historie="1982"),
    _p("GW3-01", "Ölpreisänderung (Vormonat)", "Logarithmische Änderung des WTI-Spotpreises zum Monatsende (DCOILWTICO)",
       "Log-Änderung", "monatlich", "Energy Information Administration", "erster Handelstag nach Monatsende", historie="1986"),
    _p("GW2-04", "Produktionslücke",
       "Abweichung der Industrieproduktion (log) vom quadratischen Trend seit 1960, gerechnet mit dem Datenstand "
       "des Veröffentlichungstags (nach Cooper & Priestley 2009)", "Log-Punkte", "je Veröffentlichung oder Revision",
       "Federal Reserve Board, G.17", "Veröffentlichungstag 09:15 ET",
       schwaechen="Echtzeit-Trend statt Trend über die ganze Stichprobe wie in der Studie"),
    _p("GW2-06", "Änderung der Jahresinflation",
       "Jahresrate der Verbraucherpreise des jüngsten Monats minus Jahresrate des Vormonats, mit dem Datenstand "
       "des Veröffentlichungstags (CPIAUCSL)", "Prozentpunkte (als Anteil)", "je Veröffentlichung oder Revision",
       "Bureau of Labor Statistics", "Veröffentlichungstag 08:30 ET",
       schwaechen="Ersatz für die unerwartete Inflation; Markterwartungen sind nicht offen verfügbar"),
    _p("GW1-05", "Termine von Fed und Statistik", "wert 1 = FOMC-Entscheidung, 2 = Arbeitsmarktbericht, "
       "3 = Verbraucherpreise; ereignis_zeit = Termin", "Art (1–3)", "je Termin",
       "Federal Reserve Board, Bureau of Labor Statistics", f"gilt als {VORLAUF_TAGE} Tage vor dem Termin bekannt",
       schwaechen="Der wahre Bekanntgabezeitpunkt des Terminplans liegt meist früher", vor=False),
)


# --------------------------------------------------------------------------- Abruf
class Fred:
    def __init__(self, abruf: Abruf | None = None, schluessel: str | None = None):
        self.schluessel = schluessel or os.environ.get("FRED_API_KEY", "").strip()
        if not self.schluessel:
            raise RuntimeError("Umgebungsvariable FRED_API_KEY fehlt (GitHub Secret anlegen)")
        self.abruf = abruf or Abruf(anfragen_pro_sekunde=1.5, kontakt_noetig=False)

    def _hole(self, pfad: str, **params) -> dict:
        params.update(api_key=self.schluessel, file_type="json")
        return self.abruf.hole_json(f"{BASIS}/{pfad}", params=params)

    def beobachtungen(self, serie: str, alle_staende: bool = False) -> pd.DataFrame:
        """Beobachtungen einer Reihe; mit ``alle_staende`` jede je veröffentlichte Fassung (ALFRED)."""
        zeilen, versatz, grenze = [], 0, 100_000
        while True:
            params = dict(series_id=serie, limit=grenze, offset=versatz, sort_order="asc")
            if alle_staende:
                params.update(realtime_start=ANFANG, realtime_end=OFFEN)
            antwort = self._hole("series/observations", **params)
            teil = antwort.get("observations", [])
            zeilen.extend(teil)
            versatz += grenze
            if not teil or versatz >= int(antwort.get("count", 0)):
                break
        df = pd.DataFrame(zeilen, columns=["realtime_start", "realtime_end", "date", "value"])
        df["wert"] = pd.to_numeric(df["value"], errors="coerce")
        df["datum"] = pd.to_datetime(df["date"], errors="coerce")
        df["von"] = pd.to_datetime(df["realtime_start"], errors="coerce")
        df["bis"] = pd.to_datetime(df["realtime_end"].replace(OFFEN, "2262-01-01"), errors="coerce")
        df = df[df["wert"].notna() & df["datum"].notna()]
        return df[["datum", "wert", "von", "bis"]].sort_values(["datum", "von"], kind="stable").reset_index(drop=True)

    def termine(self) -> tuple[pd.DataFrame, list[str]]:
        """Veröffentlichungstermine (auch künftige) der in TERMINE genannten Veröffentlichungen."""
        alle = self._hole("releases", limit=1000).get("releases", [])
        nach_name = {str(r.get("name", "")).strip().lower(): r.get("id") for r in alle}
        teile, fehlend = [], []
        for name, art in TERMINE.items():
            kennung = nach_name.get(name.lower())
            if kennung is None:
                fehlend.append(name)
                continue
            antwort = self._hole("release/dates", release_id=kennung, include_release_dates_with_no_data="true",
                                 realtime_start="2000-01-01", realtime_end=OFFEN, limit=10000, sort_order="asc")
            tage = pd.to_datetime([d.get("date") for d in antwort.get("release_dates", [])], errors="coerce")
            teile.append(pd.DataFrame({"datum": tage, "art": art}))
        df = pd.concat(teile, ignore_index=True) if teile else pd.DataFrame(columns=["datum", "art"])
        return df[df["datum"].notna()].drop_duplicates().reset_index(drop=True), fehlend


# --------------------------------------------------------------------------- Kennzahlen
def _utc(tage: pd.Series, stunde: int, minute: int = 0) -> pd.Series:
    zeit = pd.to_datetime(tage) + pd.Timedelta(hours=stunde, minutes=minute)
    return zeit.dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")


def _zeilen(pid: str, ereignis: pd.Series, verfuegbar: pd.Series, wert, stand) -> pd.DataFrame:
    return pd.DataFrame({"cik": MARKT_CIK, "parameter_id": pid, "ereignis_zeit": pd.Series(ereignis).values,
                         "verfuegbar_ab": pd.Series(verfuegbar).values, "wert": np.asarray(wert, dtype="float64"),
                         "stand": list(stand)})


def taegliche_zinsen(lang: pd.DataFrame, kurz: pd.DataFrame) -> pd.DataFrame:
    z = lang[["datum", "wert"]].merge(kurz[["datum", "wert"]], on="datum", how="outer", suffixes=("_l", "_k")).sort_values("datum")
    ereignis = _utc(z["datum"], 18)                        # Tagesschluss; nutzbar am nächsten Handelstag
    vab = handelbar_ab_serie(ereignis)
    stand = z["datum"].dt.strftime("%Y-%m-%d")
    beide = z["wert_l"].notna() & z["wert_k"].notna()
    return pd.concat([
        _zeilen("GW2-01", ereignis[beide], vab[beide], (z["wert_l"] - z["wert_k"])[beide], stand[beide]),
        _zeilen("GW2-03", ereignis[z["wert_k"].notna()], vab[z["wert_k"].notna()], z["wert_k"].dropna(), stand[z["wert_k"].notna()]),
    ], ignore_index=True)


def zinsregime(ziel_alt: pd.DataFrame, ziel_neu: pd.DataFrame) -> pd.DataFrame:
    """Änderungen des Leitzinsziels: bis 15.12.2008 der Zielsatz, danach die obere Grenze der Spanne."""
    wechsel = pd.Timestamp("2008-12-16")
    z = pd.concat([ziel_alt[ziel_alt["datum"] < wechsel], ziel_neu[ziel_neu["datum"] >= wechsel]])
    z = z.sort_values("datum").drop_duplicates("datum").reset_index(drop=True)
    aenderung = z["wert"].diff()
    t = z[aenderung.notna() & (aenderung != 0)]
    ereignis = _utc(t["datum"], 9, 30)
    return _zeilen("GW1-06", ereignis, handelbar_ab_serie(ereignis), aenderung[t.index].round(4), t["datum"].dt.strftime("%Y-%m-%d"))


def oelpreis(oel: pd.DataFrame) -> pd.DataFrame:
    o = oel[oel["wert"] > 0].sort_values("datum")
    letzter = o.groupby(o["datum"].dt.to_period("M")).tail(1).copy()
    letzter["aenderung"] = np.log(letzter["wert"]).diff()
    letzter = letzter[letzter["aenderung"].notna()]
    # der laufende Monat ist erst nach seinem Ende vollständig
    if len(o):
        letzter = letzter[letzter["datum"].dt.to_period("M") < o["datum"].max().to_period("M")]
    ereignis = _utc(letzter["datum"], 18)
    vab = [monatsende_handelbar(d.year, d.month) for d in letzter["datum"]]
    return _zeilen("GW3-01", ereignis, pd.to_datetime(vab, utc=True), letzter["aenderung"],
                   letzter["datum"].dt.strftime("%Y-%m"))


def _staende(df: pd.DataFrame, ab: str) -> list[pd.Timestamp]:
    return sorted(v for v in df["von"].unique() if pd.Timestamp(v) >= pd.Timestamp(ab))


def _stand_zum(df: pd.DataFrame, tag: pd.Timestamp) -> pd.DataFrame:
    """Die Reihe, wie sie am Tag ``tag`` veröffentlicht war."""
    s = df[(df["von"] <= tag) & (df["bis"] >= tag)]
    return s.drop_duplicates("datum", keep="last").sort_values("datum")


def produktionsluecke(indpro: pd.DataFrame, ab: str = "2000-01-01", start: str = "1960-01-01") -> pd.DataFrame:
    zeilen = []
    basis = indpro[indpro["datum"] >= pd.Timestamp(start)]
    for tag in _staende(basis, ab):
        s = _stand_zum(basis, pd.Timestamp(tag))
        if len(s) < 240 or (s["wert"] <= 0).any():
            continue
        y = np.log(s["wert"].to_numpy())
        t = np.arange(len(y), dtype="float64") / 120.0
        x = np.column_stack([np.ones_like(t), t, t * t])
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        zeilen.append((pd.Timestamp(tag), s["datum"].iloc[-1], float(y[-1] - x[-1] @ beta)))
    if not zeilen:
        return leer()
    z = pd.DataFrame(zeilen, columns=["tag", "monat", "luecke"])
    ereignis = _utc(z["monat"] + pd.offsets.MonthEnd(0), 0)
    veroeffentlicht = _utc(z["tag"], 9, 15)
    return _zeilen("GW2-04", ereignis, handelbar_ab_serie(veroeffentlicht), z["luecke"], z["tag"].dt.strftime("%Y-%m-%d"))


def inflationsaenderung(cpi: pd.DataFrame, ab: str = "2000-01-01") -> pd.DataFrame:
    zeilen = []
    for tag in _staende(cpi, ab):
        s = _stand_zum(cpi, pd.Timestamp(tag))
        if len(s) < 14:
            continue
        d, w = s["datum"].to_numpy(), s["wert"].to_numpy()
        monate = lambda a, b: (pd.Timestamp(a).year - pd.Timestamp(b).year) * 12 + pd.Timestamp(a).month - pd.Timestamp(b).month
        if monate(d[-1], d[-13]) != 12 or monate(d[-2], d[-14]) != 12 or monate(d[-1], d[-2]) != 1:
            continue                        # Lücke in der Reihe: keine Jahresrate
        zeilen.append((pd.Timestamp(tag), pd.Timestamp(d[-1]), (w[-1] / w[-13] - 1) - (w[-2] / w[-14] - 1)))
    if not zeilen:
        return leer()
    z = pd.DataFrame(zeilen, columns=["tag", "monat", "wert"])
    ereignis = _utc(z["monat"] + pd.offsets.MonthEnd(0), 0)
    return _zeilen("GW2-06", ereignis, handelbar_ab_serie(_utc(z["tag"], 8, 30)), z["wert"], z["tag"].dt.strftime("%Y-%m-%d"))


def terminkalender(termine: pd.DataFrame) -> pd.DataFrame:
    if termine.empty:
        return leer()
    t = termine.sort_values(["datum", "art"])
    ereignis = _utc(t["datum"], 9, 30)
    bekannt = handelbar_ab_serie(_utc(t["datum"] - timedelta(days=VORLAUF_TAGE), 9, 30))
    return _zeilen("GW1-05", ereignis, bekannt, t["art"], t["datum"].dt.strftime("%Y-%m-%d"))


# --------------------------------------------------------------------------- Lauf
def lauf(ablage: Ablage, fred: Fred | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    fred = fred or Fred()
    hinweise: list[str] = []
    reihen = {}
    for name, staende in (("DGS10", False), ("DGS3MO", False), ("DFEDTAR", False), ("DFEDTARU", False),
                          ("DCOILWTICO", False), ("INDPRO", True), ("CPIAUCSL", True)):
        reihen[name] = fred.beobachtungen(name, alle_staende=staende)
        if reihen[name].empty:
            raise RuntimeError(f"Reihe {name} ohne Beobachtungen")
        ablage.schreibe_bereinigt(f"fred_{name.lower()}", "alle", reihen[name])
    termine, fehlend = fred.termine()
    if fehlend:
        hinweise.append("Termine nicht gefunden für: " + ", ".join(fehlend))
    ablage.schreibe_bereinigt("fred_termine", "alle", termine)
    teile = [
        taegliche_zinsen(reihen["DGS10"], reihen["DGS3MO"]),
        zinsregime(reihen["DFEDTAR"], reihen["DFEDTARU"]),
        oelpreis(reihen["DCOILWTICO"]),
        produktionsluecke(reihen["INDPRO"]),
        inflationsaenderung(reihen["CPIAUCSL"]),
        terminkalender(termine),
    ]
    parameter = als_parameter(pd.concat([t for t in teile if len(t)], ignore_index=True))
    ablage.schreibe_parameter("fred", parameter)
    info = {name: int(len(df)) for name, df in reihen.items()}
    info["termine"] = int(len(termine))
    return parameter, info, hinweise
