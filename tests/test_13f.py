import zipfile
from datetime import date
from types import SimpleNamespace

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


# --------------------------------------------------------------------------- Einzelmeldungen (Quartal ohne Datensatz)
NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"


def z(cusip, wert, stueck, art="SH", putcall=""):
    return (cusip, wert, stueck, art, putcall)


def meldung(acc, cik, periode, eingereicht, zeilen, praefix="", form="13F-HR"):
    """Einreichungsdatei im Aufbau von EDGAR: Kopf, Deckblatt, Informationstabelle (mit oder ohne Namensraum-Vorsatz)."""
    p = f"{praefix}:" if praefix else ""
    xmlns = f'xmlns:{praefix}="{NS}"' if praefix else f'xmlns="{NS}"'
    eintraege = ""
    for cusip, wert, stueck, art, putcall in zeilen:
        eintraege += (
            f"<{p}infoTable>\n <{p}nameOfIssuer>N &amp; Co</{p}nameOfIssuer><{p}titleOfClass>COM</{p}titleOfClass>"
            f"<{p}cusip>{cusip}</{p}cusip>\n <{p}value>{wert}</{p}value>\n <{p}shrsOrPrnAmt><{p}sshPrnamt>{stueck}</{p}sshPrnamt>"
            f"<{p}sshPrnamtType>{art}</{p}sshPrnamtType></{p}shrsOrPrnAmt>"
            + (f"<{p}putCall>{putcall}</{p}putCall>" if putcall else "")
            + f"<{p}investmentDiscretion>SOLE</{p}investmentDiscretion><{p}votingAuthority><{p}Sole>{stueck}</{p}Sole>"
              f"<{p}Shared>0</{p}Shared><{p}None>0</{p}None></{p}votingAuthority>\n</{p}infoTable>\n")
    return (f"<SEC-DOCUMENT>{acc}.txt : {eingereicht}\n<SEC-HEADER>{acc}.hdr.sgml : {eingereicht}\n"
            f"<ACCEPTANCE-DATETIME>{eingereicht}101500\nACCESSION NUMBER:\t\t{acc}\nCONFORMED SUBMISSION TYPE:\t{form}\n"
            f"PUBLIC DOCUMENT COUNT:\t\t2\nCONFORMED PERIOD OF REPORT:\t{periode}\nFILED AS OF DATE:\t\t{eingereicht}\n\n"
            f"FILER:\n\n\tCOMPANY DATA:\t\n\t\tCOMPANY CONFORMED NAME:\t\t\tManager {cik}\n"
            f"\t\tCENTRAL INDEX KEY:\t\t\t{cik:010d}\n</SEC-HEADER>\n"
            "<DOCUMENT>\n<TYPE>13F-HR\n<SEQUENCE>1\n<FILENAME>primary_doc.xml\n<TEXT>\n<XML>\n"
            '<?xml version="1.0"?><edgarSubmission><cusip>000000000</cusip></edgarSubmission>\n</XML>\n</TEXT>\n</DOCUMENT>\n'
            "<DOCUMENT>\n<TYPE>INFORMATION TABLE\n<SEQUENCE>2\n<FILENAME>infotable.xml\n<TEXT>\n<XML>\n"
            f'<?xml version="1.0" encoding="UTF-8"?>\n<{p}informationTable {xmlns}>\n{eintraege}</{p}informationTable>\n'
            "</XML>\n</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n").encode("utf-8")


class Quelle:
    """Ersatz für den Abruf: Einreichungsdateien nach Aktenzeichen, zählt die Anfragen."""

    def __init__(self, dateien):
        self.dateien, self.anfragen = dateien, []

    def hole(self, url, erlaube_404=False, **kw):
        self.anfragen.append(url)
        inhalt = self.dateien.get(url.rsplit("/", 1)[-1].removesuffix(".txt"))
        return None if inhalt is None else SimpleNamespace(content=inhalt)


def verzeichnis(ablage, zeilen, jahr="2024"):
    df = pd.DataFrame(zeilen, columns=["cik", "accession", "form", "filing_date", "report_date"])
    df["filing_date"], df["report_date"] = pd.to_datetime(df["filing_date"]), pd.to_datetime(df["report_date"])
    ablage.schreibe_bereinigt("edgar_meldungen", jahr, df)


Q3 = "2024-09-30"                                             # Frist 14.11.2024
Q3_VERZEICHNIS = [
    [1, "Q3-M1-ALT", "13F-HR", "2024-11-01", Q3], [1, "Q3-M1", "13F-HR", "2024-11-05", Q3],
    [2, "Q3-M2", "13F-HR", "2024-11-14", Q3], [6, "Q3-M6", "13F-HR", "2024-11-12", Q3],
    [8, "Q3-M8", "13F-HR", "2024-11-14", Q3],
    [9, "Q3-M9", "13F-HR", "2024-11-13", None],               # ohne Berichtsdatum im Verzeichnis: der Kopf entscheidet
    [7, "Q3-M7", "13F-HR", "2024-11-15", Q3],                 # einen Tag nach der Frist
    [2, "Q3-M2A", "13F-HR/A", "2024-11-13", Q3],              # Nachtrag zählt nicht
    [5, "Q2-SPAET", "13F-HR", "2024-11-04", "2024-06-30"],    # verspätete Meldung für ein früheres Quartal
    [77, "ACHT-K", "8-K", "2024-11-15", None],                # das Verzeichnis reicht über die Frist hinaus
]


def q3_dateien():
    return {
        "Q3-M1-ALT": meldung("Q3-M1-ALT", 1, "20240930", "20241101", [z(X, 999, 99)]),
        "Q3-M1": meldung("Q3-M1", 1, "20240930", "20241105",
                         [z(A2, 100, 10), z(C, 100, 10), z(B, 500, 50, putcall="Put"), z(B, 500, 50, art="PRN")], "ns1"),
        "Q3-M2": meldung("Q3-M2", 2, "20240930", "20241114", [z(A, 300, 30), z(B, 30, 3), z(D, 10, 1)]),
        "Q3-M6": meldung("Q3-M6", 6, "20240930", "20241112", [z(c, 10, 1) for c in FUELL] + [z(C, 880, 88)], "n1"),
        "Q3-M8": meldung("Q3-M8", 8, "20240930", "20241114", [z(B, 50, 5)]),
        "Q3-M9": meldung("Q3-M9", 9, "20240630", "20241113", [z(X, 1, 1)]),
    }


def test_lies_meldung():
    kopf, pos = f.lies_meldung(meldung("0000000001-24-000002", 1970731, "20240930", "20241105", [
        z(A, 100, 10), z(A.lower(), 50, 5), z(B, 500, 50, putcall="Put"), z(B, 500, 50, art="PRN"),
        z("12345", 1, 1), z(C, 7, 0), z(D, "", 4)], "ns1"))
    assert kopf["form"] == "13F-HR" and kopf["filer_cik"] == 1970731 and kopf["zeilen"] == 7
    assert kopf["periode"] == pd.Timestamp(Q3) and kopf["eingereicht"] == pd.Timestamp("2024-11-05")
    # gleiche CUSIP summiert; Option, Nennbetrag, kurze CUSIP und Stückzahl 0 fallen weg; fehlender Wert zählt 0
    assert pos.set_index("cusip")[["stueck", "wert"]].to_dict("index") == {
        A: {"stueck": 15.0, "wert": 150.0}, D: {"stueck": 4.0, "wert": 0.0}}
    ohne = f.lies_meldung(meldung("a", 1, "20240930", "20241105", [z(A, 1, 1)]))[1]
    assert ohne["cusip"].tolist() == [A]                      # ohne Namensraum-Vorsatz
    with pytest.raises(ValueError, match="Informationstabelle"):
        f.lies_meldung(b"<SEC-HEADER>\nCONFORMED SUBMISSION TYPE:\t13F-HR\n</SEC-HEADER>\n")


def test_offene_quartale():
    assert f.periode_von("2026q3") == pd.Timestamp("2026-09-30") and f.periode_von("2025Q4") == pd.Timestamp("2025-12-31")
    # Frist für das dritte Quartal 2026: 16.11. (der 14.11. ist ein Samstag)
    assert f.frist("2026-09-30") == date(2026, 11, 16)
    assert f.offene_quartale("2026-06-30", date(2026, 11, 16)) == []
    assert f.offene_quartale("2026-06-30", date(2026, 11, 17)) == [pd.Timestamp("2026-09-30")]
    assert f.offene_quartale("2026-03-31", date(2026, 11, 17)) == [pd.Timestamp("2026-06-30"), pd.Timestamp("2026-09-30")]
    dateien = pd.DataFrame({"datei": ["2024q4", "einzel-2024q3", "einzel-2024q4"], "quartale": ["2024q3", "2024q3", "2024q4"]})
    assert f.vorlaeufige_quartale(dateien) == {pd.Timestamp("2024-12-31")}


def test_einzelmeldungen(lage):
    ablage, ordner, tmp = lage
    f.lauf(ablage, tmp / "arb", lokal=ordner)                 # zwei Quartale aus Datensätzen
    verzeichnis(ablage, Q3_VERZEICHNIS)
    quelle = Quelle(q3_dateien())
    p, info, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner, abruf=quelle)
    assert len(quelle.anfragen) == 6                          # verspätete Meldung, Nachtrag, anderes Quartal: nicht geholt
    assert quelle.anfragen[0].endswith("/data/1/Q3-M1-ALT.txt")
    assert info["einzelmeldungen"]["2024q3"]["status"] == {"gelesen": 5, "anderes_quartal": 1}
    assert info["aus_einzelmeldungen"] == ["2024q3"] and info["datensaetze_gelesen"] == 2 and info["datensaetze_neu"] == 0
    fi = ablage.lies_bereinigt("edgar_13f_firmen")
    f3 = fi[fi["periode"] == Q3].set_index("cik")
    assert set(f3["herkunft"]) == {"einzelmeldungen"} and set(fi.loc[fi["periode"] < Q3, "herkunft"]) == {"datensatz"}
    assert f3.loc[[10, 11, 12, 13], "halter"].tolist() == [2, 2, 2, 1] and (f3["manager"] == 4).all()
    # in beiden Quartalen: Manager 1, 2, 6. Firma 13: 0 -> 1; Firma 11: der neue Manager 8 zählt nicht
    assert (f3["manager_beide"] == 3).all() and f3.loc[13, "breite_aenderung"] == pytest.approx(1 / 3)
    assert f3.loc[[10, 11, 12], "breite_aenderung"].tolist() == [0.0, 0.0, 0.0] and f3.loc[12, "beste_idee"] == 1
    neu = p[p["stand"] == "2024q3 Einzelmeldungen"]
    assert len(p) == 34 and len(neu) == 17 and set(p["stand"]) == {"2024q2", "2024q3 Einzelmeldungen"}
    assert (neu["verfuegbar_ab"] == pd.Timestamp("2024-11-15 09:30", tz=ET)).all()
    bestand = pd.read_parquet(ablage.bereinigt / "bereinigt__edgar_13f_bestaende__2024q3.parquet")
    assert set(bestand.columns) == {"filer_cik", "cusip", "stueck", "gewicht"} and X not in set(bestand["cusip"])
    dateien = ablage.lies_bereinigt("edgar_13f_dateien").set_index("datei")
    assert dateien.loc["einzel-2024q3", ["meldungen", "erstmeldungen", "fristgerecht", "quartale"]].tolist() == [6, 5, 4, "2024q3"]

    p2, info, _ = f.lauf(ablage, tmp / "arb", lokal=ordner, abruf=quelle)      # Folgelauf: nichts neu lesen
    assert len(quelle.anfragen) == 6 and len(p2) == 34 and "einzelmeldungen" not in info
    assert info["aus_einzelmeldungen"] == ["2024q3"]

    # der Datensatz der SEC erscheint und ersetzt das Quartal; er kennt zusätzlich Manager 9
    baue_zip(ordner / "01sep2024-30nov2024_form13f.zip",
             [["Q3-M1", "05-NOV-2024", "13F-HR", "1", "30-SEP-2024"], ["Q3-M2", "14-NOV-2024", "13F-HR", "2", "30-SEP-2024"],
              ["Q3-M6", "12-NOV-2024", "13F-HR", "6", "30-SEP-2024"], ["Q3-M8", "14-NOV-2024", "13F-HR", "8", "30-SEP-2024"],
              ["Q3-M9", "13-NOV-2024", "13F-HR", "9", "30-SEP-2024"]],
             [pos("Q3-M1", A2, 100, 10), pos("Q3-M1", C, 100, 10), pos("Q3-M2", A, 300, 30), pos("Q3-M2", B, 30, 3),
              pos("Q3-M2", D, 10, 1), pos("Q3-M8", B, 50, 5), pos("Q3-M9", D, 10, 1)]
             + [pos("Q3-M6", c, 10, 1) for c in FUELL] + [pos("Q3-M6", C, 880, 88)])
    p3, info, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner, abruf=quelle)
    assert len(quelle.anfragen) == 6 and info["aus_einzelmeldungen"] == [] and info["datensaetze_gelesen"] == 3
    assert any("ersetzt die Einzelmeldungen" in h and "(Summe 19 -> 20)" in h for h in hinweise)
    fi = ablage.lies_bereinigt("edgar_13f_firmen")
    f3 = fi[fi["periode"] == Q3].set_index("cik")
    assert set(fi["herkunft"]) == {"datensatz"} and not fi.duplicated(["periode", "cik"]).any()
    assert f3.loc[13, "halter"] == 2 and (f3["manager"] == 5).all() and (f3["manager_beide"] == 3).all()
    assert set(p3["stand"]) == {"2024q2", "2024q3"} and len(p3) == 34
    assert not ablage.lies_bereinigt("edgar_13f_quartal").duplicated(["periode", "cusip"]).any()


def test_einzelmeldungen_erst_nach_der_frist(lage):
    ablage, ordner, tmp = lage
    f.lauf(ablage, tmp / "arb", lokal=ordner)
    verzeichnis(ablage, [zeile for zeile in Q3_VERZEICHNIS if zeile[3] <= "2024-11-14"])     # Stand: letzter Tag der Frist
    quelle = Quelle(q3_dateien())
    p, info, _ = f.lauf(ablage, tmp / "arb", lokal=ordner, abruf=quelle)
    assert quelle.anfragen == [] and info["aus_einzelmeldungen"] == [] and info["juengstes_quartal"] == "2024q2"


def test_einzelmeldungen_unvollstaendig(lage):
    ablage, ordner, tmp = lage
    f.lauf(ablage, tmp / "arb", lokal=ordner)
    verzeichnis(ablage, Q3_VERZEICHNIS)
    dateien = q3_dateien()
    del dateien["Q3-M6"]                                      # eine von sechs Meldungen fehlt: über der Grenze von 2 %
    p, info, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner, abruf=Quelle(dateien))
    assert any("2024q3: Einzelmeldungen unvollständig" in h for h in hinweise)
    assert info["einzelmeldungen"]["2024q3"]["status"]["fehlt"] == 1 and info["juengstes_quartal"] == "2024q2"
    assert set(p["stand"]) == {"2024q2"} and "einzel-2024q3" not in set(ablage.lies_bereinigt("edgar_13f_dateien")["datei"])
    assert not (ablage.bereinigt / "bereinigt__edgar_13f_bestaende__2024q3.parquet").exists()


def test_gegenprobe(lage):
    ablage, ordner, tmp = lage
    verzeichnis(ablage, [[1, "Q2-M1-ALT", "13F-HR", "2024-08-01", "2024-06-30"], [1, "Q2-M1", "13F-HR", "2024-08-05", "2024-06-30"],
                         [2, "Q2-M2", "13F-HR", "2024-08-14", "2024-06-30"], [6, "Q2-M6", "13F-HR", "2024-08-14", "2024-06-30"],
                         [7, "Q2-M7", "13F-HR", "2024-08-15", "2024-06-30"]])
    quelle = Quelle({
        "Q2-M1-ALT": meldung("Q2-M1-ALT", 1, "20240630", "20240801", [z(X, 999, 99)]),
        "Q2-M1": meldung("Q2-M1", 1, "20240630", "20240805", [z(A2, 100, 10), z(A2, 50, 5), z(C, 100, 10),
                                                              z(B, 500, 50, putcall="Put"), z(B, 500, 50, art="PRN")]),
        "Q2-M2": meldung("Q2-M2", 2, "20240630", "20240814", [z(A, 300, 30), z(B, 30, 3)], "ns1"),
        "Q2-M6": meldung("Q2-M6", 6, "20240630", "20240814", [z(c, 10, 1) for c in FUELL] + [z(C, 880, 88)])})
    p, info, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner, abruf=quelle, pruefe_quartal="2024q2")
    v = info["vergleich"]
    assert v["vollstaendig"] and v["halter_gleich"] == 1.0 and v["halter_alt"] == v["halter_neu"] == 17
    assert v["manager_einzel"] == v["manager_datensatz"] == 3 and len(quelle.anfragen) == 4
    assert info["aus_einzelmeldungen"] == [] and len(p) == 17          # die Gegenprobe schreibt nichts
    assert any("Gegenprobe 2024q2" in h for h in hinweise)
