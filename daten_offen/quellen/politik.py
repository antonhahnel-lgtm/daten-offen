"""Regierungskonstellation der USA und Wahltermine → PR1-03.

Kein Abruf: Präsidenten, Mehrheiten im Kongress und Wahltermine stehen als Kalender im Code (Quellen: Office of the
Historian des Repräsentantenhauses, Senate Historical Office, National Archives). Nach jeder Wahl muss der Kalender
von Hand fortgeschrieben werden; der Lauf meldet einen schweren Fehler, sobald ein neuer Kongress beginnt, dessen
Mehrheiten fehlen.

  politik_regierung__alle   gilt_ab, praesident, partei, haus, senat, anlass, wert
  politik_wahlen__alle      tag, art (Wahl des Präsidenten und des Kongresses oder Zwischenwahl)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd

from ..kern.ablage import Ablage
from ..kern.schema import MARKT_CIK, Parameter, als_parameter, registriere
from ..kern.zeit import ET, handelbar_ab

# Beginn (12:00 Uhr Ostküstenzeit), Präsident, seine Partei, Mehrheit im Repräsentantenhaus, im Senat, Anlass
ZEITRAEUME = [
    ("2001-01-03", "Clinton", "D", "R", "D", "107. Kongress; Senat 50:50, Stichentscheid Vizepräsident Gore"),
    ("2001-01-20", "Bush", "R", "R", "R", "Amtsantritt Bush; Stichentscheid Vizepräsident Cheney"),
    ("2001-06-06", "Bush", "R", "R", "D", "Senator Jeffords verlässt die Republikaner"),
    ("2003-01-07", "Bush", "R", "R", "R", "108. Kongress"),
    ("2005-01-04", "Bush", "R", "R", "R", "109. Kongress"),
    ("2007-01-04", "Bush", "R", "D", "D", "110. Kongress"),
    ("2009-01-06", "Bush", "R", "D", "D", "111. Kongress"),
    ("2009-01-20", "Obama", "D", "D", "D", "Amtsantritt Obama"),
    ("2011-01-05", "Obama", "D", "R", "D", "112. Kongress"),
    ("2013-01-03", "Obama", "D", "R", "D", "113. Kongress"),
    ("2015-01-06", "Obama", "D", "R", "R", "114. Kongress"),
    ("2017-01-03", "Obama", "D", "R", "R", "115. Kongress"),
    ("2017-01-20", "Trump", "R", "R", "R", "Amtsantritt Trump"),
    ("2019-01-03", "Trump", "R", "D", "R", "116. Kongress"),
    ("2021-01-03", "Trump", "R", "D", "R", "117. Kongress; Senatssitze Georgias bis 20.01. offen"),
    ("2021-01-20", "Biden", "D", "D", "D", "Amtsantritt Biden; Senat 50:50, Stichentscheid Vizepräsidentin Harris"),
    ("2023-01-03", "Biden", "D", "R", "D", "118. Kongress"),
    ("2025-01-03", "Biden", "D", "R", "R", "119. Kongress"),
    ("2025-01-20", "Trump", "R", "R", "R", "Amtsantritt Trump"),
]
NAECHSTER_KONGRESS = date(2027, 1, 3)      # 120. Kongress: Mehrheiten aus der Wahl vom 03.11.2026 nachtragen
WAHLEN_BIS = 2032
TABELLE, TABELLE_WAHLEN = "politik_regierung", "politik_wahlen"

registriere(Parameter(
    id="PR1-03", name="Regierungskonstellation",
    definition="Partei des Präsidenten mit Vorzeichen (+ Demokraten, − Republikaner) mal (1 + Zahl der Kammern des "
               "Kongresses, in denen seine Partei die Mehrheit hat): ±3 = Präsident und beide Kammern einer Partei, "
               "±1 = beide Kammern bei der Gegenpartei. Eine Zeile je Beginn eines Kongresses, Amtsantritt oder "
               "Mehrheitswechsel; Wahltermine in politik_wahlen",
    einheit="Stufe −3 bis +3", frequenz="je Wechsel (rund alle zwei Jahre)",
    offenlegung="amtlich (Wahlergebnisse, Verfassungstermine 3. und 20. Januar)",
    quelle="Kalender im Code nach Office of the Historian (history.house.gov), Senate Historical Office (senate.gov) "
           "und National Archives", lizenz="gemeinfrei (Fakten)", historie_ab="2001",
    verzoegerung="Beginn des Zeitraums (12:00 Uhr Ostküstenzeit), sonst Eröffnung des nächsten Handelstags; bekannt "
                 "ist die Konstellation meist schon seit der Wahl im November",
    schwaechen="Marktweite Größe (cik = 0); der Kalender wird nach jeder Wahl von Hand fortgeschrieben. Knappe "
               "Mehrheiten und Stichentscheide des Vizepräsidenten zählen wie klare Mehrheiten"))


def wert(partei: str, haus: str, senat: str) -> float:
    return (1.0 if partei == "D" else -1.0) * (1 + (haus == partei) + (senat == partei))


def wahltage(bis: int = WAHLEN_BIS) -> pd.DataFrame:
    """Bundeswahlen: Dienstag nach dem ersten Montag im November jedes geraden Jahres."""
    zeilen = []
    for jahr in range(2000, bis + 1, 2):
        erster = date(jahr, 11, 1)
        montag = erster + timedelta(days=(0 - erster.weekday()) % 7)
        zeilen.append({"tag": pd.Timestamp(montag + timedelta(days=1)),
                       "art": "Präsident und Kongress" if jahr % 4 == 0 else "Kongress (Zwischenwahl)"})
    return pd.DataFrame(zeilen)


def regierung() -> pd.DataFrame:
    df = pd.DataFrame(ZEITRAEUME, columns=["gilt_ab", "praesident", "partei", "haus", "senat", "anlass"])
    df["gilt_ab"] = pd.to_datetime(df["gilt_ab"])
    df["wert"] = [wert(p, h, s) for p, h, s in zip(df["partei"], df["haus"], df["senat"])]
    return df


def baue_parameter(df: pd.DataFrame) -> pd.DataFrame:
    beginn = [datetime.combine(t.date(), time(12, 0), tzinfo=ET) for t in df["gilt_ab"]]
    return als_parameter(pd.DataFrame({
        "cik": MARKT_CIK, "parameter_id": "PR1-03",
        "ereignis_zeit": [pd.Timestamp(b).tz_convert("UTC") for b in beginn],
        "verfuegbar_ab": [pd.Timestamp(handelbar_ab(b)) for b in beginn],
        "wert": df["wert"].to_numpy(dtype="float64"), "stand": df["anlass"].to_numpy()}))


def lauf(ablage: Ablage, heute: date | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    heute = heute or datetime.now(ET).date()
    df = regierung()
    ablage.schreibe_bereinigt(TABELLE, "alle", df)
    ablage.schreibe_bereinigt(TABELLE_WAHLEN, "alle", wahltage())
    parameter = baue_parameter(df)
    ablage.schreibe_parameter("politik", parameter)
    letzter = df.iloc[-1]
    info = {"zeitraeume": len(df), "letzter_wechsel": letzter["gilt_ab"].date().isoformat(),
            "aktuell": f"{letzter['praesident']} ({letzter['partei']}), Haus {letzter['haus']}, Senat {letzter['senat']}",
            "kalender_veraltet": heute >= NAECHSTER_KONGRESS}
    return parameter, info, []
