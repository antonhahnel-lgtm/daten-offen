from pathlib import Path

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import edgar_ereignisse, edgar_index
from tests.hilfen import baue_submissions_zip


def _et(text):
    return pd.Timestamp(text, tz=ET).tz_convert("UTC")


@pytest.fixture()
def lauf(tmp_path: Path):
    ablage = Ablage(tmp_path / "aus")
    info, schwer, hinweise = edgar_index.lauf(ablage, tmp_path / "arb", 2006,
                                              zip_pfad=baue_submissions_zip(tmp_path / "s.zip"))
    return ablage, info, schwer


def test_verzeichnis(lauf):
    ablage, info, schwer = lauf
    assert schwer == []
    assert info["annahme_zeitzone"] == "ET" and info["trefferquote_et"] == 1.0
    df = ablage.lies_bereinigt("edgar_meldungen").set_index(["cik", "accession"])
    assert info["meldungen"] == len(df) == 24
    assert (df["filing_date"] >= "2006-01-01").all()                      # Meldung von 2005 gefiltert
    assert (1000, "0001000-07-000001") in df.index                        # ältere Zusatzdatei gelesen
    z = df.loc[(1000, "0001000-24-000001")]
    assert z["annahme_utc"] == _et("2024-03-28 16:05:10") and z["verfuegbar_ab"] == _et("2024-04-01 09:30")
    z = df.loc[(1000, "0001000-24-000003")]
    assert z["verfuegbar_ab"] == _et("2024-05-08 07:01")                  # vorbörslich
    z = df.loc[(1000, "0001000-24-000009")]                               # ohne Annahmezeit
    assert bool(z["annahme_geschaetzt"]) and z["verfuegbar_ab"] == _et("2024-07-08 09:30")
    assert (df["annahme_utc"] <= df["verfuegbar_ab"]).all()
    firmen = ablage.lies_bereinigt("edgar_firmen").set_index("cik")
    assert firmen.loc[1000, "tickers"] == "ALPH" and firmen.loc[1000, "sitz_staat"] == "CA"


def test_zeitzone_utc_wird_erkannt():
    # Dieselben Meldungen, aber Annahmezeit in echter UTC: 17:31 ET = 21:31 UTC (Sommer)
    # Entscheidend sind Meldungen zwischen 13:30 und 17:30 ET: In UTC gelesen tragen sie das Tagesdatum,
    # als ET gelesen lägen sie nach Annahmeschluss.
    df = pd.DataFrame({"form": ["8-K"] * 5,
                       "filing_date": pd.to_datetime(["2023-08-01", "2023-08-02", "2023-08-04", "2023-08-07",
                                                      "2023-08-08"]),
                       "annahme_naiv": pd.to_datetime(["2023-08-01 12:30", "2023-08-01 22:00", "2023-08-03 23:15",
                                                       "2023-08-04 21:31", "2023-08-08 20:00"])})
    zone, q_et, q_utc = edgar_index.erkenne_annahme_zeitzone(df)
    assert zone == "UTC" and q_utc == 1.0 and q_et < 1.0


def test_ereignisse(lauf):
    ablage, _, _ = lauf
    p = edgar_ereignisse.lauf(ablage, boersen_schwelle=3)
    je = lambda pid: p[p["parameter_id"] == pid]
    assert sorted(je("WS2-04")["wert"]) == [2.02, 2.02, 2.02, 2.03, 2.05, 3.02, 4.01, 4.02, 5.02, 5.02, 8.01, 9.01]
    assert list(je("UA2-03")["stand"]) == ["0001000-23-000004"]
    assert list(je("UA2-04")["stand"]) == ["0001000-24-000002"]
    assert list(je("IH6-04")["stand"]) == ["0001000-24-000004"]
    assert list(je("GA2-03")["stand"]) == ["0001000-24-000009"]
    assert sorted(je("UA3-03")["wert"]) == [1.0, 2.0, 3.0]
    assert len(je("UA3-04")) == 1
    kd = je("KD1-11")
    assert list(kd["cik"]) == [1000]                                      # Börse als Einreicher ausgeschlossen
    ua = je("UA1-10").set_index("stand")["wert"]
    assert ua["0001000-23-000004"] == pytest.approx(4 + (17 * 60 + 31) / 1440, abs=1e-4)   # Freitag 17:31
    assert "0001000-24-000008" not in set(p["stand"])                     # 8-K/A zählt nicht
    ws = je("WS3-02")
    assert (ws["cik"] == 0).all() and list(ws["wert"]) == [1.0, 1.0, 1.0]
    assert (p["ereignis_zeit"] <= p["verfuegbar_ab"]).all()
    assert sorted(x.name for x in ablage.parameter.iterdir()) == [
        "parameter__edgar_ereignisse__2023.parquet", "parameter__edgar_ereignisse__2024.parquet"]


def test_delisting_arten():
    t = lambda s: pd.Timestamp(s, tz="UTC")
    meldungen = pd.DataFrame({
        "cik": [1, 1, 2, 3, 4, 5, 6],
        "accession": ["a", "b", "c", "d", "e", "f", "g"],
        "form": ["8-K", "8-K", "15-12G/A", "DEFM14A", "SC 14D9", "SC TO-T", "PREM14A"],
        "items": ["1.03,9.01", "3.01", None, None, None, None, None],
        "annahme_utc": [t("2024-05-01 14:00")] * 7,
        "verfuegbar_ab": [t("2024-05-01 14:00")] * 7,
    })
    p = edgar_ereignisse.baue_parameter(meldungen)
    kd = p[p["parameter_id"] == "KD1-11"].set_index("stand")["wert"].to_dict()
    assert kd == {"a": 3.0, "b": 5.0, "c": 2.0, "d": 4.0, "e": 4.0, "g": 4.0}   # SC TO-T nicht zugeordnet
