import numpy as np
import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import fred as f


def b(datum, wert, von="2020-01-01", bis=f.OFFEN):
    return {"realtime_start": von, "realtime_end": bis, "date": datum, "value": str(wert)}


def monate(start, n):
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, periods=n, freq="MS")]


def indpro():
    # 300 Monate auf exaktem quadratischem Trend (Lücke 0), veröffentlicht am 15.01.2000;
    # der 301. Monat erscheint am 15.02.2000 mit +5 % über Trend und wird am 15.03.2000 auf Trend revidiert.
    t = np.arange(301) / 120.0
    trend = np.exp(3.0 + 0.2 * t + 0.01 * t * t)
    tage = monate("1975-01-01", 301)
    zeilen = [b(tage[i], trend[i], von="2000-01-15") for i in range(300)]
    zeilen.append(b(tage[300], trend[300] * 1.05, von="2000-02-15", bis="2000-03-14"))
    zeilen.append(b(tage[300], trend[300], von="2000-03-15"))
    return zeilen


def cpi():
    tage = monate("1998-01-01", 26)
    werte = [100 * 1.002 ** i for i in range(25)] + [100 * 1.002 ** 24 * 1.012]   # letzter Monat +1,2 %
    return [b(tage[i], werte[i], von="2000-02-10") for i in range(25)] + [b(tage[25], werte[25], von="2000-03-17")]


class Abruf:
    def __init__(self):
        self.aufrufe = []
        self.reihen = {
            "DGS10": [b("2024-03-27", 4.20), b("2024-03-28", 4.25), b("2024-04-01", "."), b("2024-04-02", 4.30)],
            "DGS3MO": [b("2024-03-27", 5.40), b("2024-03-28", 5.45), b("2024-04-02", 5.42)],
            "DFEDTAR": [b("2008-12-12", 1.0), b("2008-12-15", 1.0), b("2008-12-16", 9.9)],
            "DFEDTARU": [b("2008-12-16", 0.25), b("2008-12-17", 0.25), b("2015-12-17", 0.5)],
            "DCOILWTICO": [b("2024-01-30", 78.0), b("2024-01-31", 80.0), b("2024-02-29", 84.0), b("2024-03-15", 90.0)],
            "INDPRO": indpro(), "CPIAUCSL": cpi(),
        }

    def hole_json(self, url, params=None):
        self.aufrufe.append((url, dict(params)))
        assert params["api_key"] == "geheim" and params["file_type"] == "json"
        if url.endswith("series/observations"):
            alle = self.reihen[params["series_id"]]
            teil = alle[params["offset"]:params["offset"] + params["limit"]]
            return {"count": len(alle), "observations": teil}
        if url.endswith("/releases"):
            return {"releases": [{"id": 101, "name": "FOMC Press Release"}, {"id": 50, "name": "Employment Situation"}]}
        if url.endswith("release/dates"):
            assert params["include_release_dates_with_no_data"] == "true"
            return {"release_dates": [{"date": "2024-03-20"}, {"date": "2027-01-27"}] if params["release_id"] == 101
                    else [{"date": "2024-04-05"}]}
        raise AssertionError(url)


@pytest.fixture(scope="module")
def ergebnis(tmp_path_factory):
    abruf = Abruf()
    ablage = Ablage(tmp_path_factory.mktemp("fred") / "aus")
    p, info, hinweise = f.lauf(ablage, f.Fred(abruf=abruf, schluessel="geheim"))
    return p, info, hinweise, abruf, ablage


def je(p, pid):
    return p[p["parameter_id"] == pid].set_index("stand")


def test_zinsen(ergebnis):
    p = ergebnis[0]
    z = je(p, "GW2-01")
    assert z.loc["2024-03-27", "wert"] == pytest.approx(-1.20) and "2024-04-01" not in z.index
    assert z.loc["2024-03-28", "verfuegbar_ab"] == pd.Timestamp("2024-04-01 09:30", tz=ET)   # Karfreitag dazwischen
    assert je(p, "GW2-03").loc["2024-04-02", "wert"] == 5.42
    assert (p["cik"] == 0).all()


def test_zinsregime(ergebnis):
    z = je(ergebnis[0], "GW1-06")
    assert z["wert"].to_dict() == {"2008-12-16": -0.75, "2015-12-17": 0.25}     # Übergang Zielsatz -> Spanne


def test_oel(ergebnis):
    z = je(ergebnis[0], "GW3-01")
    assert list(z.index) == ["2024-02"]                                          # März noch nicht abgeschlossen
    assert z.loc["2024-02", "wert"] == pytest.approx(np.log(84 / 80))
    assert z.loc["2024-02", "verfuegbar_ab"] == pd.Timestamp("2024-03-01 09:30", tz=ET)


def test_produktionsluecke_mit_datenstand(ergebnis):
    z = je(ergebnis[0], "GW2-04")
    assert list(z.index) == ["2000-01-15", "2000-02-15", "2000-03-15"]
    assert z.loc["2000-01-15", "wert"] == pytest.approx(0, abs=1e-9)
    assert 0.03 < z.loc["2000-02-15", "wert"] < 0.05           # +5 % Ausreißer, vom Trend teils aufgefangen
    assert z.loc["2000-03-15", "wert"] == pytest.approx(0, abs=1e-9)             # Revision als neue Zeile
    assert z.loc["2000-02-15", "verfuegbar_ab"] == pd.Timestamp("2000-02-15 09:15", tz=ET)
    assert z.loc["2000-02-15", "ereignis_zeit"] == pd.Timestamp("2000-01-31 00:00", tz=ET)


def test_inflation(ergebnis):
    z = je(ergebnis[0], "GW2-06")
    assert z.loc["2000-02-10", "wert"] == pytest.approx(0, abs=1e-12)
    assert z.loc["2000-03-17", "wert"] == pytest.approx((1.002 ** 11 * 1.012) - 1.002 ** 12)
    assert z.loc["2000-03-17", "verfuegbar_ab"] == pd.Timestamp("2000-03-17 08:30", tz=ET)


def test_inflation_mit_luecke():
    # Oktober 2025 fehlt (Shutdown): November wird gegen September gerechnet, Oktober 2026 entfällt.
    tage = [t for t in monate("2024-01-01", 34) if t != "2025-10-01"]
    werte = {t: 100 * 1.003 ** i for i, t in enumerate(monate("2024-01-01", 34))}
    zeilen = [{"datum": pd.Timestamp(t), "wert": werte[t], "von": pd.Timestamp(t) + pd.Timedelta(days=45),
               "bis": pd.Timestamp("2262-01-01")} for t in tage]
    z = f.inflationsaenderung(pd.DataFrame(zeilen), ab="2025-01-01").set_index("stand")
    nov = pd.Timestamp("2025-11-01") + pd.Timedelta(days=45)
    assert nov.strftime("%Y-%m-%d") in z.index                                  # früher: alle Folgestände verloren
    assert z.loc[nov.strftime("%Y-%m-%d"), "wert"] == pytest.approx(0, abs=1e-12)
    okt26 = (pd.Timestamp("2026-10-01") + pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    assert okt26 not in z.index                                                 # Vorjahresmonat fehlt
    assert len(z) == 19                     # 22 Stände ab 2025, ohne Dez. 2024/Jan. 2025 (kurz) und Okt. 2026


def test_termine(ergebnis):
    p, info, hinweise = ergebnis[0], ergebnis[1], ergebnis[2]
    z = je(p, "GW1-05")
    assert z["wert"].to_dict() == {"2024-03-20": 1.0, "2027-01-27": 1.0, "2024-04-05": 2.0}
    assert z.loc["2024-03-20", "verfuegbar_ab"] == pd.Timestamp("2024-02-21 09:30", tz=ET)
    assert hinweise == ["Termine nicht gefunden für: Consumer Price Index"]
    assert info["termine"] == 3


def test_stande_und_ablage(ergebnis):
    abruf, ablage = ergebnis[3], ergebnis[4]
    mit_staenden = {p["series_id"] for u, p in abruf.aufrufe if u.endswith("observations") and "realtime_start" in p}
    assert mit_staenden == {"INDPRO", "CPIAUCSL"}
    assert len(ablage.lies_bereinigt("fred_indpro")) == 302


def test_ohne_schluessel(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        f.Fred(abruf=Abruf())
