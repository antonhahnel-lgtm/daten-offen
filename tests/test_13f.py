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
A, A2, B, C, D, X = "111111111", "111111112", "222222222", "333333333", "444444444", "999999999"
FUELL = [f"7000000{i:02d}" for i in range(12)]          # zwölf weitere Aktien für einen konzentrierten Manager


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
    # A und A2 sind dieselbe Firma (CUSIP-Wechsel); X ist nicht zugeordnet
    ablage.schreibe_bereinigt("ftd_wertpapiere", "alle", pd.DataFrame({
        "cusip": [A, A2, B, C, D, X] + FUELL,
        "cik": pd.array([10, 10, 11, 12, 13, pd.NA] + [100 + i for i in range(12)], dtype="Int64"),
        "konfidenz": [0.98, 0.98, 0.98, 1.0, 0.98, 0.0] + [0.98] * 12,
        "art": ["kuerzel_name"] * 5 + ["keiner"] + ["kuerzel_name"] * 12, "stamm": [True] * 18}))
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
              pos("Q1-M2", A, 300, 30), pos("Q1-M2", D, 10, 1),
              pos("Q1-M3", B, 50, 5), pos("Q1-M3", C, 50, 5),
              pos("Q4-SPAET", A, 1, 1)])
    # Berichtsquartal 30.06.2024 (Frist 14.08.): Manager 1 und 2 wie zuvor, 6 neu; Manager 3 meldet nicht mehr.
    # Firma 10 hat eine neue CUSIP: Manager 1 meldet sie, Manager 2 noch die alte.
    konzentriert = [pos("Q2-M6", c, 10, 1) for c in FUELL] + [pos("Q2-M6", C, 880, 88)]
    baue_zip(ordner / "01jun2024-31aug2024_form13f.zip",
             [["Q2-M1-ALT", "01-AUG-2024", "13F-HR", "1", "30-JUN-2024"],
              ["Q2-M1", "05-AUG-2024", "13F-HR", "1", "30-JUN-2024"],               # jüngste Meldung zählt
              ["Q2-M2", "14-AUG-2024", "13F-HR", "2", "30-JUN-2024"],
              ["Q2-M6", "14-AUG-2024", "13F-HR", "6", "30-JUN-2024"],
              ["Q2-M7", "15-AUG-2024", "13F-HR", "7", "30-JUN-2024"],               # einen Tag nach der Frist
              ["Q2-M2A", "13-AUG-2024", "13F-HR/A", "2", "30-JUN-2024"]],           # Nachtrag zählt nicht
             [pos("Q2-M1-ALT", X, 999, 99),
              pos("Q2-M1", A2, 100, 10), pos("Q2-M1", A2, 50, 5), pos("Q2-M1", C, 100, 10),   # A2 zweimal: summiert; B verkauft
              pos("Q2-M1", B, 500, 50, putcall="Put"), pos("Q2-M1", B, 500, 50, art="PRN"),
              pos("Q2-M2", A, 300, 30), pos("Q2-M2", B, 30, 3),
              pos("Q2-M7", X, 7, 7), pos("Q2-M2A", X, 5, 5)] + konzentriert)
    return ablage, ordner, tmp_path


def test_schluessel_und_stichtag():
    assert f.fensterende("2023q4") == date(2023, 12, 31)
    assert f.fensterende("01jan2024-29feb2024") == date(2024, 2, 29)
    html = ('<a href="/files/structureddata/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip">a</a>'
            '<a href="/files/structureddata/data/form-13f-data-sets/2013q2_form13f.zip">b</a><a href="/x.zip">c</a>')
    assert sorted(f.links_aus_seite(html)) == ["01jun2026-31aug2026", "2013q2"]
    assert f.frist("2024-06-30") == date(2024, 8, 14)
    # 14.02.2026 ist ein Samstag, der 16.02. Presidents' Day; ebenso 2015
    assert f.frist("2025-12-31") == date(2026, 2, 17) and f.frist("2014-12-31") == date(2015, 2, 17)
    assert f.verfuegbar_ab("2024-06-30") == pd.Timestamp("2024-08-15 09:30", tz=ET)
    assert f.verfuegbar_ab("2025-12-31") == pd.Timestamp("2026-02-18 09:30", tz=ET)
    assert f.quartal_name("2024-06-30") == "2024q2"


def test_lauf(lage):
    ablage, ordner, tmp = lage
    p, info, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner)
    q = ablage.lies_bereinigt("edgar_13f_quartal")
    q1 = q[q["periode"] == "2024-03-31"].set_index("cusip")
    q2 = q[q["periode"] == "2024-06-30"].set_index("cusip")
    assert q1["halter"].to_dict() == {A: 2, B: 2, C: 1, D: 1}
    assert q2.loc[A2, ["halter", "stueck"]].tolist() == [1, 15] and q2.loc[A, "halter"] == 1 and q2.loc[C, "halter"] == 2
    assert X not in q2.index                 # ältere Meldung desselben Managers, verspätete Meldung, Nachtrag

    fi = ablage.lies_bereinigt("edgar_13f_firmen")
    f1 = fi[fi["periode"] == "2024-03-31"].set_index("cik")
    f2 = fi[fi["periode"] == "2024-06-30"].set_index("cik")
    assert f1["halter"].to_dict() == {10: 2, 11: 2, 12: 1, 13: 1} and f1["manager"].iloc[0] == 3
    assert f1["breite_aenderung"].isna().all()                       # kein Vorquartal
    # Firma 10: alte und neue CUSIP zählen zusammen -> zwei Halter, keine Änderung
    assert f2.loc[10, "halter"] == 2 and f2.loc[10, "breite_aenderung"] == 0.0
    # Manager in beiden Quartalen: 1 und 2. Firma 11: 1 -> 1; Firma 12: 0 -> 1; Firma 13: 1 -> 0 (niemand hält sie mehr)
    assert f2.loc[[11, 12, 13], "breite_aenderung"].tolist() == [0.0, 0.5, -0.5] and f2.loc[13, "halter"] == 0
    assert (f2["manager_beide"] == 2).all() and (f2["manager"] == 3).all()
    # nur Manager 6 hat 10–200 zugeordnete Aktien; sein größtes Übergewicht ist Firma 12
    assert f2["beste_idee"].sum() == 1 and f2.loc[12, "beste_idee"] == 1

    werte = {(z.parameter_id, int(z.cik)): z.wert for z in p.itertuples() if z.cik < 100}
    assert werte == {("IH5-04", 10): 0.0, ("IH5-04", 11): 0.0, ("IH5-04", 12): 0.5, ("IH5-04", 13): -0.5,
                     ("IH5-03", 12): 1.0}
    assert len(p) == 17 and set(p["stand"]) == {"2024q2"}
    zeile = p[p["parameter_id"] == "IH5-03"].iloc[0]
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2024-08-15 09:30", tz=ET)
    assert zeile["ereignis_zeit"] == pd.Timestamp("2024-06-30 18:00", tz=ET)
    bestand = ablage.lies_bereinigt("edgar_13f_bestaende")
    assert set(bestand.columns) == {"filer_cik", "cusip", "stueck", "gewicht"}          # kein Kurswert
    m1 = pd.read_parquet(ablage.bereinigt / "bereinigt__edgar_13f_bestaende__2024q2.parquet")
    m1 = m1[m1["filer_cik"] == 1].set_index("cusip")["gewicht"]
    assert m1[A2] == pytest.approx(0.6) and m1[C] == pytest.approx(0.4)
    assert info["datensaetze_gelesen"] == 2 and info["quartale"] == 2 and info["juengstes_quartal"] == "2024q2"
    assert info["firmen_juengstes"] == 16 and info["manager_juengstes"] == 3
    dateien = ablage.lies_bereinigt("edgar_13f_dateien").set_index("datei")
    assert dateien.loc["01jun2024-31aug2024", ["erstmeldungen", "fristgerecht"]].tolist() == [5, 3]
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
    assert len(p2) == 17 and not ablage.lies_bereinigt("edgar_13f_firmen").duplicated(["periode", "cik"]).any()
    p3, info, _ = f.lauf(ablage, tmp / "arb", lokal=ordner)            # Tagesbetrieb ohne neuen Datensatz
    assert info["datensaetze_neu"] == 0 and len(p3) == 17


def test_vorquartal_fehlt_lokal(lage):
    ablage, ordner, tmp = lage
    spaeter = ordner / "01jun2024-31aug2024_form13f.zip"
    weg = tmp / "spaeter.zip"
    spaeter.rename(weg)
    f.lauf(ablage, tmp / "arb", lokal=ordner)
    (ablage.bereinigt / "bereinigt__edgar_13f_bestaende__2024q1.parquet").unlink()      # wie im Tagesbetrieb
    weg.rename(spaeter)
    p, info, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner)
    assert any("ohne Bestand des Vorquartals" in h for h in hinweise)
    assert set(p["parameter_id"]) == {"IH5-03"}                       # Breite fehlt, beste Ideen sind da
    q = ablage.lies_bereinigt("edgar_13f_quartal")
    assert q["periode"].nunique() == 2 and not q.duplicated(["periode", "cusip"]).any()


def test_pflichtspalten(tmp_path):
    with zipfile.ZipFile(tmp_path / "k.zip", "w") as z:
        z.writestr("SUBMISSION.tsv", tsv(["ACCESSION_NUMBER", "DATUM"], [["a", "b"]]))
        z.writestr("INFOTABLE.tsv", tsv(INFO, []))
    with pytest.raises(KeyError, match="Pflichtspalten fehlen"):
        f.lies_archiv(tmp_path / "k.zip")
