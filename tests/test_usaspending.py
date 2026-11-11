import zipfile
from datetime import date

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.http import QuelleNichtErreichbar
from daten_offen.kern.namen import bereinige
from daten_offen.kern.zeit import ET
from daten_offen.quellen import usaspending as u

KOPF = ["contract_transaction_unique_key"] + u.SPALTEN + ["naics_code"]


def zeile(betrag, aktion, meldung="", behoerde="047", mutter_uei="", mutter="", roh="", uei="", name="", name_roh=""):
    return {"contract_transaction_unique_key": "k", "federal_action_obligation": betrag, "action_date": aktion,
            "awarding_agency_code": behoerde, "recipient_uei": uei, "recipient_name": name, "recipient_name_raw": name_roh,
            "recipient_parent_uei": mutter_uei, "recipient_parent_name": mutter, "recipient_parent_name_raw": roh,
            "initial_report_date": meldung, "naics_code": "336411"}


def baue_zip(pfad, zeilen, teile=1):
    df = pd.DataFrame(zeilen, columns=KOPF)
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(teile):
            z.writestr(f"{pfad.stem}_{i + 1}.csv", df.iloc[i::teile].to_csv(index=False))
    return pfad


def firmen():
    return pd.DataFrame({
        "cik": [10, 12, 13, 14, 15, 16, 17, 49071, 82267, 1047122],
        "name": ["ALPHA CORP", "GAMMA INC", "DELTA SYSTEMS INC", "EPSILON MARYLAND LLC", "EPSILON COMMUNICATIONS INC",
                 "ZETA GROUP INC", "Theta Corp", "HUMANA INC", "RAYTHEON CO", "RAYTHEON CO/"],
        "tickers": ["ALP", None, None, None, "EPS", "ZET", "THT", "HUM", None, None],
        "sic": ["3720"] * 10, "fruehere_namen": ["[]"] * 10})


ALPHA = dict(mutter_uei="P1", mutter="ALPHA CORP", uei="C1", name="ALPHA CORP")
FY26 = [
    zeile("100.00", "2026-09-10", "2026-09-11 03:35:06+00", roh="ALPHA  CORPORATION", **ALPHA),               # bekannt 13.09.
    zeile("50", "2026-09-29", "2026-09-30 10:00:00+00", roh="BETA AIRCRAFT  LLC", **ALPHA),                   # bekannt 02.10.
    zeile("1000", "2026-06-20", "2026-06-20 10:00:00+00", behoerde="097", roh="ALPHA CORPORATION", **ALPHA),  # Sperre: 20.09.
    zeile("-20", "2026-08-10", "", roh="ALPHA CORPORATION", **ALPHA),                                          # ohne Meldetag: 11.09.
    zeile("7", "2026-09-01", "2026-08-20 10:00:00+00", roh="ALPHA CORPORATION", **ALPHA),                     # Meldung vor Auftrag: 03.09.
    zeile("5", "2026-09-02", "2026-09-02 10:00:00+00", uei="R9", name="LONE STAR, LLC", name_roh="LONE STAR  LLC"),
    zeile("3", "2026-09-02", "2026-09-02 10:00:00+00", name="NAMENLOS INC", name_roh="NAMENLOS INC"),
    zeile("9", "kein Datum", "2026-09-02 10:00:00+00", roh="ALPHA CORPORATION", **ALPHA),
]


def test_schluessel_und_zeit():
    assert u.haushaltsjahr(date(2026, 9, 30)) == 2026 and u.haushaltsjahr(date(2026, 10, 1)) == 2027
    assert u.datei_schluessel("https://x/FY2026_All_Contracts_Full_20261106.zip") == (2026, date(2026, 11, 6))
    assert u.datei_schluessel("FY(All)_All_Contracts_Delta_20261106.zip") is None
    t = lambda *tage: pd.Series(pd.to_datetime(list(tage)))
    aus = u.bekannt_am(t("2026-09-10", "2026-06-20", "2026-08-10", "2026-09-01", "2026-06-20"),
                       t("2026-09-11", "2026-06-20", None, "2026-08-20", "2026-10-01"),
                       pd.Series([False, True, False, False, True]))
    # Meldetag + 2; Verteidigung: Auftrag + 90 + 2; ohne Meldetag: Auftrag + 30 + 2; Meldung vor Auftrag: Auftrag + 2;
    # Verteidigung mit später Meldung: Meldetag + 2
    assert aus.dt.strftime("%Y-%m-%d").tolist() == ["2026-09-13", "2026-09-20", "2026-09-11", "2026-09-03", "2026-10-03"]


def test_lies_archiv(tmp_path):
    tabelle, info = u.lies_archiv(baue_zip(tmp_path / "FY2026_All_Contracts_Full_20261106.zip", FY26, teile=2))
    assert info["zeilen"] == 8 and info["ohne_datum"] == 1 and info["ohne_meldetag"] == 1 and info["zeilen_dod"] == 1
    assert info["juengste_aktion_zivil"] == "2026-09-29" and info["juengste_aktion_dod"] == "2026-06-20"
    t = tabelle.set_index(["familie", "roh", "monat"])
    sep, okt = pd.Timestamp("2026-09-01"), pd.Timestamp("2026-10-01")
    assert t.loc[("P1", "ALPHA CORPORATION", sep), ["betrag", "zeilen"]].tolist() == [1087.0, 4]     # 100 + 1000 - 20 + 7
    assert t.loc[("P1", "BETA AIRCRAFT LLC", okt), "betrag"] == 50.0
    # ohne Mutter zählt der Empfänger selbst; ohne jede UEI der Name
    assert t.loc[("R9", "LONE STAR LLC", sep), "betrag"] == 5.0 and t.loc[("NAME:NAMENLOS INC", "NAMENLOS INC", sep), "betrag"] == 3.0
    assert set(tabelle.loc[tabelle["familie"] == "R9", "mutter"]) == {"LONE STAR, LLC"} and len(tabelle) == 4
    assert info["betrag"] == pytest.approx(1145.0)


def test_pflichtspalten(tmp_path):
    pfad = tmp_path / "FY2026_All_Contracts_Full_20261106.zip"
    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("a.csv", "action_date,recipient_uei\n2026-01-01,X\n")
    with pytest.raises(KeyError, match="Pflichtspalten fehlen"):
        u.lies_archiv(pfad)


def monate(*zeilen):
    return pd.DataFrame([(f, m, r, pd.Timestamp(monat), float(b), 1) for f, m, r, monat, b in zeilen],
                        columns=u.SCHLUESSEL + ["monat", "betrag", "zeilen"])


def test_zuordnung():
    m = monate(
        # Familie trägt den Namen der Mutter; die Tochter mit anderem Namen zählt mit
        ("F1", "ALPHA CORP", "ALPHA CORPORATION", "2026-01-01", 100), ("F1", "ALPHA CORP", "BETA AIRCRAFT LLC", "2026-02-01", 50),
        # falscher heutiger Name (eine zugekaufte Firma): die gemeldeten Namen entscheiden
        ("F2", "GAMMA INC", "DELTA SYSTEMS INC", "2026-01-01", 40), ("F2", "GAMMA INC", "DELTA HEALTH LLC", "2026-02-01", 10),
        # heutiger Name ist eine Tochter ohne Börsenkürzel; ein gemeldeter Name nennt die börsennotierte Mutter
        ("F3", "EPSILON MARYLAND LLC", "EPSILON BUSINESS LLC", "2026-01-01", 30),
        ("F3", "EPSILON MARYLAND LLC", "EPSILON COMMUNICATIONS INC.", "2026-02-01", 2),
        ("F3", "EPSILON MARYLAND LLC", "EPSILON MARYLAND LLC", "2026-03-01", 1),
        # Mutter im Abgleich, aber kein gemeldeter Name stützt sie
        ("F4", "ZETA GROUP INC", "OMEGA SERVE INC", "2026-01-01", 20),
        # Namensanfang von Hand, gleichnamige Firmen von Hand, ohne Treffer
        ("F5", "HUMANA GOVERNMENT BUSINESS INC", "HUMANA GOVERNMENT BUSINESS INC", "2026-01-01", 9),
        ("F6", "RAYTHEON COMPANY", "RAYTHEON COMPANY", "2015-01-01", 8),
        ("F7", "KLEIN LLC", "KLEIN LLC", "2026-01-01", 7),
        # Stützung nur in einem von zehn Monaten und mit wenig Volumen: zu wenig für die ganze Familie
        ("F8", "THETA CORP", "THETA SERVICES LLC", "2025-01-01", 1),
        *[("F8", "THETA CORP", "KAPPA LLC", f"2025-{i:02d}-01", 100) for i in range(2, 11)])
    z = u.ordne_zu(m, firmen()).set_index(["familie", "roh"])
    assert z.loc[("F1", "ALPHA CORPORATION"), ["cik", "art"]].tolist() == [10, "exakt"]
    assert z.loc[("F1", "BETA AIRCRAFT LLC"), ["cik", "konfidenz", "art"]].tolist() == [10, 1.0, "familie"]
    assert z.loc[("F2", "DELTA SYSTEMS INC"), "cik"] == 13 and z.loc[("F2", "DELTA HEALTH LLC"), ["cik", "art"]].tolist() == [13, "familie"]
    assert set(z.loc["F3", "cik"]) == {15} and z.loc[("F3", "EPSILON MARYLAND LLC"), "art"] == "familie"
    assert pd.isna(z.loc[("F4", "OMEGA SERVE INC"), "cik"]) and z.loc[("F4", "OMEGA SERVE INC"), "art"] == "ungestuetzt"
    assert z.loc[("F5", "HUMANA GOVERNMENT BUSINESS INC"), ["cik", "konfidenz", "art"]].tolist() == [49071, 0.9, "marke"]
    assert z.loc[("F6", "RAYTHEON COMPANY"), ["cik", "art"]].tolist() == [1047122, "exakt"]
    assert pd.isna(z.loc[("F7", "KLEIN LLC"), "cik"]) and z.loc[("F7", "KLEIN LLC"), "art"] == "keiner"
    assert pd.isna(z.loc[("F8", "KAPPA LLC"), "cik"]) and z.loc[("F8", "KAPPA LLC"), "art"] == "ungestuetzt"
    assert pd.isna(z.loc[("F8", "THETA SERVICES LLC"), "cik"])
    # dieselbe Familie, in der Hälfte der Monate gestützt: die Mutter gilt für alle
    z = u.ordne_zu(monate(("F8", "THETA CORP", "THETA SERVICES LLC", "2025-01-01", 1), ("F8", "THETA CORP", "KAPPA LLC", "2025-02-01", 100)),
                   firmen()).set_index("roh")
    assert z["cik"].tolist() == [17, 17] and z.loc["KAPPA LLC", "art"] == "familie"


def test_namen_rechtsform():
    assert bereinige("SANOFI S A") == "SANOFI" and bereinige("FOUR POINTS TECHNOLOGY, L.L.C.") == "FOUR POINTS TECHNOLOGY"
    assert bereinige("AMERICAN NATIONAL RED CROSS, THE") == "AMERICAN NATIONAL RED CROSS"
    assert bereinige("XYZ SERIES A B") == "XYZ SERIES A B" and bereinige("S A") == "S A"


class Quelle:
    """Ersatz für den Abruf: Verzeichnis und Dateien aus einem Ordner; ``gestoert`` bricht bei diesen Jahren ab."""

    def __init__(self, ordner, gestoert=()):
        self.ordner, self.gestoert, self.abfragen = ordner, set(gestoert), []

    def sende_json(self, url, daten):
        self.abfragen.append(daten["fiscal_year"])
        return {"monthly_files": [{"file_name": p.name, "url": f"https://files.example/{p.name}"}
                                  for p in sorted(self.ordner.glob(f"FY{daten['fiscal_year']}_*.zip"))]
                + [{"file_name": "FY(All)_All_Contracts_Delta_20261106.zip", "url": "https://files.example/delta.zip"}]}

    def hole_datei(self, url, ziel, erlaube_404=False):
        name = url.rsplit("/", 1)[-1]
        if u.datei_schluessel(name)[0] in self.gestoert:
            raise QuelleNichtErreichbar(f"{url}: Verbindung abgebrochen")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes((self.ordner / name).read_bytes())
        return ziel


def test_abruf_gestoert(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    ordner = tmp_path / "zips"
    ordner.mkdir()
    baue_zip(ordner / "FY2026_All_Contracts_Full_20261106.zip", FY26)
    baue_zip(ordner / "FY2027_All_Contracts_Full_20261106.zip",
             [zeile("60", "2026-10-20", "2026-10-21", roh="ALPHA CORPORATION", **ALPHA)])
    heute = date(2026, 11, 11)
    quelle = Quelle(ordner, gestoert=[2026])
    p, info, hinweise = u.lauf(ablage, tmp_path / "arb", abruf=quelle, heute=heute)
    assert quelle.abfragen == list(range(2008, 2028))                       # eine Verzeichnisabfrage je Haushaltsjahr
    assert info["neu_gelesen"] == [2027] and any("Haushaltsjahr 2026 nicht gelesen" in h for h in hinweise)
    assert p.set_index("stand")["wert"].to_dict() == {"2026-10": 60.0}       # das Gelesene bleibt
    assert not list((tmp_path / "arb" / "usaspending").glob("*"))            # keine Reste der Sammeldateien
    p, info, hinweise = u.lauf(ablage, tmp_path / "arb", abruf=Quelle(ordner), heute=heute)
    assert info["neu_gelesen"] == [2026] and info["haushaltsjahre_gelesen"] == 2
    assert p.set_index("stand")["wert"].to_dict() == {"2026-09": 1087.0, "2026-10": 110.0}
    assert not any("nicht gelesen" in h for h in hinweise)


def test_lauf(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    ordner = tmp_path / "zips"
    ordner.mkdir()
    baue_zip(ordner / "FY2025_All_Contracts_Full_20261106.zip",
             [zeile("400", "2025-08-05", "2025-08-06 10:00:00+00", roh="ALPHA CORPORATION", **ALPHA)])
    baue_zip(ordner / "FY2026_All_Contracts_Full_20261106.zip", FY26)
    baue_zip(ordner / "FY2027_All_Contracts_Full_20261106.zip",
             [zeile("60", "2026-10-20", "2026-10-21 10:00:00+00", roh="ALPHA CORPORATION", **ALPHA),
              zeile("70", "2026-11-03", "2026-11-04 10:00:00+00", roh="ALPHA CORPORATION", **ALPHA)])      # laufender Monat
    baue_zip(ordner / "FY(All)_All_Contracts_Delta_20261106.zip", [])
    p, info, hinweise = u.lauf(ablage, tmp_path / "arb", lokal=ordner)
    assert info["neu_gelesen"] == [2025, 2026, 2027] and info["haushaltsjahre_gelesen"] == 3 and info["letzter_monat"] == "2026-10"
    werte = p.set_index("stand")["wert"].to_dict()
    # September: 1087; Oktober aus zwei Haushaltsjahren: 50 + 60; November ist noch nicht abgeschlossen
    assert werte == {"2025-08": 400.0, "2026-09": 1087.0, "2026-10": 110.0}
    assert set(p["cik"]) == {10} and set(p["parameter_id"]) == {"PR2-01"}
    sep = p[p["stand"] == "2026-09"].iloc[0]
    assert sep["ereignis_zeit"] == pd.Timestamp("2026-09-30 23:59:59", tz=ET)
    assert sep["verfuegbar_ab"] == pd.Timestamp("2026-10-16 09:30", tz=ET)          # 15 Tage nach Monatsende, nächste Eröffnung
    z = ablage.lies_bereinigt("usaspending_zuordnung").set_index(["familie", "roh"])
    assert z.loc[("P1", "BETA AIRCRAFT LLC"), ["cik", "art", "umfang"]].tolist() == [10, "familie", 50.0]
    assert pd.isna(z.loc[("R9", "LONE STAR LLC"), "cik"])
    assert info["trefferquote"]["quote_gewichtet"] == pytest.approx(1 - 8 / 1675, abs=1e-4) and info["anteil_boerse"] > 0.99
    assert any("jüngste Sammeldatei: Stand 2026-11-06" in h for h in hinweise)

    p2, info, _ = u.lauf(ablage, tmp_path / "arb", lokal=ordner)                    # Tagesbetrieb ohne neue Datei
    assert info["neu_gelesen"] == [] and len(p2) == 3

    # Dezember: neue Stände; nur die beiden jüngsten Haushaltsjahre werden neu gelesen
    for jahr in (2025, 2026, 2027):
        (ordner / f"FY{jahr}_All_Contracts_Full_20261106.zip").unlink()
    baue_zip(ordner / "FY2025_All_Contracts_Full_20261206.zip", [zeile("999", "2025-08-05", "2025-08-06", roh="ALPHA CORPORATION", **ALPHA)])
    baue_zip(ordner / "FY2026_All_Contracts_Full_20261206.zip", FY26[:1])
    baue_zip(ordner / "FY2027_All_Contracts_Full_20261206.zip",
             [zeile("60", "2026-10-20", "2026-10-21", roh="ALPHA CORPORATION", **ALPHA),
              zeile("70", "2026-11-03", "2026-11-04", roh="ALPHA CORPORATION", **ALPHA),
              zeile("500", "2026-08-10", "2026-08-10", behoerde="097", roh="ALPHA CORPORATION", **ALPHA)])  # Sperre bis 08.11.
    p3, info, _ = u.lauf(ablage, tmp_path / "arb", lokal=ordner)
    assert info["neu_gelesen"] == [2026, 2027] and info["letzter_monat"] == "2026-11"
    assert p3.set_index("stand")["wert"].to_dict() == {"2025-08": 400.0, "2026-09": 100.0, "2026-10": 60.0, "2026-11": 570.0}
    dateien = ablage.lies_bereinigt("usaspending_dateien").set_index("haushaltsjahr")
    assert dateien["stand"].dt.strftime("%Y-%m-%d").to_dict() == {2025: "2026-11-06", 2026: "2026-12-06", 2027: "2026-12-06"}
