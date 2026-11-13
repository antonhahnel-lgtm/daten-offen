from datetime import date

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import uspto_patente as u
from daten_offen.quellen import uspto_zitate as z
from tests.hilfen import baue_patentsview
from tests.test_patente import firmen

# zitierendes Patent, zitiertes Patent (Erteilungstage und Inhaber in tests/hilfen.py)
ZITATE = [
    ("7000003", "7000001"),        # eine Woche später; das zitierte Patent hat zwei Inhaber
    ("11000002", "11000001"),      # zitiertes Patent gehörte bei der Erteilung noch Raytheon selbst
    ("11000002", "7000001"),       # 14 Jahre: außerhalb des Fensters
    ("11999000", "11500000"),
    ("11999001", "11500000"),
    ("11999001", "11500000"),      # doppelt gemeldet
    ("11999000", "11000002"),      # mehr als fünf Jahre
    ("D500001", "7000001"),        # zitierendes Patent ist kein Erfindungspatent
    ("11999000", "D500001"),       # zitiertes Patent ist kein Erfindungspatent
    ("7000002", "7000001"),        # zitierendes Patent zurückgezogen
    ("11500000", "11000002"),      # zitiertes Patent gehörte bei der Erteilung RTX
    ("7000001", "6000001"),        # gut sechs Jahre
    ("11000001", "11000002"),      # zitiert ein späteres Patent
    ("11999000", "99999999"),      # unbekannte Nummer
]


class Leer:
    def hole(self, url, **kw):
        return None


def bestand(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    roh = baue_patentsview(tmp_path / "roh", zitate=ZITATE)
    u.lauf(ablage, abruf=Leer(), heute=date(2026, 11, 4), historie=roh)
    return ablage, roh


def test_zitate(tmp_path):
    ablage, roh = bestand(tmp_path)
    tage = z.erteilungstage(roh)
    assert tage[7000001] == (pd.Timestamp("2006-02-21") - z.EPOCHE).days and tage[7000002] == -1 and tage[5] == -1
    eigner = z.besitz(ablage)
    assert set(zip(eigner["nummer"], eigner["cik"])) == {
        (6000001, 10), (7000001, 10), (7000001, 12927), (11000001, 1047122), (11000002, 101829), (11500000, 10),
        (11999000, 10), (11999001, 12927)}
    p, info, hinweise = z.lauf(ablage, roh, block=256)
    werte = {(int(r.cik), r.stand): r.wert for r in p.itertuples()}
    assert werte == {(10, "2006-02-28"): 1.0, (12927, "2006-02-28"): 1.0, (1047122, "2020-04-07"): 1.0,
                     (101829, "2022-11-08"): 1.0, (10, "2026-11-03"): 2.0}
    assert set(p["parameter_id"]) == {"GA1-09"}
    zeile = p[(p["cik"] == 10) & (p["stand"] == "2026-11-03")].iloc[0]
    assert zeile["ereignis_zeit"] == pd.Timestamp("2026-11-03 00:00", tz=ET)
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2026-11-04 09:30", tz=ET)
    assert {k: info[k] for k in ("zitate", "zwischen_erfindungspatenten", "im_fenster", "zugeordnet", "anteil_zugeordnet",
                                 "von", "bis", "firmen", "patente_mit_firma")} == {
        "zitate": 14, "zwischen_erfindungspatenten": 10, "im_fenster": 5, "zugeordnet": 5, "anteil_zugeordnet": 1.0,
        "von": "2006-02-28", "bis": "2026-11-03", "firmen": 4, "patente_mit_firma": 7}
    assert len(list(ablage.parameter.glob("parameter__uspto_zitate__*.parquet"))) == 4 and "100.0%" in hinweise[0]


def test_zitate_ohne_dateien(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    with pytest.raises(RuntimeError, match="nur lokal"):
        z.lauf(ablage, None)
    roh = baue_patentsview(tmp_path / "roh")
    with pytest.raises(RuntimeError, match="g_us_patent_citation.tsv fehlt"):
        z.lauf(ablage, roh)
    baue_patentsview(roh, zitate=ZITATE)
    with pytest.raises(RuntimeError, match="uspto_patente zuerst"):
        z.lauf(ablage, roh)
