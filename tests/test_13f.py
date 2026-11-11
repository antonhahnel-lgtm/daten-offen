import zipfile
from datetime import date

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import edgar_13f as f
from tests.hilfen import tsv

SUB = ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]
INFO = ["ACCESSION_NUMBER", "INFOTABLE_SK", "NAMEOFISSUER", "TITLEOFCLASS", "CUSIP", "FIGI", "VALUE", "SSHPRNAMT",
        "SSHPRNAMTTYPE", "PUTCALL"]
A, B, C, X = "111111111", "222222222", "333333333", "999999999"
FUELL = [f"7000000{i:02d}" for i in range(12)]          # zwölf weitere Wertpapiere für einen konzentrierten Manager


def baue_zip(pfad, meldungen, positionen):
    zeilen = [[acc, i, "NAME", "COM", cusip, "", wert, stueck, art, putcall]
              for i, (acc, cusip, wert, stueck, art, putcall) in enumerate(positionen)]
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SUBMISSION.tsv", tsv(SUB, meldungen))
        z.writestr("INFOTABLE.tsv", tsv(INFO, zeilen))
        z.writestr("FORM13F_readme.htm", "x")
    return pfad


def pos(acc, cusip, wert, stueck, art="SH", putcall=""):
    return (acc, cusip, wert, stueck, art, putcall)


@pytest.fixture()
def lage(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("ftd_wertpapiere", "alle", pd.DataFrame({
        "cusip": [A, B, C, X], "cik": pd.array([10, 11, 12, pd.NA], dtype="Int64"),
        "konfidenz": [0.98, 0.98, 1.0, 0.0], "art": ["kuerzel_name", "kuerzel_name", "exakt", "keiner"],
        "stamm": [True, True, True, True]}))
    ordner = tmp_path / "f13"
    ordner.mkdir()
    # Berichtsquartal 31.03.2024 (Frist 15.05.): Manager 1, 2, 3
    baue_zip(ordner / "01mar2024-31may2024_form13f.zip",
             [["Q1-M1", "10-MAY-2024", "13F-HR", "0000000001", "31-MAR-2024"],
              ["Q1-M2", "14-MAY-2024", "13F-HR", "2", "31-MAR-2024"],
              ["Q1-M3", "15-MAY-2024", "13F-HR", "3", "31-MAR-2024"],
              ["Q1-NT", "15-MAY-2024", "13F-NT", "4", "31-MAR-2024"],
              ["Q4-SPAET", "20-MAR-2024", "13F-HR", "5", "31-DEC-2023"]],          # 80 Tage: verspätet
             [pos("Q1-M1", A, 100, 10), pos("Q1-M1", B, 100, 10),
              pos("Q1-M2", A, 300, 30), pos("Q1-M3", B, 50, 5), pos("Q1-M3", C, 50, 5),
              pos("Q4-SPAET", A, 1, 1)])
    # Berichtsquartal 30.06.2024: Manager 1, 2 (beide wie zuvor), 6 (neu); Manager 3 meldet nicht mehr
    konzentriert = [pos("Q2-M6", c, 10, 1) for c in FUELL] + [pos("Q2-M6", C, 880, 88)]
    baue_zip(ordner / "01jun2024-31aug2024_form13f.zip",
             [["Q2-M1-ALT", "01-AUG-2024", "13F-HR", "1", "30-JUN-2024"],
              ["Q2-M1", "05-AUG-2024", "13F-HR", "1", "30-JUN-2024"],               # jüngste Meldung zählt
              ["Q2-M2", "14-AUG-2024", "13F-HR", "2", "30-JUN-2024"],
              ["Q2-M6", "14-AUG-2024", "13F-HR", "6", "30-JUN-2024"],
              ["Q2-M2A", "20-AUG-2024", "13F-HR/A", "2", "30-JUN-2024"]],           # Nachtrag zählt nicht
             [pos("Q2-M1-ALT", X, 999, 99),
              pos("Q2-M1", A, 100, 10), pos("Q2-M1", A, 50, 5), pos("Q2-M1", C, 100, 10),   # A zweimal: summiert; B verkauft
              pos("Q2-M1", B, 500, 50, putcall="Put"), pos("Q2-M1", B, 500, 50, art="PRN"),
              pos("Q2-M2", A, 300, 30), pos("Q2-M2", B, 30, 3),
              pos("Q2-M2A", X, 5, 5)] + konzentriert)
    return ablage, ordner, tmp_path


def test_schluessel_und_stichtag():
    assert f.fensterende("2023q4") == date(2023, 12, 31)
    assert f.fensterende("01jan2024-29feb2024") == date(2024, 2, 29)
    html = ('<a href="/files/structureddata/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip">a</a>'
            '<a href="/files/structureddata/data/form-13f-data-sets/2013q2_form13f.zip">b</a><a href="/x.zip">c</a>')
    assert sorted(f.links_aus_seite(html)) == ["01jun2026-31aug2026", "2013q2"]
    # 30.06.2024 + 47 Tage = Freitag 16.08. nach Börsenschluss -> Montag 19.08. zur Eröffnung
    assert f.verfuegbar_ab("2024-06-30") == pd.Timestamp("2024-08-19 09:30", tz=ET)
    assert f.quartal_name("2024-06-30") == "2024q2"


def test_lauf(lage):
    ablage, ordner, tmp = lage
    p, info, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner)
    q = ablage.lies_bereinigt("edgar_13f_quartal")
    q2 = q[q["periode"] == "2024-06-30"].set_index("cusip")
    q1 = q[q["periode"] == "2024-03-31"].set_index("cusip")
    assert q1["halter"].to_dict() == {A: 2, B: 2, C: 1} and q1["manager"].iloc[0] == 3
    assert q1["breite_aenderung"].isna().all()                       # kein Vorquartal
    assert q2.loc[A, ["halter", "stueck"]].tolist() == [2, 45] and q2.loc[C, "halter"] == 2
    assert X not in q2.index                                          # ältere Meldung desselben Managers und Nachtrag
    # Manager in beiden Quartalen: 1 und 2. A: 2 -> 2; B: 1 -> 1 (Manager 2 kauft, Manager 1 verkauft); C: 0 -> 1
    assert q2.loc[[A, B, C], "breite_aenderung"].tolist() == [0.0, 0.0, 0.5] and q2["manager_beide"].iloc[0] == 2
    # nur Manager 6 hat 10–200 Positionen; sein größtes Übergewicht ist C
    assert q2["beste_idee"].to_dict() == {**{c: 0 for c in FUELL}, A: 0, B: 0, C: 1}

    werte = {(z.parameter_id, int(z.cik), z.stand): z.wert for z in p.itertuples()}
    assert werte == {("IH5-04", 10, "2024q2"): 0.0, ("IH5-04", 11, "2024q2"): 0.0, ("IH5-04", 12, "2024q2"): 0.5,
                     ("IH5-03", 12, "2024q2"): 1.0}
    zeile = p[p["parameter_id"] == "IH5-03"].iloc[0]
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2024-08-19 09:30", tz=ET)
    assert zeile["ereignis_zeit"] == pd.Timestamp("2024-06-30 18:00", tz=ET)
    bestand = ablage.lies_bereinigt("edgar_13f_bestaende")
    assert set(bestand.columns) == {"filer_cik", "cusip", "stueck", "gewicht"}          # kein Kurswert
    m1 = pd.read_parquet(ablage.bereinigt / "bereinigt__edgar_13f_bestaende__2024q2.parquet")
    m1 = m1[m1["filer_cik"] == 1].set_index("cusip")["gewicht"]
    assert m1[A] == pytest.approx(0.6) and m1[C] == pytest.approx(0.4)
    assert info["datensaetze_gelesen"] == 2 and info["quartale"] == 2 and info["juengstes_quartal"] == "2024q2"
    dateien = ablage.lies_bereinigt("edgar_13f_dateien").set_index("datei")
    assert dateien.loc["01jun2024-31aug2024", ["erstmeldungen", "fristgerecht"]].tolist() == [4, 3]
    assert dateien.loc["01mar2024-31may2024", "fristgerecht"] == 3


def test_fortschreibung(lage):
    ablage, ordner, tmp = lage
    spaeter = ordner / "01jun2024-31aug2024_form13f.zip"
    weg = tmp / "spaeter.zip"
    spaeter.rename(weg)
    p1, _, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner)        # nur das erste Quartal
    assert p1.empty
    weg.rename(spaeter)
    p2, info, _ = f.lauf(ablage, tmp / "arb", lokal=ordner)            # das zweite kommt dazu, das erste bleibt
    assert info["datensaetze_neu"] == 1 and info["datensaetze_gelesen"] == 2
    assert len(p2) == 4 and not ablage.lies_bereinigt("edgar_13f_quartal").duplicated(["periode", "cusip"]).any()


def test_pflichtspalten(tmp_path):
    with zipfile.ZipFile(tmp_path / "k.zip", "w") as z:
        z.writestr("SUBMISSION.tsv", tsv(["ACCESSION_NUMBER", "DATUM"], [["a", "b"]]))
        z.writestr("INFOTABLE.tsv", tsv(INFO, []))
    with pytest.raises(KeyError, match="Pflichtspalten fehlen"):
        f.lies_archiv(tmp_path / "k.zip")
