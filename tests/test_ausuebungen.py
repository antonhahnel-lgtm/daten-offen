import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET, handelbar_ab_serie
from daten_offen.kern.zustand import Zeitbudget
from daten_offen.quellen import edgar_ausuebungen as a
from tests.hilfen import OWN_KOPF, SUB_KOPF, tsv

DT_KOPF = ["ACCESSION_NUMBER", "DERIV_TRANS_SK", "SECURITY_TITLE", "CONV_EXERCISE_PRICE", "TRANS_DATE", "TRANS_CODE",
           "TRANS_SHARES", "TRANS_ACQUIRED_DISP_CD", "EXCERCISE_DATE", "EXPIRATION_DATE", "UNDLYNG_SEC_SHARES"]
ND_KOPF = ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "SECURITY_TITLE", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
           "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"]

SUB = [["0001-26-000001", "03-FEB-2026", "02-FEB-2026", "4", "1000", "ALPHA CORP", "ALPH", "0"],
       ["0001-26-000002", "04-FEB-2026", "02-FEB-2026", "4", "1000", "ALPHA CORP", "ALPH", "0"],
       ["0001-26-000003", "10-FEB-2026", "02-FEB-2026", "4/A", "1000", "ALPHA CORP", "ALPH", "0"]]
OWN = [["0001-26-000001", "2001", "DOE JANE", "Director,Officer", "President and CEO"],
       ["0001-26-000002", "2002", "ROE RICHARD", "Director", ""],
       ["0001-26-000003", "2001", "DOE JANE", "Director,Officer", "President and CEO"]]
DT = [["0001-26-000001", 1, "Stock Option (right to buy)", "10.0", "02-FEB-2026", "M", "1000.0", "D", "", "02-AUG-2026", "1000.0"],
      ["0001-26-000001", 2, "Employee Stock Option", "12.0", "02-FEB-2026", "M", "500.0", "D", "01-JAN-2020", "02-FEB-2030", "500.0"],
      ["0001-26-000001", 3, "Restricted Stock Units", "0.0", "02-FEB-2026", "M", "300.0", "D", "", "", "300.0"],
      ["0001-26-000001", 4, "Warrants (right to buy)", "5.0", "02-FEB-2026", "X", "100.0", "D", "", "02-FEB-2027", "100.0"],
      ["0001-26-000001", 5, "Stock Option (right to buy)", "10.0", "02-FEB-2026", "A", "800.0", "A", "", "02-FEB-2036", "800.0"],
      ["0001-26-000001", 6, "Stock Option (right to buy)", "10.0", "02-FEB-2026", "M", "50.0", "D", "", "01-JAN-2026", "50.0"],
      ["0001-26-000002", 7, "Director Stock Option", "20.0", "02-FEB-2026", "M", "200.0", "D", "", "02-FEB-2031", "200.0"],
      ["0001-26-000003", 8, "Stock Option (right to buy)", "10.0", "02-FEB-2026", "M", "1000.0", "D", "", "02-AUG-2026", "1000.0"]]
ND = [["0001-26-000001", 1, "Common Stock", "02-FEB-2026", "M", "1500.0", "10.0", "A"],
      ["0001-26-000001", 2, "Common Stock", "02-FEB-2026", "S", "500.0", "30.0", "D"],
      ["0001-26-000001", 3, "Common Stock", "02-FEB-2026", "F", "100.0", "31.0", "D"],
      ["0001-26-000001", 4, "Common Stock", "05-FEB-2026", "S", "100.0", "99.0", "D"]]


def baue_zip(pfad: Path, sub=SUB, own=OWN, dt=DT, nd=ND) -> Path:
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SUBMISSION.tsv", tsv(SUB_KOPF, sub))
        z.writestr("REPORTINGOWNER.tsv", tsv(OWN_KOPF, own))
        z.writestr("DERIV_TRANS.tsv", tsv(DT_KOPF, dt))
        z.writestr("NONDERIV_TRANS.tsv", tsv(ND_KOPF, nd))
    return pfad


def form4(titel="Chief Executive Officer", tranchen=(("Stock Option (right to buy)", "8.00", "2026-10-13", "M", 400, "D", "2027-01-31"),),
          geschaefte=(("2026-10-13", "S", 400, 25.0, "D"),)) -> bytes:
    deriv = "".join(f"""
        <derivativeTransaction>
            <securityTitle><value>{w}</value></securityTitle>
            <conversionOrExercisePrice><value>{basis}</value></conversionOrExercisePrice>
            <transactionDate><value>{tag}</value></transactionDate>
            <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode></transactionCoding>
            <transactionAmounts><transactionShares><value>{stueck}</value></transactionShares>
                <transactionPricePerShare><value>0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode></transactionAmounts>
            <exerciseDate><footnoteId id="F1"/></exerciseDate>
            <expirationDate><value>{verfall}</value></expirationDate>
            <underlyingSecurity><underlyingSecurityTitle><value>Common Stock</value></underlyingSecurityTitle>
                <underlyingSecurityShares><value>{stueck}</value></underlyingSecurityShares></underlyingSecurity>
        </derivativeTransaction>""" for w, basis, tag, code, stueck, ad, verfall in tranchen)
    nonderiv = "".join(f"""
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>{tag}</value></transactionDate>
            <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode></transactionCoding>
            <transactionAmounts><transactionShares><value>{stueck}</value></transactionShares>
                <transactionPricePerShare><value>{preis}</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode></transactionAmounts>
        </nonDerivativeTransaction>""" for tag, code, stueck, preis, ad in geschaefte)
    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <documentType>4</documentType>
    <issuer><issuerCik>0000001000</issuerCik><issuerName>ALPHA CORP</issuerName></issuer>
    <reportingOwner>
        <reportingOwnerId><rptOwnerCik>0000002001</rptOwnerCik><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>{titel}</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>{nonderiv}</nonDerivativeTable>
    <derivativeTable>{deriv}</derivativeTable>
</ownershipDocument>""".encode()


def test_datensatz_lesen(tmp_path):
    df = a.lies_quartal(baue_zip(tmp_path / "2026q1_form345.zip"), "2026q1")
    assert list(df.columns) == a.SPALTEN
    # RSU (Basis 0), Optionsschein, Zuteilung (A) und Verfall vor der Ausübung fallen weg
    assert df["zeile"].tolist() == [0, 1, 6, 7]
    z = df.iloc[0]
    assert (z["issuer_cik"], z["owner_cik"], z["code"], z["basis"], z["stueck"]) == (1000, 2001, "M", 10.0, 1000.0)
    assert bool(z["ist_ceo"]) and bool(z["ist_officer"]) and z["herkunft"] == "datensatz"
    assert z["restlaufzeit"] == pytest.approx(181 / 365.25)
    assert z["kurs"] == pytest.approx((500 * 30 + 100 * 31) / 600)                # S und F am Ausübungstag, nicht am 05.02.
    assert z["kurs_zu_basis"] == pytest.approx(z["kurs"] / 10)
    assert df.iloc[1]["verfall"] == pd.Timestamp("2030-02-02")
    d = df.iloc[2]
    assert not bool(d["ist_ceo"]) and pd.isna(d["kurs"]) and d["basis"] == 20


def test_xml_lesen():
    df = a.lies_xml(form4(), "0001-26-000099", "2026-10-14", "2026q4")
    assert list(df.columns) == a.SPALTEN and len(df) == 1
    z = df.iloc[0]
    assert (z["issuer_cik"], z["basis"], z["stueck"], z["kurs"], z["herkunft"]) == (1000, 8.0, 400.0, 25.0, "xml")
    assert bool(z["ist_ceo"]) and z["restlaufzeit"] == pytest.approx(110 / 365.25)
    assert a.lies_xml(form4(tranchen=()), "x", "2026-10-14", "2026q4").empty
    assert a.lies_xml(form4(titel="Chief Financial Officer"), "x", "2026-10-14", "2026q4")["ist_ceo"].tolist() == [False]


def meldungen(zeilen):
    df = pd.DataFrame(zeilen, columns=["cik", "accession", "form", "filing_date", "primary_document", "annahme"])
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["annahme_utc"] = pd.to_datetime([pd.Timestamp(x, tz=ET).tz_convert("UTC") for x in df["annahme"]], utc=True).astype("datetime64[us, UTC]")
    df["verfuegbar_ab"] = handelbar_ab_serie(df["annahme_utc"]).astype("datetime64[us, UTC]")
    return df.drop(columns="annahme")


class Archiv:
    def __init__(self, dateien):
        self.dateien, self.aufrufe = dateien, []

    def hole(self, url, erlaube_404=False, **kw):
        self.aufrufe.append(url)
        inhalt = self.dateien.get(url)
        return None if inhalt is None else type("A", (), {"content": inhalt})()


def test_lauf(tmp_path):
    lokal = tmp_path / "zips"
    lokal.mkdir()
    baue_zip(lokal / "2026q1_form345.zip")
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_meldungen", "2026", meldungen([
        (1000, "0001-26-000001", "4", "2026-02-03", "x.xml", "2026-02-03 21:15"),
        (1000, "0001-26-000002", "4", "2026-02-04", "x.xml", "2026-02-04 11:00"),
        (1000, "0001-26-000099", "4", "2026-10-14", "xslF345X05/f4.xml", "2026-10-14 10:30"),
        (1000, "0001-26-000098", "4", "2026-10-14", "xslF345X05/g4.xml", "2026-10-14 10:31")]))
    # Quartal ohne Datensatz: edgar_insider kennt zwei Meldungen mit Ausübung und eine ohne
    ablage.schreibe_bereinigt("insider_transaktionen", "2026q3", pd.DataFrame(
        {"accession": ["0001-26-000099", "0001-26-000098", "0001-26-000097"], "code": ["M", "M", "P"]}))
    url = "https://www.sec.gov/Archives/edgar/data/1000/000126000099/f4.xml"
    archiv = Archiv({url: form4()})
    p, info, hinweise = a.lauf(ablage, tmp_path / "arbeit", ab_jahr=2026, heute=date(2026, 11, 15), abruf=archiv, lokal=lokal)
    assert info["gelesen"] == ["2026q1"] and info["unveroeffentlicht"] == ["2026q2", "2026q3"]
    assert info["xml"] == [{"quartal": "2026q3", "offen": 0, "abgebrochen": False, "gelesen": 1, "fehlt": 1}]
    assert len(archiv.aufrufe) == 2 and info["tranchen"] == 5
    # je Meldung des CEO die kürzeste Restlaufzeit; der Nachtrag mit gleichen Angaben entfällt; der Direktor zählt nicht
    assert p["stand"].tolist() == ["0001-26-000001", "0001-26-000099"] and set(p["parameter_id"]) == {"UA6-02"}
    assert p["wert"].round(4).tolist() == [round(181 / 365.25, 4), round(110 / 365.25, 4)]
    assert p["verfuegbar_ab"].iloc[0] == pd.Timestamp("2026-02-04 09:30", tz=ET)       # Annahme nach Börsenschluss
    assert p["ereignis_zeit"].iloc[0] == pd.Timestamp("2026-02-02 00:00", tz=ET)
    assert p["verfuegbar_ab"].iloc[1] == pd.Timestamp("2026-10-14 10:30", tz=ET)

    # Folgelauf: der Datensatz wird nicht erneut gelesen, gelesene Form-4-Dateien nicht erneut abgerufen
    archiv = Archiv({url: form4()})
    p2, info, _ = a.lauf(ablage, tmp_path / "arbeit", ab_jahr=2026, heute=date(2026, 11, 15), abruf=archiv, lokal=lokal)
    assert info["gelesen"] == [] and archiv.aufrufe == [] and len(p2) == len(p)

    # erscheint der Datensatz des Quartals, ersetzt er die Form-4-Dateien
    baue_zip(lokal / "2026q3_form345.zip", sub=[["0001-26-000099", "14-OCT-2026", "13-OCT-2026", "4", "1000", "ALPHA CORP", "ALPH", "0"]],
             own=[["0001-26-000099", "2001", "DOE JANE", "Officer", "CEO"]],
             dt=[["0001-26-000099", 1, "Stock Option", "8.0", "13-OCT-2026", "M", "400.0", "D", "", "31-JAN-2027", "400.0"]],
             nd=[["0001-26-000099", 1, "Common Stock", "13-OCT-2026", "S", "400.0", "25.0", "D"]])
    p3, info, _ = a.lauf(ablage, tmp_path / "arbeit", ab_jahr=2026, heute=date(2026, 11, 15), abruf=Archiv({}), lokal=lokal)
    assert info["gelesen"] == ["2026q3"] and info["xml"] == [] and info["quartale_datensatz"] == 2
    assert not (ablage.bereinigt / "bereinigt__insider_ausuebungen_stand__2026q3.parquet").exists()
    assert set(ablage.lies_bereinigt("insider_ausuebungen")["herkunft"]) == {"datensatz"}
    assert p3["stand"].tolist() == p["stand"].tolist()


def test_zeitbudget(tmp_path):
    lokal = tmp_path / "zips"
    lokal.mkdir()
    baue_zip(lokal / "2026q1_form345.zip")
    ablage = Ablage(tmp_path / "aus")
    p, info, hinweise = a.lauf(ablage, tmp_path / "arbeit", ab_jahr=2026, heute=date(2026, 11, 15), lokal=lokal, budget=Zeitbudget(0))
    assert info["unvollstaendig"] and p.empty and (ablage.wurzel / "FORTSETZEN__edgar_ausuebungen").exists()
