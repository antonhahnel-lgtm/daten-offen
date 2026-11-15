import io
import re
import zipfile
from datetime import date
from types import SimpleNamespace

import pandas as pd

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import rueckrufe as r


def nhtsa_zip(zeilen) -> bytes:
    """Sammeldatei der NHTSA: tabulatorgetrennt, 29 Felder, mehrere Zeilen je Kampagne."""
    text = ""
    for i, (kampagne, hersteller, stueck, eingang, erfasst) in enumerate(zeilen):
        felder = [""] * 29
        felder[0], felder[1], felder[7], felder[11], felder[15], felder[16] = str(i), kampagne, hersteller, str(stueck), eingang, erfasst
        text += "\t".join(felder) + "\r\n"
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("FLAT_RCL.txt", text.encode("latin-1"))
    return puffer.getvalue()


NHTSA = {
    "FLAT_RCL_PRE_2010.zip": nhtsa_zip([("05V100000", "FORD MOTOR COMPANY", 300, "20050110", "20050111")]),
    "FLAT_RCL_POST_2010.zip": nhtsa_zip([
        ("20V100000", "Ford Motor Company", 1000, "20200301", "20200303"), ("20V100000", "Ford Motor Company", 500, "20200301", "20200303"),
        ("19V200000", "Jayco, Inc.", 40, "20190105", "20250101"),              # Erfassungsdatum unbrauchbar: Eingang + 6 Tage
        ("15V300000", "Jayco, Inc.", 10, "20150505", "20150506"),              # vor der Übernahme durch Thor
    ]),
}
CPSC = [
    {"RecallID": 1, "RecallDate": "2026-11-12T00:00:00", "Title": "Alpha Corp Recalls Fire Pits Due to Burn Hazard", "Manufacturers": [],
     "Importers": [{"Name": "Alpha Corp, of Winston-Salem, North Carolina"}], "Distributors": [],
     "Retailers": [{"Name": "Sold At:\nBeta Inc. and other stores"}], "Products": [{"NumberOfUnits": "About 265,000"}, {"NumberOfUnits": "1,200"}]},
    {"RecallID": 2, "RecallDate": "2001-05-04T00:00:00", "Title": "CPSC, Beta Inc. Announce Recall of Toys",
     "Manufacturers": [{"Name": "Beta Inc."}], "Importers": [], "Distributors": [], "Products": []},
    {"RecallID": 3, "RecallDate": None, "Title": "Ohne Datum", "Manufacturers": [{"Name": "Alpha Corp"}]},
]
FDA = {
    ("drug", 2026): [
        {"event_id": "900", "recalling_firm": "Hospira Inc.", "classification": "Class II", "report_date": "20261104"},
        {"event_id": "900", "recalling_firm": "Hospira Inc.", "classification": "Class I", "report_date": "20261111"},
    ],
    ("device", 2025): [{"event_id": "800", "recalling_firm": "Unbekannt GmbH", "classification": "Not Yet Classified", "report_date": "20250205"}],
}


class Quelle:
    def __init__(self, fda=None):
        self.fda, self.anfragen = FDA if fda is None else fda, []

    def hole(self, url, erlaube_404=False, **kw):
        self.anfragen.append(url)
        if "nhtsa" in url:
            return SimpleNamespace(content=NHTSA[url.rsplit("/", 1)[1]])
        if "saferproducts" in url:
            return SimpleNamespace(json=lambda: CPSC)
        bereich, jahr, skip = re.search(r"gov/(\w+)/enforcement.*\[(\d{4})0101.*skip=(\d+)", url).groups()
        zeilen = self.fda.get((bereich, int(jahr)))
        if not zeilen:
            return None
        return SimpleNamespace(json=lambda: {"meta": {"results": {"total": len(zeilen)}}, "results": zeilen if skip == "0" else []})


def firmen():
    return pd.DataFrame({"cik": [37996, 730263, 10, 11, 78003],
                         "name": ["FORD MOTOR CO", "THOR INDUSTRIES INC", "ALPHA CORP", "BETA INC", "PFIZER INC"],
                         "tickers": ["F", "THO", "ALP", None, "PFE"], "sic": ["3711"] * 5, "fruehere_namen": ["[]"] * 5})


def test_einzelne_quellen():
    n = r.lies_nhtsa(NHTSA["FLAT_RCL_POST_2010.zip"]).set_index("kennung")
    assert n.loc["20V100000", ["firma", "stueck", "art"]].tolist() == ["Ford Motor Company", 1000.0, 1]
    assert n.loc["20V100000", "tag"] == pd.Timestamp("2020-03-03") and n.loc["19V200000", "tag"] == pd.Timestamp("2019-01-11")
    assert r.cpsc_firmen(CPSC[0]) == ["Alpha Corp"] and r.cpsc_firmen(CPSC[1]) == ["CPSC, Beta Inc.", "Beta Inc."]
    c = r.lies_cpsc(CPSC)
    assert c[["kennung", "firma", "stueck"]].values.tolist()[0] == ["1", "Alpha Corp", 265000.0] and len(c) == 3
    f = r.lies_fda(FDA[("drug", 2026)], "drug")
    assert f[["quelle", "kennung", "firma", "art", "klasse"]].values.tolist() == [["fda_drug", "900", "Hospira Inc.", 3, 1]]
    assert f["tag"].iloc[0] == pd.Timestamp("2026-11-04")                    # erster Bericht, schwerste Klasse
    assert r.lies_fda(FDA[("device", 2025)], "device")["klasse"].iloc[0] == 0


def test_lauf(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    quelle = Quelle()
    p, info, hinweise = r.lauf(ablage, abruf=quelle, heute=date(2026, 11, 15))
    assert info["ereignisse"] == {"cpsc": 2, "fda_device": 1, "fda_drug": 1, "nhtsa": 4} and info["fda_jahre_gelesen"] == [2004, 2026]
    assert sum("enforcement" in a for a in quelle.anfragen) == 3 * 23        # ohne Bestand alle Jahre je Bereich
    werte = {(int(z.cik), z.stand): z.wert for z in p.itertuples()}
    # Jayco zählt erst ab der Übernahme bei Thor; Hospira gehört seit 2015 zu Pfizer; „CPSC, Beta Inc.“ findet nichts
    assert werte == {(37996, "nhtsa:05V100000"): 1.0, (37996, "nhtsa:20V100000"): 1.0, (730263, "nhtsa:19V200000"): 1.0,
                     (10, "cpsc:1"): 2.0, (11, "cpsc:2"): 2.0, (78003, "fda_drug:900"): 3.0}
    zeile = p[p["stand"] == "cpsc:1"].iloc[0]
    assert zeile["ereignis_zeit"] == pd.Timestamp("2026-11-12 00:00", tz=ET)
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2026-11-13 09:30", tz=ET) and zeile["parameter_id"] == "GA3-02"
    e = ablage.lies_bereinigt("rueckrufe_ereignisse")
    assert list(e.columns) == r.SPALTEN and len(e) == 9
    z = ablage.lies_bereinigt("rueckrufe_zuordnung")
    jayco = z[z["firma"] == "Jayco, Inc."]
    assert jayco["cik"].isna().tolist() == [True, False] and jayco["art"].tolist() == ["keiner", "tochter"]
    assert int(jayco["cik"].iloc[1]) == 730263 and str(jayco["gilt_ab"].iloc[1].date()) == "2016-06-30"
    assert not [h for h in hinweise if "Mütter" in h and "THOR" in h]

    # Folgelauf: der FDA-Bestand bleibt, neu gelesen werden nur die beiden jüngsten Jahre; ein neues Ereignis kommt hinzu
    fda = {**FDA, ("drug", 2026): FDA[("drug", 2026)] + [{"event_id": "901", "recalling_firm": "Pfizer Inc.", "classification": "Class III",
                                                           "report_date": "20261111"}]}
    quelle = Quelle(fda)
    p2, info, _ = r.lauf(ablage, abruf=quelle, heute=date(2026, 11, 15))
    assert sum("enforcement" in a for a in quelle.anfragen) == 3 * 2 and info["fda_jahre_gelesen"] == [2025, 2026]
    assert len(p2) == len(p) + 1 and info["ereignisse"]["fda_drug"] == 2 and info["ereignisse"]["fda_device"] == 1
    assert len(ablage.lies_bereinigt("rueckrufe_fda")) == 3
