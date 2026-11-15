"""Zinsüberraschungen und Nachrichtenstimmung der Federal Reserve Bank of San Francisco (Markt, cik = 0).

Zwei frei abrufbare Dateien:

* USMPD (United States Monetary Policy Event-Study Database): Änderungen von Zinsfutures und Renditen in einem
  30-Minuten-Fenster um jede Erklärung des Offenmarktausschusses seit 1994. Die Datei wird nach jeder Sitzung
  fortgeschrieben (nach der Sitzung vom 28.10.2026 am 30.10.2026).
* Daily News Sentiment Index: Tageswert der Stimmung in Wirtschaftsnachrichten seit 1980, wöchentlich fortgeschrieben.

  fedsf_ereignisse__alle   je Erklärung: zeit, ungeplant, mp1, ed4, pfad
  fedsf_stimmung__alle     je Tag: tag, wert
"""
from __future__ import annotations

import io
from datetime import date, datetime

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.schema import MARKT_CIK, Parameter, als_parameter, registriere
from ..kern.zeit import ET, EROEFFNUNG, handelbar_ab_serie, naechster_handelstag

SEITE = "https://www.frbsf.org/research-and-insights/data-and-indicators/"
URL_USMPD = "https://www.frbsf.org/wp-content/uploads/USMPD.xlsx"
URL_STIMMUNG = "https://www.frbsf.org/wp-content/uploads/news_sentiment_data.xlsx"
BLATT_USMPD, BLATT_STIMMUNG = "Statements", "Data"
TABELLE_EREIGNISSE, TABELLE_STIMMUNG = "fedsf_ereignisse", "fedsf_stimmung"
VERZUG_HANDELSTAGE = 3      # die Datei erscheint rund zwei Tage nach der Sitzung: bekannt am dritten Handelstag danach
VERZUG_STIMMUNG_TAGE = 12   # wöchentliche Fortschreibung mit Werten bis zum Sonntag davor: ein Montag liegt elf Tage zurück
MIN_EREIGNISSE = 20         # so viele Erklärungen braucht die Schätzung des Pfad-Anteils
MAX_ALTER_EREIGNIS, MAX_ALTER_STIMMUNG = 120, 30      # Tage; darüber gilt die Datei als nicht mehr gepflegt

_L = "Federal Reserve Bank of San Francisco, frei abrufbar; als Quelle zu nennen"
registriere(
    Parameter(id="GW1-01", name="Zinsüberraschung",
              definition="Überraschende Änderung des Leitzinsziels zur laufenden Sitzung, abgeleitet aus Fed-Funds-Futures im "
                         "30-Minuten-Fenster um die Erklärung des Offenmarktausschusses (MP1 der USMPD)",
              einheit="Prozentpunkte", frequenz="je Erklärung (rund acht im Jahr)",
              offenlegung="amtlich: Datei der Federal Reserve Bank of San Francisco, fortgeschrieben nach jeder Sitzung",
              quelle=SEITE + "us-monetary-policy-event-study-database/ (Acosta, Ajello, Bauer, Loria & Miranda-Agrippino 2025)",
              lizenz=_L, historie_ab="02/1994",
              verzoegerung="Eröffnung des dritten Handelstags nach der Erklärung (die Datei erscheint rund zwei Tage danach)",
              schwaechen="Der Wert ist am Markt sofort ablesbar, in dieser Datei aber erst Tage später; die Wirkung am Tag "
                         "selbst lässt sich damit nur rückblickend messen. Vor 1994 keine Werte"),
    Parameter(id="GW1-02", name="Pfad-Anteil der Zinsreaktion (Forward Guidance)",
              definition="Änderung des vierten Zinsfutures (Eurodollar, ab 2022 SOFR) im 30-Minuten-Fenster um die Erklärung "
                         "minus der Teil, den die Zinsüberraschung GW1-01 erklärt (Regression über alle Erklärungen bis "
                         "dahin, mindestens 20)", einheit="Prozentpunkte", frequenz="je Erklärung",
              offenlegung="amtlich: Datei der Federal Reserve Bank of San Francisco", quelle=SEITE + "us-monetary-policy-event-study-database/",
              lizenz=_L, historie_ab="1996", verzoegerung="wie GW1-01",
              schwaechen="Näherung an den zweiten Faktor nach Gürkaynak, Sack & Swanson (2005): ein Future statt der "
                         "ganzen Zinskurve, laufend neu geschätzt"),
    Parameter(id="WS2-05", name="Nachrichtenstimmung des Marktes",
              definition="Daily News Sentiment Index: Stimmung in Wirtschaftsartikeln von 24 US-Zeitungen, Tageswert",
              einheit="Indexwert", frequenz="täglich",
              offenlegung="amtlich: Datei der Federal Reserve Bank of San Francisco, wöchentlich fortgeschrieben",
              quelle=SEITE + "daily-news-sentiment-index/ (Shapiro, Sudhof & Wilson 2020)", lizenz=_L, historie_ab="1980",
              verzoegerung="Eröffnung des ersten Handelstags ab dem zwölften Tag nach dem Berichtstag",
              schwaechen="Frühere Tageswerte können sich bei einer Neuschätzung ändern; gespeichert ist der jeweils "
                         "jüngste Stand, nicht der Stand am Tag selbst"),
)


def handelstag_nach(tag: date, n: int) -> date:
    for _ in range(n):
        tag = naechster_handelstag(tag)
    return tag


def pfad_anteil(mp1: np.ndarray, ed4: np.ndarray, mindestens: int = MIN_EREIGNISSE) -> np.ndarray:
    """Rest der Regression von ``ed4`` auf ``mp1`` über alle Ereignisse bis einschließlich des jeweiligen."""
    aus = np.full(len(mp1), np.nan)
    gut = ~np.isnan(mp1) & ~np.isnan(ed4)
    for i in range(len(mp1)):
        if not gut[i]:
            continue
        x, y = mp1[: i + 1][gut[: i + 1]], ed4[: i + 1][gut[: i + 1]]
        if len(x) < mindestens or x.var() == 0:
            continue
        b = float(((x - x.mean()) * (y - y.mean())).mean() / x.var())
        aus[i] = ed4[i] - (y.mean() + b * (mp1[i] - x.mean()))
    return aus


def lies_usmpd(inhalt: bytes) -> pd.DataFrame:
    t = pd.read_excel(io.BytesIO(inhalt), sheet_name=BLATT_USMPD)
    fehlt = {"date_time", "MP1", "ED4"} - set(t.columns)
    if fehlt:
        raise RuntimeError(f"USMPD: Spalten fehlen ({', '.join(sorted(fehlt))})")
    t = t.dropna(subset=["date_time"]).sort_values("date_time").reset_index(drop=True)
    lokal = pd.to_datetime(t["date_time"]).dt.tz_localize(ET, ambiguous="NaT", nonexistent="NaT")
    aus = pd.DataFrame({"zeit": lokal.dt.tz_convert("UTC"), "tag": lokal.dt.tz_localize(None).dt.normalize(),
                        "ungeplant": pd.to_numeric(t.get("Unscheduled", 0), errors="coerce").fillna(0).astype("int64"),
                        "mp1": pd.to_numeric(t["MP1"], errors="coerce"), "ed4": pd.to_numeric(t["ED4"], errors="coerce")})
    aus = aus.dropna(subset=["zeit"]).reset_index(drop=True)
    aus["pfad"] = pfad_anteil(aus["mp1"].to_numpy(dtype="float64"), aus["ed4"].to_numpy(dtype="float64"))
    return aus


def lies_stimmung(inhalt: bytes) -> pd.DataFrame:
    t = pd.read_excel(io.BytesIO(inhalt), sheet_name=BLATT_STIMMUNG)
    if t.shape[1] < 2:
        raise RuntimeError("Nachrichtenstimmung: Blatt ohne Datums- und Wertspalte")
    aus = pd.DataFrame({"tag": pd.to_datetime(t.iloc[:, 0], errors="coerce"), "wert": pd.to_numeric(t.iloc[:, 1], errors="coerce")})
    return aus.dropna().sort_values("tag").drop_duplicates("tag", keep="last").reset_index(drop=True)


def baue_parameter(ereignisse: pd.DataFrame, stimmung: pd.DataFrame) -> pd.DataFrame:
    bekannt = [pd.Timestamp(datetime.combine(handelstag_nach(t.date(), VERZUG_HANDELSTAGE), EROEFFNUNG, tzinfo=ET)).tz_convert("UTC")
               for t in ereignisse["tag"]]
    teile = []
    for pid, spalte in (("GW1-01", "mp1"), ("GW1-02", "pfad")):
        gut = ereignisse[spalte].notna().to_numpy()
        teile.append(pd.DataFrame({
            "cik": MARKT_CIK, "parameter_id": pid, "ereignis_zeit": ereignisse.loc[gut, "zeit"].values,
            "verfuegbar_ab": [b for b, g in zip(bekannt, gut) if g], "wert": ereignisse.loc[gut, spalte].to_numpy(dtype="float64"),
            "stand": ereignisse.loc[gut, "tag"].dt.strftime("%Y-%m-%d").to_numpy()}))
    ende = (stimmung["tag"] + pd.Timedelta(hours=23, minutes=59)).dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    frei = (stimmung["tag"] + pd.Timedelta(days=VERZUG_STIMMUNG_TAGE)).dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    teile.append(pd.DataFrame({"cik": MARKT_CIK, "parameter_id": "WS2-05", "ereignis_zeit": ende.values,
                               "verfuegbar_ab": handelbar_ab_serie(frei).values, "wert": stimmung["wert"].to_numpy(dtype="float64"),
                               "stand": stimmung["tag"].dt.strftime("%Y-%m-%d").to_numpy()}))
    return als_parameter(pd.concat([t for t in teile if len(t)], ignore_index=True))


def lauf(ablage: Ablage, abruf=None, heute: date | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    abruf = abruf or Abruf(anfragen_pro_sekunde=1, kontakt_noetig=False)
    heute = heute or datetime.now(ET).date()
    ereignisse = lies_usmpd(abruf.hole(URL_USMPD).content)
    stimmung = lies_stimmung(abruf.hole(URL_STIMMUNG).content)
    if ereignisse.empty or stimmung.empty:
        raise RuntimeError("Datei der Fed San Francisco ohne Zeilen")
    ablage.schreibe_bereinigt(TABELLE_EREIGNISSE, "alle", ereignisse)
    ablage.schreibe_bereinigt(TABELLE_STIMMUNG, "alle", stimmung)
    parameter = baue_parameter(ereignisse, stimmung)
    ablage.schreibe_parameter("fed_sf", parameter)
    info = {"erklaerungen": int(len(ereignisse)), "juengste_erklaerung": ereignisse["tag"].max().date().isoformat(),
            "tage_seit_erklaerung": (heute - ereignisse["tag"].max().date()).days,
            "stimmungstage": int(len(stimmung)), "juengster_stimmungstag": stimmung["tag"].max().date().isoformat(),
            "tage_seit_stimmung": (heute - stimmung["tag"].max().date()).days}
    return parameter, info, []
