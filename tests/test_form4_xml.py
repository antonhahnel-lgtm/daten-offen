from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from daten_offen.kern import http
from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET, handelbar_ab_serie
from daten_offen.kern.zustand import Zeitbudget
from daten_offen.quellen import edgar_insider as ins
from tests.hilfen import baue_form345_zip


def form4(issuer=1000, owner=2001, name="DOE JANE", direktor="1", officer="0", zehn="0", titel="", plan="0",
          geschaefte=(("2026-10-14", "P", 1000, 30, "A", 4000),), doc="4") -> bytes:
    zeilen = "".join(f"""
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>{tag}</value></transactionDate>
            <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>{stueck}</value></transactionShares>
                <transactionPricePerShare><value>{preis}</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts><sharesOwnedFollowingTransaction><value>{danach}</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
            <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
        </nonDerivativeTransaction>""" for tag, code, stueck, preis, ad, danach in geschaefte)
    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0508</schemaVersion>
    <documentType>{doc}</documentType>
    <periodOfReport>2026-10-14</periodOfReport>
    <issuer><issuerCik>{issuer:010d}</issuerCik><issuerName>ALPHA CORP</issuerName>
        <issuerTradingSymbol>alph</issuerTradingSymbol></issuer>
    <reportingOwner>
        <reportingOwnerId><rptOwnerCik>{owner:010d}</rptOwnerCik><rptOwnerName>{name}</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isDirector>{direktor}</isDirector><isOfficer>{officer}</isOfficer>
            <isTenPercentOwner>{zehn}</isTenPercentOwner><isOther>0</isOther><officerTitle>{titel}</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <aff10b5One>{plan}</aff10b5One>
    <nonDerivativeTable>{zeilen}
    </nonDerivativeTable>
</ownershipDocument>""".encode()


class Antwort:
    def __init__(self, inhalt):
        self.content = inhalt


class Archiv:
    """Liefert Form-4-Dateien nach Adresse; zählt die Abrufe."""

    def __init__(self, dateien: dict[str, bytes | None | Exception]):
        self.dateien, self.aufrufe = dateien, []

    def hole(self, url, erlaube_404=False, **kw):
        self.aufrufe.append(url)
        inhalt = self.dateien[url]
        if isinstance(inhalt, Exception):
            raise inhalt
        return None if inhalt is None else Antwort(inhalt)


def verzeichnis(zeilen):
    df = pd.DataFrame(zeilen, columns=["cik", "accession", "form", "filing_date", "primary_document", "annahme"])
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["annahme_utc"] = pd.to_datetime([pd.Timestamp(a, tz=ET).tz_convert("UTC") for a in df["annahme"]], utc=True) \
        .astype("datetime64[us, UTC]")
    df["verfuegbar_ab"] = handelbar_ab_serie(df["annahme_utc"]).astype("datetime64[us, UTC]")
    df["annahme_geschaetzt"] = False
    df["items"] = None
    return df.drop(columns="annahme")


def adresse(cik, acc, datei):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{datei}"


def test_xml_wird_wie_datensatz_gelesen():
    inhalt = form4(officer="true", titel="Chief Financial Officer", plan="true",
                   geschaefte=(("2026-10-13-05:00", "M", 500, 2, "A", 3500), ("2026-10-14", "S", 500, 31.5, "D", 3000)))
    df = ins.lies_form4_xml(inhalt, "0001999-26-000010", "2026-10-15", "2026q4")
    assert list(df.columns) == ins.SPALTEN and len(df) == 2
    z = df.iloc[1]
    assert z["issuer_cik"] == 1000 and z["owner_cik"] == 2001 and z["issuer_ticker"] == "ALPH"
    assert z["code"] == "S" and z["erwerb"] == "D" and z["stueck"] == 500 and z["preis"] == 31.5
    assert z["wert_usd"] == 15750 and z["bestand_danach"] == 3000
    assert bool(z["ist_officer"]) and bool(z["ist_direktor"]) and not bool(z["ist_zehn_prozent"])
    assert z["plan_10b5_1"] == 1.0 and bool(z["mit_ausuebung"]) and z["herkunft"] == "xml"
    assert df.iloc[0]["trans_date"] == pd.Timestamp("2026-10-13")          # Datum mit Zeitzonenanhang
    assert ins.lies_form4_xml(form4(geschaefte=()), "x", "2026-10-15", "2026q4").empty
    with pytest.raises(ValueError):
        ins.lies_form4_xml(b"<anderesDokument/>", "x", "2026-10-15", "2026q4")


def test_adresse_der_rohdatei():
    assert ins.xml_adresse(1000, "0001999-26-000010", "xslF345X05/wk-form4_1.xml") == \
        adresse(1000, "0001999-26-000010", "wk-form4_1.xml")
    assert ins.xml_adresse(1000, "0001999-26-000010", "form4.xml").endswith("/form4.xml")
    assert ins.xml_adresse(1000, "0001999-26-000010", "form4.htm") is None
    assert ins.xml_adresse(1000, "0001999-26-000010", None) is None


@pytest.fixture()
def lage(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KONTAKT_EMAIL", "test@example.org")
    ablage = Ablage(tmp_path / "aus")
    # amtlicher Datensatz bis 2026q3
    z = baue_form345_zip(tmp_path / "q3.zip",
                         [["D-1", "20-SEP-2026", "", "4", 1000, "ALPHA", "ALPH", "0"]],
                         [["D-1", 2002, "DIR PERSON", "Director", ""]],
                         [["D-1", 1, "Common", "18-SEP-2026", "P", 500, 28, "A", 500, "D"]])
    ablage.schreibe_bereinigt(ins.TABELLE, "2026q3", ins.lies_quartal(z, "2026q3"))
    meld = verzeichnis([
        (1000, "0002001-26-000001", "4", "2026-10-15", "xslF345X05/a.xml", "2026-10-15 16:30"),
        (2001, "0002001-26-000001", "4", "2026-10-15", "xslF345X05/a.xml", "2026-10-15 16:30"),   # dieselbe Meldung beim Meldenden
        (1000, "0002003-26-000002", "4", "2026-10-16", "xslF345X05/b.xml", "2026-10-16 10:00"),
        (1000, "0002004-26-000003", "4", "2026-10-19", "c.htm", "2026-10-19 10:00"),
        (1000, "0002005-26-000004", "4", "2026-10-20", "xslF345X05/d.xml", "2026-10-20 10:00"),
        (1000, "0002006-26-000005", "4/A", "2026-10-21", "xslF345X05/e.xml", "2026-10-21 10:00"),
    ])
    ablage.schreibe_bereinigt("edgar_meldungen", "2026", meld)
    dateien = {
        adresse(1000, "0002001-26-000001", "a.xml"): form4(owner=2001, officer="1", titel="CEO"),
        adresse(1000, "0002003-26-000002", "b.xml"): form4(owner=2003, name="ROE RICHARD",
                                                             geschaefte=(("2026-10-15", "P", 2000, 29, "A", 9000),)),
        adresse(1000, "0002005-26-000004", "d.xml"): None,                       # 404
        adresse(1000, "0002006-26-000005", "e.xml"): b"<kaputt",
    }
    return ablage, Archiv(dateien), meld, tmp_path


def test_laufende_ergaenzung_und_parameter(lage):
    ablage, archiv, meld, tmp = lage
    p, info, hinweise = ins.lauf(ablage, tmp / "arb", ab_jahr=2026, heute=date(2026, 11, 10), abruf=archiv,
                                 lokal=tmp / "leer")
    x = info["xml"][0]
    assert x["quartal"] == "2026q4" and x["neu"] == 2
    assert x["gelesen"] == 2 and x["keine_xml"] == 1 and x["fehlt"] == 1 and x["unlesbar"] == 1
    assert len(archiv.aufrufe) == 4                                           # jede Meldung nur einmal, nicht je CIK
    kauf = p[p["parameter_id"] == "IH1-03"].set_index("stand")
    assert kauf.loc["0002001-26-000001", "wert"] == 30000
    assert kauf.loc["0002001-26-000001", "verfuegbar_ab"] == pd.Timestamp("2026-10-16 09:30", tz=ET)
    cluster = p[p["parameter_id"] == "IH1-01"].set_index("stand")["wert"]
    assert cluster["0002003-26-000002"] == 3                                  # D-1 (Sept.), CEO und Roe in 30 Tagen
    assert set(ins.amtliche_quartale(ablage)) == {"2026q3"}

    # zweiter Lauf: nichts wird erneut abgerufen
    vorher = len(archiv.aufrufe)
    ins.lauf(ablage, tmp / "arb", ab_jahr=2026, heute=date(2026, 11, 10), abruf=archiv, lokal=tmp / "leer")
    assert len(archiv.aufrufe) == vorher


def test_abbruch_am_zeitbudget_und_fortsetzung(lage):
    ablage, archiv, meld, tmp = lage
    _, info, hinweise = ins.lauf(ablage, tmp / "arb", ab_jahr=2026, heute=date(2026, 11, 10), abruf=archiv,
                                 lokal=tmp / "leer", budget=Zeitbudget(0))
    assert info["unvollstaendig"] and (ablage.wurzel / "FORTSETZEN__edgar_insider").exists()
    assert len(archiv.aufrufe) == 0
    p, info, _ = ins.lauf(ablage, tmp / "arb", ab_jahr=2026, heute=date(2026, 11, 10), abruf=archiv, lokal=tmp / "leer")
    assert info["xml"][0]["neu"] == 2 and not p.empty


def test_amtlicher_datensatz_ersetzt_xml(lage):
    ablage, archiv, meld, tmp = lage
    ins.lauf(ablage, tmp / "arb", ab_jahr=2026, heute=date(2026, 11, 10), abruf=archiv, lokal=tmp / "leer")
    assert "2026q4" not in ins.amtliche_quartale(ablage)
    ordner = tmp / "amtlich"
    ordner.mkdir()
    baue_form345_zip(ordner / "2026q4_form345.zip",
                     [["0002001-26-000001", "15-OCT-2026", "", "4", 1000, "ALPHA", "ALPH", "0"]],
                     [["0002001-26-000001", 2001, "DOE JANE", "Officer", "CEO"]],
                     [["0002001-26-000001", 1, "Common", "14-OCT-2026", "P", 1000, 30, "A", 4000, "D"]])
    _, info, _ = ins.lauf(ablage, tmp / "arb", ab_jahr=2026, heute=date(2027, 1, 5), abruf=archiv, lokal=ordner)
    assert "2026q4" in ins.amtliche_quartale(ablage)
    assert all(x["quartal"] != "2026q4" for x in info["xml"])                # ergänzt wird erst ab 2027q1


def test_dauerstoerung_bricht_ab(lage):
    ablage, _, meld, tmp = lage
    kaputt = Archiv({adresse(1000, a, d): http.QuelleNichtErreichbar("gesperrt") for a, d in
                     (("0002001-26-000001", "a.xml"), ("0002003-26-000002", "b.xml"),
                      ("0002005-26-000004", "d.xml"), ("0002006-26-000005", "e.xml"))})
    with pytest.raises(http.QuelleNichtErreichbar):
        ins.ergaenze_aus_xml(ablage, kaputt, Zeitbudget(5), "2026q4", meld, max_fehler=3)
