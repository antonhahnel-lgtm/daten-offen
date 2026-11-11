import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import klinik as k


def studie(nct, sponsor, phasen, status="COMPLETED", klasse="INDUSTRY", pcd="2024-01-15", pcd_typ="ACTUAL",
           ergebnis=None):
    s = {"protocolSection": {
        "identificationModule": {"nctId": nct},
        "statusModule": {"overallStatus": status, "primaryCompletionDateStruct": {"date": pcd, "type": pcd_typ}},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor, "class": klasse}},
        "designModule": {"phases": phasen}}, "hasResults": ergebnis is not None}
    if ergebnis:
        s["protocolSection"]["statusModule"]["resultsFirstPostDateStruct"] = {"date": ergebnis, "type": "ACTUAL"}
    return s


class Register:
    def __init__(self, seiten):
        self.seiten, self.aufrufe = seiten, []

    def hole_json(self, url, params=None):
        self.aufrufe.append(dict(params))
        assert params["filter.advanced"] == "AREA[Phase](PHASE2 OR PHASE3)" and params["pageSize"] == 1000
        i = int(params.get("pageToken", 0))
        antwort = {"studies": self.seiten[i]}
        if i + 1 < len(self.seiten):
            antwort["nextPageToken"] = str(i + 1)
        return antwort


class Fda:
    def __init__(self, antraege):
        self.antraege = antraege

    def hole_json(self, url, params=None):
        return {"results": {"drug": {"drugsfda": {"partitions": [{"file": "https://download.open.fda.gov/x.json.zip"}]}}}}

    def hole_datei(self, url, ziel, erlaube_404=False):
        Path(ziel).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ziel, "w") as z:
            z.writestr("drug-drugsfda-0001-of-0001.json", json.dumps({"results": self.antraege}))
        return Path(ziel)


ANTRAEGE = [
    {"application_number": "NDA000001", "sponsor_name": "ALPHA PHARMA",
     "submissions": [{"submission_type": "ORIG", "submission_status": "AP", "submission_status_date": "20240315",
                      "review_priority": "PRIORITY"},
                     {"submission_type": "SUPPL", "submission_status": "AP", "submission_status_date": "20240601"}]},
    {"application_number": "NDA000002", "sponsor_name": "BETA BIO",
     "submissions": [{"submission_type": "ORIG", "submission_status": "TA", "submission_status_date": "20240101"}]},
    {"application_number": "NDA000003", "sponsor_name": "FREMDE FIRMA",
     "submissions": [{"submission_type": "ORIG", "submission_status": "AP", "submission_status_date": "20230105",
                      "review_priority": "STANDARD"}]},
]


@pytest.fixture()
def lage(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", pd.DataFrame({
        "cik": [10, 11, 12], "name": ["ALPHA PHARMA INC", "Beta Bio Corp", "DOE JANE"], "sic": ["2834", "2836", None],
        "tickers": ["ALPH", "BETA", None], "fruehere_namen": ["[]", "[]", "[]"]}))
    seiten = [[studie("NCT1", "Alpha Pharma, Inc.", ["PHASE3"], ergebnis="2024-03-08"),
               studie("NCT2", "Beta Bio", ["PHASE2"], status="RECRUITING", pcd="2025-06", pcd_typ="ESTIMATED")],
              [studie("NCT3", "Universität X", ["PHASE2"], klasse="OTHER", ergebnis="2024-02-01"),
               studie("NCT4", "Beta Bio", ["PHASE1", "PHASE2"], ergebnis="2023-11-20")]]
    return ablage, seiten, tmp_path


def test_studien_und_zulassungen(lage):
    ablage, seiten, tmp = lage
    register = Register(seiten)
    p, info, hinweise = k.lauf(ablage, tmp / "arb", abruf_ct=register, abruf_fda=Fda(ANTRAEGE), heute=date(2024, 6, 3))
    assert len(register.aufrufe) == 2 and info["studien"] == 4                         # zwei Seiten gelesen
    s = p[p["parameter_id"] == "GA1-04"].set_index("stand")
    assert s["wert"].to_dict() == {"NCT1": 3.0, "NCT4": 2.0}                           # NCT3: kein Industrie-Sponsor
    assert s.loc["NCT1", "cik"] == 10 and s.loc["NCT4", "cik"] == 11
    assert s.loc["NCT1", "verfuegbar_ab"] == pd.Timestamp("2024-03-11 09:30", tz=ET)   # Freitag -> Montag
    z = p[p["parameter_id"] == "GA1-08"].set_index("stand")
    assert z["wert"].to_dict() == {"NDA000001": 2.0}                                   # nur Erstzulassung, zugeordnet
    assert z.loc["NDA000001", "verfuegbar_ab"] == pd.Timestamp("2024-03-18 09:30", tz=ET)
    assert info["zulassungen"] == 3 and info["aenderungen"] == 0
    assert any("Erster Lauf" in h for h in hinweise)
    assert (p["ereignis_zeit"] <= p["verfuegbar_ab"]).all()


def test_aenderungsprotokoll(lage):
    ablage, seiten, tmp = lage
    k.lauf(ablage, tmp / "arb", abruf_ct=Register(seiten), abruf_fda=Fda(ANTRAEGE), heute=date(2024, 6, 3))
    spaeter = [[studie("NCT1", "Alpha Pharma, Inc.", ["PHASE3"], ergebnis="2024-03-08"),
                studie("NCT2", "Beta Bio", ["PHASE2"], status="TERMINATED", pcd="2024-06-01", pcd_typ="ACTUAL"),
                studie("NCT4", "Beta Bio", ["PHASE1", "PHASE2"], ergebnis="2023-11-20"),
                studie("NCT5", "Beta Bio", ["PHASE3"], status="RECRUITING")]]
    _, info, _ = k.lauf(ablage, tmp / "arb", abruf_ct=Register(spaeter), abruf_fda=Fda(ANTRAEGE), heute=date(2024, 6, 4))
    protokoll = ablage.lies_bereinigt(k.AENDERUNGEN)
    assert info["aenderungen"] == 3 and set(protokoll["nct"]) == {"NCT2"}             # neue Studie ist keine Änderung
    z = protokoll.set_index("feld")
    assert z.loc["status", "alt"] == "RECRUITING" and z.loc["status", "neu"] == "TERMINATED"
    assert z.loc["pcd_typ", "neu"] == "ACTUAL" and (protokoll["abruf_datum"] == pd.Timestamp("2024-06-04")).all()
    # dritter Lauf ohne Änderung: Protokoll bleibt erhalten
    k.lauf(ablage, tmp / "arb", abruf_ct=Register(spaeter), abruf_fda=Fda(ANTRAEGE), heute=date(2024, 6, 5))
    assert len(ablage.lies_bereinigt(k.AENDERUNGEN)) == 3


def test_verzeichnis_ohne_teile(lage):
    ablage, seiten, tmp = lage

    class Leer(Fda):
        def hole_json(self, url, params=None):
            return {"results": {}}

    with pytest.raises(KeyError, match="partitions"):
        k.lade_zulassungen(Leer([]), tmp)


def test_sponsorabgleich():
    firmen = pd.DataFrame({
        "cik": [200406, 59478, 30, 31, 32, 33, 34, 35],
        "name": ["JOHNSON & JOHNSON", "ELI LILLY & Co", "ASTRAZENECA PLC", "NOVARTIS AG", "BAUSCH HEALTH COMPANIES INC",
                 "BAUSCH & LOMB CORP", "ICON PLC", "Merck & Co., Inc."],
        "sic": ["2834", "2834", "2834", "2834", "2834", "3851", "8731", "2834"],
        "tickers": ["JNJ", "LLY", "AZN", "NVS", "BHC", "BLCO", "ICLR", "MRK"],
        "fruehere_namen": ["[]"] * 8})
    a = k.Sponsorabgleich(firmen)
    assert a.finde("Johnson & Johnson") == (200406, 1.0, "exakt")
    assert a.finde("JANSSEN PHARMS") == (200406, 0.95, "tochter")
    assert a.finde("LILLY") == (59478, 0.95, "tochter")
    assert a.finde("ASTRAZENECA AB") == (30, 0.90, "anfang")
    assert a.finde("Novartis Pharmaceuticals") == (31, 0.90, "anfang")
    assert a.finde("NOVARTIS PHARMS CORP") == (31, 0.90, "anfang")
    assert a.finde("BAUSCH")[0] is None and a.finde("BAUSCH")[2] == "mehrdeutig"      # zwei Firmen beginnen so
    assert a.finde("ICON Bioscience Inc")[0] is None                                  # ICON ist zu kurz für einen Anfang
    assert a.finde("Merck KGaA, Darmstadt, Germany")[0] is None                       # anderes Unternehmen
    assert a.finde("MERCK") == (35, 0.90, "anfang")
    assert a.finde("Unbekannt Pharma")[0] is None
    z = a.ordne_zu(pd.Series(["LILLY", None, "ASTRAZENECA AB"]))
    assert z["cik"].tolist()[0] == 59478 and pd.isna(z["cik"].tolist()[1]) and z["art"].tolist()[2] == "anfang"
