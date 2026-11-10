from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import edgar_xbrl as x
from tests.hilfen import baue_companyfacts_zip, musterfirma


@pytest.fixture(scope="module")
def berichte():
    return pd.DataFrame(x.berichtszeilen(42, musterfirma().json(42))).set_index("accn")


@pytest.fixture(scope="module")
def parameter(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("xbrl")
    ablage = Ablage(tmp / "aus")
    p, info, hinweise = x.lauf(ablage, tmp / "arb", zip_pfad=baue_companyfacts_zip(tmp / "cf.zip"))
    return p, info, hinweise, ablage


def wert(p, pid, stand):
    t = p[(p["parameter_id"] == pid) & (p["stand"] == stand)]
    assert len(t) == 1, f"{pid}/{stand}: {len(t)} Zeilen"
    return t["wert"].iloc[0]


def fehlt(p, pid, stand):
    return p[(p["parameter_id"] == pid) & (p["stand"] == stand)].empty


def test_zeitraumklasse():
    assert x.zeitraumklasse("2023-01-01", "2023-03-31") == "Q"
    assert x.zeitraumklasse("2023-01-01", "2023-06-30") == "H"
    assert x.zeitraumklasse("2023-01-01", "2023-09-30") == "T"
    assert x.zeitraumklasse("2023-01-01", "2023-12-31") == "Y"
    assert x.zeitraumklasse(None, "2023-12-31") == "I"
    assert x.zeitraumklasse("2023-01-01", "2023-01-31") == ""


def test_berichtszeile_quartal(berichte):
    z = berichte.loc["Q-2023-2"]
    assert z["period_end"] == "2023-06-30" and z["form"] == "10-Q"
    assert z["revenue"] == 125 and z["revenue_q"] == 1 and z["revenue_py"] == 120    # Quartal vor Halbjahr
    assert z["op_cf"] == 14 and z["op_cf_q"] == 2 and z["op_cf_py"] == 12            # Kapitalfluss nur aufgelaufen
    assert z["assets"] == 1000                                                      # nicht der Vergleichswert 940
    assert z["cash"] == 50 and z["sti"] == 30
    assert z["shares_deckblatt"] == 1100


def test_berichtszeile_jahr(berichte):
    z = berichte.loc["K-2023"]
    assert z["revenue"] == 480 and z["revenue_q"] == 4 and z["revenue_py"] == 450
    assert z["net_income"] == 68 and z["op_cf"] == 36 and z["gross_profit"] == 200 and z["debt"] == 140
    assert len(berichte) == 12


def test_einzelquartale_und_zwoelf_monate():
    tage = np.array([90, 181, 273, 365, 455, 546])
    aufgelaufen = np.array([5.0, 12, 21, 32, 6, 14])
    q = np.array([1.0, 2, 3, 4, 1, 2])
    einzel = x._einzelquartale(tage, aufgelaufen, q)
    assert list(einzel) == [5, 7, 9, 11, 6, 8]
    assert list(x._zwoelf_monate(tage, einzel, aufgelaufen, q))[3:] == [32, 33, 34]
    # fehlt ein Vorquartal, bleibt der Wert leer statt falsch
    assert np.isnan(x._einzelquartale(np.array([181, 273]), np.array([12.0, 21]), np.array([2.0, 3]))).all()


def test_sue(parameter):
    p = parameter[0]
    # Saisonale Differenzen 2022: 1, 3, −1, 5; 2023: 3, 1, 5, −1 (viertes Quartal aus Jahr minus neun Monate)
    assert wert(p, "UA1-01", "Q-2023-1") == pytest.approx(3 / np.std([1, 3, -1, 5], ddof=1))
    assert wert(p, "UA1-01", "Q-2023-2") == pytest.approx(1 / np.std([1, 3, -1, 5, 3], ddof=1))
    assert wert(p, "UA1-01", "K-2023") == pytest.approx(-1 / np.std([1, 3, -1, 5, 3, 1, 5], ddof=1))
    assert fehlt(p, "UA1-01", "Q-2022-4") and fehlt(p, "UA1-01", "K-2022")           # zu wenig Vorgeschichte


def test_zahlenlage_und_bilanz(parameter):
    p = parameter[0]
    assert wert(p, "UA1-02", "Q-2023-1") == 1                # Umsatz +9 %, Gewinn, Cashflow positiv
    assert wert(p, "UA1-02", "Q-2022-3") == 0                # Umsatz −10 %, aber Gewinn: gemischt
    assert wert(p, "UA1-02", "Q-2021-1") == 0                # ohne Vorjahresumsatz: Gewinn bekannt, gemischt
    assert wert(p, "UA1-02", "V-1") == 0 and wert(p, "UA1-02", "B-1") == 0   # Bank: +16 % Ertrag, Gewinn 0
    assert wert(p, "UA1-03", "Q-2023-2") == pytest.approx((64 - 34) / 1000)
    assert wert(p, "UA1-04", "Q-2023-2") == pytest.approx(34 / 1000)
    assert wert(p, "UA1-03", "K-2023") == pytest.approx((68 - 36) / 1040)
    assert wert(p, "UA1-05", "Q-2023-2") == pytest.approx(1000 / 900 - 1)
    assert fehlt(p, "UA1-05", "Q-2021-2")
    assert wert(p, "GA1-02", "Q-2023-2") == 20 and wert(p, "GA1-02", "K-2023") == 20


def test_reichweite_und_aktien(parameter):
    p, info = parameter[0], parameter[1]
    assert wert(p, "UA1-07", "V-1") == pytest.approx(5.0)    # 100 Kasse / 20 Abfluss je Quartal
    assert fehlt(p, "UA1-07", "Q-2023-2")                    # kein Mittelabfluss
    assert wert(p, "UA3-01", "Q-2023-2") == pytest.approx(0.10)
    assert fehlt(p, "UA3-01", "Q-2023-3") and fehlt(p, "UA3-01", "K-2023")   # Faktor 3,5: Split-Verdacht
    assert info["split_verdacht"] == 2


def test_jahreskennzahlen(parameter):
    p = parameter[0]
    dsri = (100 / 480) / (90 / 450)
    gmi = (180 / 450) / (200 / 480)
    aqi = (1 - (450 + 320) / 1040) / (1 - (400 + 300) / 940)
    sgi = 480 / 450
    depi = (20 / (20 + 300)) / (22 / (22 + 320))
    sgai = (92 / 480) / (90 / 450)
    tata = (68 - 36) / 1040
    lvgi = ((140 + 210) / 1040) / ((150 + 200) / 940)
    m = -4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
    assert wert(p, "UA2-01", "K-2023") == pytest.approx(m)
    assert fehlt(p, "UA2-01", "K-2022") and fehlt(p, "UA2-01", "Q-2023-2")
    # Piotroski 2023: Gewinn, Cashflow, Rendite gestiegen, Cashflow < Gewinn (0), Verschuldung gesunken,
    # Liquidität gestiegen, Aktienzahl gestiegen (0), Marge gestiegen, Umschlag gesunken (0) = 6
    assert wert(p, "UA1-06", "K-2023") == 6
    assert fehlt(p, "UA1-06", "K-2022")
    assert wert(p, "GA1-06", "K-2022") == pytest.approx((90 / 0.25) / 940)
    assert wert(p, "GA1-06", "K-2023") == pytest.approx(((90 / 0.25) * 0.85 ** (365 / 365.25) + 92) / 1040)
    assert wert(p, "GA3-03", "K-2023") == pytest.approx(0.2)
    assert wert(p, "PR2-03", "K-2023") == pytest.approx(0.2) and wert(p, "PR2-03", "K-2022") == pytest.approx(0.2)


def test_bank_und_ablage(parameter):
    p, info, hinweise, ablage = parameter
    b = ablage.lies_bereinigt(x.TABELLE).set_index("accn")
    assert b.loc["B-1", "revenue"] == 100 and b.loc["B-1", "revenue_py"] == 85 and b.loc["B-1", "rev_src"] == "bank"
    assert info["quelldateien"] == 4 and info["firmen"] == 3            # leere und kaputte Datei übergangen
    assert any("Meldungsverzeichnis fehlt" in h for h in hinweise)
    assert (p["ereignis_zeit"] <= p["verfuegbar_ab"]).all()


def test_stichtag_aus_verzeichnis():
    b = pd.DataFrame(x.berichtszeilen(42, musterfirma().json(42)))
    annahme = pd.Timestamp("2023-08-09 16:30", tz=ET).tz_convert("UTC")
    meld = pd.DataFrame({"accession": ["Q-2023-2"], "annahme_utc": [annahme],
                         "verfuegbar_ab": [pd.Timestamp("2023-08-10 09:30", tz=ET).tz_convert("UTC")]})
    p, _ = x.baue_parameter(b, meld)
    z = p[(p["parameter_id"] == "UA1-02")].set_index("stand")
    assert z.loc["Q-2023-2", "verfuegbar_ab"] == pd.Timestamp("2023-08-10 09:30", tz=ET)
    # ohne Eintrag im Verzeichnis: Einreichungstag 17:30 ET, also nächster Handelstag
    assert z.loc["Q-2023-1", "verfuegbar_ab"] == pd.Timestamp("2023-05-11 09:30", tz=ET)
    assert z.loc["Q-2023-2", "ereignis_zeit"] == pd.Timestamp("2023-06-30 00:00", tz=ET)


def test_aktienzahl_zum_deckblattdatum_verschiebt_das_periodenende_nicht():
    from tests.hilfen import Fakten
    f = Fakten()
    f.plus("Revenues", 100, "A", "10-Q", "2024-05-10", "2024-03-31", start="2024-01-01")
    f.plus("Assets", 500, "A", "10-Q", "2024-05-10", "2024-03-31")
    f.plus("CommonStockSharesOutstanding", 900, "A", "10-Q", "2024-05-10", "2024-05-02", einheit="shares")
    f.plus("WeightedAverageNumberOfSharesOutstandingBasic", 880, "A", "10-Q", "2024-05-10", "2024-03-31",
           start="2024-01-01", einheit="shares")
    z = x.berichtszeilen(7, f.json(7))[0]
    assert z["period_end"] == "2024-03-31" and z["revenue"] == 100 and z["assets"] == 500
    assert z["shares"] == 880                      # kein Stichtagswert zum Periodenende: Durchschnitt als Ersatz


def test_whited_wu_mit_branchenwachstum_des_vorjahres():
    # drei Firmen derselben Branche (SIC 283x) mit den Zahlen der Musterfirma
    js = musterfirma().json(42)
    b = pd.concat([pd.DataFrame(x.berichtszeilen(c, js)).assign(accn=lambda d, c=c: d["accn"] + f"-{c}")
                   for c in (42, 51, 52)], ignore_index=True)
    firmen = pd.DataFrame({"cik": [42, 51, 52, 99], "sic": ["2834", "2836", "2833", None]})
    p, _ = x.baue_parameter(b, pd.DataFrame(), firmen)
    ww = p[p["parameter_id"] == "GW1-04"].set_index("stand")["wert"]
    branche_2022 = 450 / 400 - 1                       # Umsatzwachstum der Branche im Vorjahr
    erwartet = (-0.091 * (68 + 22) / 1040 - 0.062 * 0 + 0.021 * 140 / 1040 - 0.044 * np.log(1040 / 1e6)
                + 0.102 * branche_2022 - 0.035 * (480 / 450 - 1))
    assert ww["K-2023-42"] == pytest.approx(erwartet)
    assert list(ww.index) == ["K-2023-42", "K-2023-51", "K-2023-52"]      # 2022 fehlt das Branchenwachstum 2021
    # ohne Branchenschlüssel oder mit zu wenigen Firmen entsteht kein Wert
    assert x.baue_parameter(b, pd.DataFrame(), None)[0].query("parameter_id == 'GW1-04'").empty
    zwei = b[b["cik"].isin([42, 51])]
    assert x.baue_parameter(zwei, pd.DataFrame(), firmen)[0].query("parameter_id == 'GW1-04'").empty
