from datetime import date

import pandas as pd

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import politik


def test_kalender_und_werte():
    df = politik.regierung().set_index("gilt_ab")
    assert df.loc["2009-01-20", "wert"] == 3.0                                     # Obama mit beiden Kammern
    assert df.loc["2011-01-05", "wert"] == 2.0 and df.loc["2015-01-06", "wert"] == 1.0
    assert df.loc["2001-06-06", "wert"] == -2.0 and df.loc["2025-01-20", "wert"] == -3.0
    assert df.loc["2019-01-03", "wert"] == -2.0 and df.loc["2025-01-03", "wert"] == 1.0
    assert df.index.is_monotonic_increasing and set(df["partei"]) == {"D", "R"}
    w = politik.wahltage().set_index("tag")["art"]
    assert w.loc["2000-11-07"] == "Präsident und Kongress" and w.loc["2026-11-03"] == "Kongress (Zwischenwahl)"
    assert pd.Timestamp("2020-11-03") in w.index and pd.Timestamp("2022-11-08") in w.index
    assert pd.Timestamp("2010-11-02") in w.index                           # 1. November ein Montag


def test_lauf(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    p, info, _ = politik.lauf(ablage, heute=date(2026, 11, 15))
    assert len(p) == len(politik.ZEITRAEUME) and set(p["cik"]) == {0} and not info["kalender_veraltet"]
    z = p.set_index("stand")
    # Amtsantritt am Samstag 20.01.2001 und am Feiertag 20.01.2025 (Martin Luther King Day): nächste Eröffnung
    assert z.loc["Amtsantritt Bush; Stichentscheid Vizepräsident Cheney", "verfuegbar_ab"] == pd.Timestamp("2001-01-22 09:30", tz=ET)
    assert z.loc["Amtsantritt Trump", "verfuegbar_ab"].iloc[-1] == pd.Timestamp("2025-01-21 09:30", tz=ET)
    obama = z.loc["Amtsantritt Obama"]
    assert obama["ereignis_zeit"] == obama["verfuegbar_ab"] == pd.Timestamp("2009-01-20 12:00", tz=ET)
    assert politik.lauf(ablage, heute=date(2027, 1, 3))[1]["kalender_veraltet"]
    assert len(ablage.lies_bereinigt("politik_wahlen")) == 17
