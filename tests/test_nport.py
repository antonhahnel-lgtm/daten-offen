import zipfile
from datetime import date

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import edgar_nport as n
from tests.hilfen import tsv

SUB = ["ACCESSION_NUMBER", "FILING_DATE", "FILE_NUM", "SUB_TYPE", "REPORT_ENDING_PERIOD", "REPORT_DATE", "IS_LAST_FILING"]
INFO = ["ACCESSION_NUMBER", "SERIES_NAME", "SERIES_ID", "TOTAL_ASSETS", "NET_ASSETS"] + \
       [f"{a}_FLOW_MON{m}" for a in ("SALES", "REINVESTMENT", "REDEMPTION") for m in (1, 2, 3)]
POS = ["ACCESSION_NUMBER", "HOLDING_ID", "ISSUER_NAME", "ISSUER_CUSIP", "BALANCE", "UNIT", "CURRENCY_VALUE", "PERCENTAGE",
       "PAYOFF_PROFILE", "ASSET_CAT"]
KENN = ["HOLDING_ID", "IDENTIFIERS_ID", "IDENTIFIER_ISIN", "IDENTIFIER_TICKER"]
A, A2, B, C, X = "111111111", "111111112", "222222222", "333333333", "999999999"


def baue_zip(pfad, meldungen, fonds, positionen, kennungen=()):
    """meldungen: (acc, eingereicht, art, berichtstag); fonds: (acc, serie, vermoegen, zufluss je Monat, abfluss je Monat);
    positionen: (acc, holding_id, cusip, stueck, art, profil)."""
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SUBMISSION.tsv", tsv(SUB, [[a, e, "811-1", art, "", b, "N"] for a, e, art, b in meldungen]))
        z.writestr("FUND_REPORTED_INFO.tsv", tsv(INFO, [[a, "Fonds", s, v, v] + ([zu] * 3 if zu is not None else [""] * 3) + ["0"] * 3
                                                      + ([ab] * 3 if ab is not None else [""] * 3) for a, s, v, zu, ab in fonds]))
        z.writestr("FUND_REPORTED_HOLDING.tsv", tsv(POS, [[a, h, "NAME", c, s, "NS", "1", "0.01", profil, art]
                                                         for a, h, c, s, art, profil in positionen]))
        z.writestr("IDENTIFIERS.tsv", tsv(KENN, [[h, i, isin, ""] for i, (h, isin) in enumerate(kennungen)]))
    return pfad


@pytest.fixture()
def lage(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("ftd_wertpapiere", "alle", pd.DataFrame({
        "cusip": [A, A2, B, C, X], "cik": pd.array([10, 10, 11, 12, pd.NA], dtype="Int64"),
        "konfidenz": [0.98, 0.98, 0.98, 1.0, 0.0], "art": ["kuerzel_name"] * 4 + ["keiner"], "stamm": [True] * 5}))
    ordner = tmp_path / "nport"
    ordner.mkdir()
    # eingereicht im zweiten Quartal 2026: Fonds 1 meldet den April
    baue_zip(ordner / "2026q2_nport.zip",
             [("F1", "20-JUN-2026", "NPORT-P", "30-APR-2026")],
             [("F1", "S1", "1000", "100", "50")],                                    # Fluss 3 × 50 / 1000 = +15 %
             [("F1", "1", A, "100", "EC", "Long"), ("F1", "2", B, "50", "EC", "Long"),
              ("F1", "3", "N/A", "10", "EC", "Long"),                                # CUSIP nur in der ISIN
              ("F1", "4", "000000000", "5", "EC", "Long"),                            # ausländische ISIN: keine Zuordnung
              ("F1", "5", A, "40", "EC", "Short"), ("F1", "6", B, "1000", "DBT", "Long")],
             [("3", "US3333333336"), ("4", "GB0000000001")])
    # eingereicht im dritten Quartal: Fonds 2 und 4 melden den Juni, Fonds 3 den Mai zu spät; Nachtrag zählt nicht
    baue_zip(ordner / "2026q3_nport.zip",
             [("F2", "25-AUG-2026", "NPORT-P", "30-JUN-2026"), ("F2A", "28-AUG-2026", "NPORT-P/A", "30-JUN-2026"),
              ("F3", "05-SEP-2026", "NPORT-P", "31-MAY-2026"), ("F4", "10-JUL-2026", "NPORT-P", "30-JUN-2026"),
              ("F6", "20-SEP-2026", "NPORT-P", "31-JUL-2026")],
             [("F2", "S2", "2000", "0", "66.6666666667"), ("F2A", "S2", "2000", "0", "0"), ("F3", "S3", "100", "0", "30"),
              ("F4", "S4", "500", None, None), ("F6", "S1", "1100", "0", "0")],
             [("F2", "10", A2, "300", "EC", "Long"), ("F2", "11", B, "50", "EC", "Long"), ("F2A", "12", A2, "999", "EC", "Long"),
              ("F3", "13", A, "70", "EC", "Long"), ("F4", "14", A, "100", "EC", "Long"), ("F6", "15", A, "100", "EC", "Long")])
    return ablage, ordner, tmp_path


def test_fristen():
    assert n.frist("2026-06-30") == date(2026, 8, 31)                      # 29.08. ist ein Samstag
    assert n.noetige_dateien("2026-06-30") == ["2026q2", "2026q3"] and n.noetige_dateien("2026-09-30") == ["2026q3", "2026q4"]
    assert n.verfuegbar_ab("2026-04-30") == pd.Timestamp("2026-09-01 09:30", tz=ET)
    html = '<a href="/files/dera/data/form-n-port-data-sets/2026q3_nport.zip">x</a><a href="/files/nport_readme.pdf">y</a>'
    assert n.links_aus_seite(html) == {"2026q3": "https://www.sec.gov/files/dera/data/form-n-port-data-sets/2026q3_nport.zip"}


def test_archiv_lesen(lage):
    ablage, ordner, tmp = lage
    fonds, bestand, info = n.lies_archiv(ordner / "2026q2_nport.zip", "2026q2")
    assert fonds[["accession", "serie", "art", "vermoegen", "nettofluss"]].values.tolist() == [["F1", "S1", "NPORT-P", 1000.0, 150.0]]
    assert fonds["fluss"].iloc[0] == pytest.approx(0.15) and fonds["berichtstag"].iloc[0] == pd.Timestamp("2026-04-30")
    assert bestand.set_index("cusip")["stueck"].to_dict() == {A: 100, B: 50, C: 10}
    assert info["ohne_cusip"] == 2 and info["cusip_aus_isin"] == 1 and info["positionszeilen"] == 6
    f3 = n.lies_archiv(ordner / "2026q3_nport.zip", "2026q3")[0].set_index("accession")
    assert pd.isna(f3.loc["F4", "fluss"]) and f3.loc["F2", "fluss"] == pytest.approx(-0.1)


def test_lauf(lage):
    ablage, ordner, tmp = lage
    p, info, hinweise = n.lauf(ablage, tmp / "arb", lokal=ordner)
    assert info["gerechnet"] == ["2026q2"] and info["unvollstaendig"] == ["2026q3"] and info["datensaetze_neu"] == ["2026q2", "2026q3"]
    fi = ablage.lies_bereinigt("nport_firmen").set_index("cik")
    # Firma 10: Fonds 1 (100 Stück, +15 %), Fonds 2 (300, −10 %), Fonds 4 (100, ohne Flussangabe); Fonds 3 zu spät
    assert fi.loc[10, ["fonds", "stueck", "stueck_abfluss", "stueck_zufluss"]].tolist() == [3, 500, 300, 100]
    assert fi.loc[10, "fluss_gewichtet"] == pytest.approx((100 * 0.15 - 300 * 0.1) / 400)
    assert fi.loc[11, "fonds"] == 2 and fi.loc[12, "fonds"] == 1 and (fi["fonds_quartal"] == 3).all()
    werte = {(z.parameter_id, int(z.cik)): z.wert for z in p.itertuples()}
    assert werte == {("KD3-01", 10): pytest.approx(-0.0375), ("IH5-06", 10): 3.0, ("IH5-06", 11): 2.0, ("IH5-06", 12): 1.0}
    zeile = p.iloc[0]
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2026-09-01 09:30", tz=ET) and zeile["ereignis_zeit"] == pd.Timestamp("2026-06-30 18:00", tz=ET)
    assert set(p["stand"]) == {"2026q2"}
    assert set(ablage.lies_bereinigt("nport_bestaende").columns) == {"accession", "cusip", "stueck", "gewicht"}   # kein Kurswert

    # Folgelauf ohne neuen Datensatz: nichts neu gelesen oder gerechnet
    p2, info, _ = n.lauf(ablage, tmp / "arb", lokal=ordner)
    assert info["datensaetze_neu"] == [] and info["gerechnet"] == [] and len(p2) == len(p)

    # der Datensatz des vierten Quartals vervollständigt das dritte Berichtsquartal
    baue_zip(ordner / "2026q4_nport.zip", [("F7", "15-OCT-2026", "NPORT-P", "31-AUG-2026")], [("F7", "S7", "100", "10", "0")],
             [("F7", "20", B, "5", "EC", "Long")])
    p3, info, _ = n.lauf(ablage, tmp / "arb", lokal=ordner)
    assert info["gerechnet"] == ["2026q3"] and info["unvollstaendig"] == [] and info["datensaetze_neu"] == ["2026q4"]
    q3 = ablage.lies_bereinigt("nport_firmen")
    q3 = q3[q3["periode"] == pd.Timestamp("2026-09-30")].set_index("cik")
    assert q3.loc[10, "fonds"] == 1 and q3.loc[11, "fonds"] == 1 and set(p3["stand"]) == {"2026q2", "2026q3"}
