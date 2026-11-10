from datetime import date

import numpy as np
import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.kern.zustand import Zeitbudget
from daten_offen.quellen import wikipedia as w


class Antwort:
    def __init__(self, daten):
        self._daten = daten

    def json(self):
        return self._daten


class Netz:
    """Wikidata liefert drei Firmen; Aufrufe je Artikel: 100 je Tag, in einer Woche 300 je Tag."""

    def __init__(self):
        self.aufrufe = []

    def hole_json(self, url, params=None, headers=None):
        assert "P5531" in params["query"]
        b = lambda cik, titel: {"cik": {"value": cik}, "titel": {"value": titel}}
        return {"results": {"bindings": [b("0000001000", "Alpha Corp"), b("1000", "Alpha (Doppelt)"),
                                         b("2000", "Beta & Co."), b("3000", "Ohne Daten"), b("x", "Kaputt")]}}

    def hole(self, url, erlaube_404=False, **kw):
        self.aufrufe.append(url)
        if "Ohne_Daten" in url:
            return None
        von, bis = url.rsplit("/", 2)[1:]
        tage = pd.date_range(von, bis, freq="D")
        spitze = (tage >= "2024-03-11") & (tage <= "2024-03-17")
        return Antwort({"items": [{"timestamp": t.strftime("%Y%m%d00"), "views": 300 if s else 100}
                                  for t, s in zip(tage, spitze)]})


def test_zuordnung_bereinigt():
    z = w.lade_zuordnung(Netz(), mindestens=2)
    assert z.to_dict("records") == [{"cik": 1000, "titel": "Alpha (Doppelt)"}, {"cik": 2000, "titel": "Beta & Co."},
                                    {"cik": 3000, "titel": "Ohne Daten"}]
    with pytest.raises(RuntimeError, match="nur 3 Zuordnungen"):
        w.lade_zuordnung(Netz())


def test_lauf_und_kennzahl(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "ANFANG", date(2024, 1, 1))
    ablage, netz = Ablage(tmp_path / "aus"), Netz()
    p, info, _ = w.lauf(ablage, abruf=netz, heute=date(2024, 3, 27), mindestens=2)      # Mittwoch
    assert info["artikel_gelesen"] == 3 and info["firmen_mit_daten"] == 2      # drei Abrufe, einer ohne Daten
    assert any("Beta_%26_Co." in u for u in netz.aufrufe)                                # Titel sicher kodiert
    wochen = ablage.lies_bereinigt(w.WOCHEN)
    alpha = wochen[wochen["cik"] == 1000].set_index("woche")["aufrufe"]
    assert alpha.index.max() == pd.Timestamp("2024-03-18")                               # laufende Woche fehlt
    assert alpha[pd.Timestamp("2024-03-11")] == 2100 and alpha[pd.Timestamp("2024-03-04")] == 700
    z = p[p["cik"] == 1000].set_index("stand")
    assert z.loc["2024-W11", "wert"] == pytest.approx(np.log(3))                         # 2100 gegen Median 700
    assert z.loc["2024-W10", "wert"] == pytest.approx(0)
    assert "2024-W08" not in z.index                                                     # noch keine acht Vorwochen
    assert z.loc["2024-W11", "verfuegbar_ab"] == pd.Timestamp("2024-03-19 09:30", tz=ET)  # Dienstag der Folgewoche
    assert (p["ereignis_zeit"] <= p["verfuegbar_ab"]).all()

    # Folgelauf eine Woche später: je Artikel ein Abruf ab der fehlenden Woche
    netz.aufrufe.clear()
    p2, info2, _ = w.lauf(ablage, abruf=netz, heute=date(2024, 4, 3), mindestens=2)
    assert len(netz.aufrufe) == 3 and all("/20240325/" in u for u in netz.aufrufe if "Ohne_Daten" not in u)
    assert len(p2) == len(p) + 2
    netz.aufrufe.clear()
    w.lauf(ablage, abruf=netz, heute=date(2024, 4, 4), mindestens=2)
    assert [u for u in netz.aufrufe if "Ohne_Daten" not in u] == []                      # nichts Neues zu holen


def test_zeitbudget(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "ANFANG", date(2024, 1, 1))
    ablage = Ablage(tmp_path / "aus")
    _, info, hinweise = w.lauf(ablage, abruf=Netz(), heute=date(2024, 3, 27), mindestens=2, budget=Zeitbudget(0))
    assert info["artikel_gelesen"] == 0 and (ablage.wurzel / "FORTSETZEN__wikipedia").exists()
