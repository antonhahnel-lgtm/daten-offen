import io
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import fed_sf as f


def excel(blaetter: dict) -> bytes:
    puffer = io.BytesIO()
    with pd.ExcelWriter(puffer, engine="openpyxl") as w:
        for name, tabelle in blaetter.items():
            tabelle.to_excel(w, sheet_name=name, index=False)
    return puffer.getvalue()


def usmpd(n=24) -> bytes:
    rng = np.random.default_rng(3)
    zeiten = pd.date_range("2024-01-31 14:00", periods=n, freq="42D")
    mp1 = rng.normal(0, 0.05, n).round(4)
    ed4 = (0.5 * mp1 + rng.normal(0, 0.03, n)).round(4)
    t = pd.DataFrame({"Date": zeiten.normalize(), "date_time": zeiten, "SEP": 0, "Unscheduled": 0, "MP1": mp1, "MP2": 0.0, "ED4": ed4})
    t.loc[2, "ED4"] = np.nan                                   # fehlender Future: kein Pfad-Anteil, aber Überraschung
    return excel({"README": pd.DataFrame({"a": ["Text"]}), "Statements": t})


def stimmung() -> bytes:
    tage = pd.to_datetime(["2026-10-30", "2026-11-02", "2026-11-08"])
    return excel({"Methodology": pd.DataFrame({"a": ["Text"]}), "Data": pd.DataFrame({"date": tage, "News Sentiment": [0.10, -0.20, 0.05]})})


class Quelle:
    def __init__(self, dateien):
        self.dateien = dateien

    def hole(self, url, **kw):
        return SimpleNamespace(content=self.dateien[url])


def test_pfad_anteil():
    mp1 = np.array([0.1, -0.1, 0.2, 0.0, 0.05])
    ed4 = 0.02 + 0.5 * mp1
    aus = f.pfad_anteil(mp1, ed4, mindestens=3)
    assert np.isnan(aus[:2]).all() and np.allclose(aus[2:], 0)            # exakte Gerade: kein Rest
    ed4[4] += 0.07
    assert f.pfad_anteil(mp1, ed4, mindestens=3)[4] == pytest.approx(0.07 * (1 - 1 / 5 - (0.05 - mp1.mean()) ** 2 / (5 * mp1.var())))
    # die Schätzung nutzt nur Ereignisse bis zum jeweiligen (kein Blick voraus)
    assert f.pfad_anteil(mp1, ed4, mindestens=3)[3] == pytest.approx(0)


def test_lauf(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    quelle = Quelle({f.URL_USMPD: usmpd(), f.URL_STIMMUNG: stimmung()})
    p, info, _ = f.lauf(ablage, abruf=quelle, heute=date(2026, 11, 15))
    assert info["erklaerungen"] == 24 and info["stimmungstage"] == 3 and info["juengster_stimmungstag"] == "2026-11-08"
    assert info["tage_seit_stimmung"] == 7
    je = p.groupby("parameter_id").size().to_dict()
    assert je == {"GW1-01": 24, "GW1-02": 4, "WS2-05": 3} and set(p["cik"]) == {0}     # Pfad erst ab 20 vollständigen Ereignissen
    erste = p[(p["parameter_id"] == "GW1-01") & (p["stand"] == "2024-01-31")].iloc[0]
    assert erste["ereignis_zeit"] == pd.Timestamp("2024-01-31 14:00", tz=ET)
    assert erste["verfuegbar_ab"] == pd.Timestamp("2024-02-05 09:30", tz=ET)               # Mittwoch -> dritter Handelstag: Montag
    tag = p[(p["parameter_id"] == "WS2-05") & (p["stand"] == "2026-11-02")].iloc[0]
    assert tag["wert"] == -0.20 and tag["ereignis_zeit"] == pd.Timestamp("2026-11-02 23:59", tz=ET)
    assert tag["verfuegbar_ab"] == pd.Timestamp("2026-11-16 09:30", tz=ET)                 # 14.11. ist ein Samstag
    assert (p["ereignis_zeit"] <= p["verfuegbar_ab"]).all()
    ereignisse = ablage.lies_bereinigt("fedsf_ereignisse")
    assert list(ereignisse.columns) == ["zeit", "tag", "ungeplant", "mp1", "ed4", "pfad"] and len(ereignisse) == 24
    assert len(ablage.lies_bereinigt("fedsf_stimmung")) == 3


def test_fehlende_spalte():
    kaputt = excel({"Statements": pd.DataFrame({"date_time": pd.to_datetime(["2026-01-28 14:00"]), "MP1": [0.0]})})
    with pytest.raises(RuntimeError, match="ED4"):
        f.lies_usmpd(kaputt)
