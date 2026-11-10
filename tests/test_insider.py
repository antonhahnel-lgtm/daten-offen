from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET, handelbar_ab_serie
from daten_offen.quellen import edgar_insider as ins
from tests.hilfen import baue_form345_zip


def _et(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz=ET).tz_convert("UTC")


@pytest.fixture()
def daten(tmp_path: Path):
    sub = [
        ["A-1", "05-MAR-2024", "", "4", 1000, "ALPHA", "alph", "0"],
        ["A-2", "06-MAR-2024", "", "4", 1000, "ALPHA", "ALPH", ""],
        ["A-3", "2024-03-26", "", "4", 1000, "ALPHA", "ALPH", "1"],
        ["S-1", "21-MAR-2024", "", "4", 1000, "ALPHA", "ALPH", "0"],
        ["S-2", "21-MAR-2024", "", "4", 1000, "ALPHA", "ALPH", "0"],
        ["A-1A", "10-MAR-2024", "", "4/A", 1000, "ALPHA", "ALPH", "0"],
        ["X-1", "01-MAR-2024", "", "4", 1000, "ALPHA", "ALPH", "0"],   # Kauftag nach Einreichung: unplausibel
        ["B-1", "29-MAR-2024", "", "4", 3000, "BETA", "BETA", "0"],
    ]
    own = [
        ["A-1", 2001, "CEO PERSON", "Director,Officer", "Chief Executive Officer"],
        ["A-2", 2002, "DIR PERSON", "Director", ""],
        ["A-2", 2099, "ZWEITE PERSON", "Other", ""],
        ["A-3", 2003, "FONDS LP", "TenPercentOwner", ""],
        ["S-1", 2004, "SVP PERSON", "Officer", "SVP Sales"],
        ["S-2", 2001, "CEO PERSON", "Director,Officer", "Chief Executive Officer"],
        ["A-1A", 2001, "CEO PERSON", "Director,Officer", "Chief Executive Officer"],
        ["X-1", 2004, "SVP PERSON", "Officer", "SVP Sales"],
        ["B-1", 2005, "ANDERE PERSON", "Director", ""],
    ]
    tr = [
        ["A-1", 1, "Common", "04-MAR-2024", "P", 1000, 10, "A", 5000, "D"],
        ["A-1", 2, "Common", "04-MAR-2024", "A", 300, 0, "A", 5300, "D"],      # Zuteilung, kein Kauf
        ["A-2", 3, "Common", "05-MAR-2024", "P", 2000, 10, "A", 2000, "D"],
        ["A-2", 4, "Common", "05-MAR-2024", "P", 1000, 11, "A", 3000, "D"],
        ["A-3", 5, "Common", "25-MAR-2024", "P", 10000, 12, "A", 110000, "I"],
        ["S-1", 6, "Common", "20-MAR-2024", "S", 5000, 12, "D", 1000, "D"],
        ["S-2", 7, "Common", "20-MAR-2024", "S", 500, 12, "D", 4500, "D"],
        ["A-1A", 8, "Common", "04-MAR-2024", "P", 1000, 10, "A", 5000, "D"],   # Nachtrag wiederholt A-1
        ["X-1", 9, "Common", "15-MAR-2024", "P", 100, 10, "A", 100, "D"],
        ["B-1", 10, "Common", "28-MAR-2024", "P", 100, 10, "A", 1100, "D"],
    ]
    # Vorgeschichte: Direktor handelt jeden März (Routine), CEO in wechselnden Monaten (opportunistisch)
    sub_alt, own_alt, tr_alt = [], [], []
    vorgeschichte = [("H-1", 2002, "15-MAR-2021"), ("H-2", 2002, "15-MAR-2022"), ("H-3", 2002, "15-MAR-2023"),
                     ("H-4", 2001, "15-JAN-2021"), ("H-5", 2001, "15-FEB-2022"), ("H-6", 2001, "15-JUN-2023")]
    for i, (acc, person, tag) in enumerate(vorgeschichte):
        sub_alt.append([acc, tag, "", "4", 1000, "ALPHA", "ALPH", ""])
        own_alt.append([acc, person, "P", "Director", ""])
        tr_alt.append([acc, 100 + i, "Common", tag, "P", 100, 10, "A", 1000 + i, "D"])
    ablage = Ablage(tmp_path / "aus")
    for teil, (s, o, t) in {"2023q4": (sub_alt, own_alt, tr_alt), "2024q1": (sub, own, tr)}.items():
        z = baue_form345_zip(tmp_path / f"{teil}.zip", s, o, t)
        ablage.schreibe_bereinigt(ins.TABELLE, teil, ins.lies_quartal(z, teil))
    annahmen = {"A-1": "2024-03-05 17:00", "A-2": "2024-03-06 10:00", "A-3": "2024-03-26 12:00",
                "S-1": "2024-03-21 09:00", "S-2": "2024-03-21 09:05"}
    meld = pd.DataFrame({"cik": 1000, "accession": list(annahmen), "form": "4", "items": None,
                         "annahme_utc": [_et(v) for v in annahmen.values()]})
    meld = pd.concat([meld, pd.DataFrame({"cik": [1000], "accession": ["K-1"], "form": ["8-K"], "items": ["2.02,9.01"],
                                          "annahme_utc": [_et("2024-02-01 20:00")]})], ignore_index=True)
    meld["annahme_utc"] = meld["annahme_utc"].astype("datetime64[us, UTC]")
    meld["verfuegbar_ab"] = handelbar_ab_serie(meld["annahme_utc"])
    meld["annahme_geschaetzt"] = False
    roh = ablage.lies_bereinigt(ins.TABELLE)
    df, info = ins.bereinige(roh, meld)
    return df, info, ins.baue_parameter(df, meld), meld


def wert(p, pid, stand):
    t = p[(p["parameter_id"] == pid) & (p["stand"] == stand)]
    assert len(t) == 1, f"{pid}/{stand}: {len(t)} Zeilen"
    return t["wert"].iloc[0]


def fehlt(p, pid, stand):
    return p[(p["parameter_id"] == pid) & (p["stand"] == stand)].empty


def test_bereinigung(daten):
    df, info, _, _ = daten
    assert info["nachtrags_dubletten"] == 1
    assert info["unplausible_daten"] == 1
    assert "A-1A" not in set(df["accession"]) and "X-1" not in set(df["accession"])
    a2 = df[df["accession"] == "A-2"]
    assert set(a2["owner_cik"]) == {2002} and a2["n_meldende"].iloc[0] == 2
    assert df.loc[df["accession"] == "A-1", "issuer_ticker"].iloc[0] == "ALPH"
    assert (df["ereignis_zeit"] <= df["verfuegbar_ab"]).all()


def test_verfuegbarkeit(daten):
    df, _, p, _ = daten
    z = p[(p["parameter_id"] == "IH1-03")].set_index("stand")["verfuegbar_ab"]
    assert z["A-1"] == _et("2024-03-06 09:30")      # Annahme nach Börsenschluss
    assert z["A-2"] == _et("2024-03-06 10:00")      # Annahme im Handel
    assert z["H-3"] == _et("2023-03-16 09:30")      # ohne Annahmezeit: nächster Handelstag
    assert z["B-1"] == _et("2024-04-01 09:30")      # Karfreitag 29.03.2024 ist kein Handelstag


def test_cluster_und_quote(daten):
    _, _, p, _ = daten
    assert wert(p, "IH1-01", "A-1") == 1 and wert(p, "IH1-18", "A-1") == 0
    assert wert(p, "IH1-01", "A-2") == 2 and wert(p, "IH1-18", "A-2") == 1
    # A-3 ist ein 10-%-Eigner ohne Amt: zählt selbst nicht, sieht aber die zwei firmeneigenen Käufer
    assert wert(p, "IH1-01", "A-3") == 2 and wert(p, "IH1-18", "A-3") == 0
    assert wert(p, "IH1-06", "A-1") == 1.0 and wert(p, "IH1-06", "A-2") == 1.0
    assert wert(p, "IH1-06", "A-3") == pytest.approx((161000 - 66000) / (161000 + 66000))


def test_einzelwerte(daten):
    _, _, p, _ = daten
    assert [wert(p, "IH1-02", a) for a in ("A-1", "A-2", "A-3")] == [4, 2, 1]
    assert [wert(p, "IH1-03", a) for a in ("A-1", "A-2", "A-3")] == [10000, 31000, 120000]
    assert wert(p, "IH1-04", "A-2") == 1 and wert(p, "IH1-04", "A-1") == 0 and fehlt(p, "IH1-04", "A-3")
    assert wert(p, "IH1-07", "A-1") == 0 and wert(p, "IH1-07", "A-3") == 1 and fehlt(p, "IH1-07", "A-2")
    assert [wert(p, "IH1-09", a) for a in ("A-1", "A-2", "A-3")] == [1, 1, 1]
    assert wert(p, "IH1-10", "A-1") == pytest.approx(0.25) and fehlt(p, "IH1-10", "A-2")
    assert wert(p, "IH1-10", "A-3") == pytest.approx(0.1)
    assert wert(p, "IH1-05", "A-1") == 32 and wert(p, "IH1-05", "A-3") == 53
    assert wert(p, "WS3-01", "A-1") == pytest.approx(1 + 17 / 24, abs=1e-4)
    assert wert(p, "WS3-01", "A-2") == pytest.approx(2 + 10 / 24, abs=1e-4)
    assert fehlt(p, "WS3-01", "H-1")


def test_verkauf_nach_kauf(daten):
    _, _, p, _ = daten
    t = p[p["parameter_id"] == "IH1-17"]
    assert list(t["stand"]) == ["S-2"]
    assert t["verfuegbar_ab"].iloc[0] == _et("2024-03-21 09:05")   # vorbörsliche Annahme zählt selbst


def test_marktanteil(daten):
    _, _, p, _ = daten
    t = p[p["parameter_id"] == "IH1-16"]
    assert list(t["stand"]) == ["2024-03"] and (t["cik"] == 0).all()
    assert t["wert"].iloc[0] == pytest.approx(2 / 3)
    assert t["verfuegbar_ab"].iloc[0] == _et("2024-04-01 09:30")


def test_quartale():
    assert ins.quartale(2023, date(2024, 7, 1))[-1] == (2024, 2)
    assert ins.quartale(2024, date(2024, 6, 30)) == [(2024, 1)]


def test_pflichtspalten(tmp_path):
    import zipfile
    z = tmp_path / "kaputt.zip"
    with zipfile.ZipFile(z, "w") as a:
        a.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\tFILING_DATE\n")
        a.writestr("REPORTINGOWNER.tsv", "ACCESSION_NUMBER\n")
        a.writestr("NONDERIV_TRANS.tsv", "ACCESSION_NUMBER\n")
    with pytest.raises(KeyError, match="Pflichtspalten fehlen"):
        ins.lies_quartal(z, "x")


def test_verkauf_aus_ausuebung_zaehlt_anteilig(tmp_path):
    sub = [["K-1", "02-APR-2024", "", "4", 7000, "GAMMA", "GAM", "0"],
           ["V-1", "01-APR-2024", "", "4", 7000, "GAMMA", "GAM", "0"]]
    own = [["K-1", 7001, "KAEUFER", "Director", ""], ["V-1", 7002, "VERKAEUFER", "Officer", "CTO"]]
    tr = [["K-1", 1, "Common", "01-APR-2024", "P", 1000, 10, "A", 2000, "D"],
          ["V-1", 2, "Common", "28-MAR-2024", "M", 4000, 1, "A", 4000, "D"],
          ["V-1", 3, "Common", "28-MAR-2024", "S", 4000, 10, "D", 0, "D"]]
    z = baue_form345_zip(tmp_path / "g.zip", sub, own, tr)
    df, _ = ins.bereinige(ins.lies_quartal(z, "2024q2"), pd.DataFrame())
    p = ins.baue_parameter(df, pd.DataFrame())
    # Verkauf 40.000 $ aus einer Meldung mit Ausübung zählt zu 25 %: (10.000 − 10.000) / (10.000 + 10.000) = 0
    assert wert(p, "IH1-06", "K-1") == pytest.approx(0.0)


def test_links_aus_seite():
    html = ('<a href="/files/structureddata/data/insider-transactions-data-sets/2026q2_form345.zip">x</a>'
            '<a href="https://www.sec.gov/files/dera/data/form-345/2006q1_form345.zip">y</a>')
    links = ins.links_aus_seite(html)
    assert links["2026q2"].startswith("https://www.sec.gov/files/structureddata/")
    assert links["2006q1"] == "https://www.sec.gov/files/dera/data/form-345/2006q1_form345.zip"
