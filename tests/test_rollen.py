from pathlib import Path

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET, handelbar_ab_serie
from daten_offen.kern.zustand import Zeitbudget
from daten_offen.quellen import edgar_rollen as r

KOPF_13D = """<SEC-DOCUMENT>0002000-24-000001.txt : 20240116
<SEC-HEADER>0002000-24-000001.hdr.sgml : 20240116
<ACCEPTANCE-DATETIME>20240116163012
ACCESSION NUMBER:\t\t0002000-24-000001
CONFORMED SUBMISSION TYPE:\tSC 13D
PUBLIC DOCUMENT COUNT:\t\t2
FILED AS OF DATE:\t\t20240116

SUBJECT COMPANY:\t

\tCOMPANY DATA:\t
\t\tCOMPANY CONFORMED NAME:\t\t\tALPHA CORP
\t\tCENTRAL INDEX KEY:\t\t\t0000001000
\t\tSTANDARD INDUSTRIAL CLASSIFICATION:\tPHARMACEUTICAL PREPARATIONS [2834]

FILED BY:\t\t

\tCOMPANY DATA:\t
\t\tCOMPANY CONFORMED NAME:\t\t\tAKTIVIST LP
\t\tCENTRAL INDEX KEY:\t\t\t0000002000
</SEC-HEADER>
"""
KOPF_144 = KOPF_13D.replace("SC 13D", "144").replace("FILED BY:", "REPORTING-OWNER:").replace("0000002000", "0000002001")


class Archiv:
    def __init__(self, texte):
        self.texte, self.aufrufe = texte, []

    def hole_anfang(self, url, anzahl=12000, erlaube_404=False):
        self.aufrufe.append(url)
        t = self.texte.get(url.rsplit("/", 1)[1].removesuffix(".txt"))
        return None if t is None else t.encode()


def test_kopf():
    assert r.lies_kopf(KOPF_13D) == (1000, 2000)
    assert r.lies_kopf(KOPF_144) == (1000, 2001)
    assert r.lies_kopf("kein Kopf") == (None, None)


@pytest.fixture()
def lage(tmp_path: Path):
    ablage = Ablage(tmp_path / "aus")
    zeilen = [  # jede Meldung steht unter Einreicher und betroffener Firma
        (2000, "0002000-24-000001", "SC 13D", "2024-01-16", "2024-01-16 16:30"),
        (1000, "0002000-24-000001", "SC 13D", "2024-01-16", "2024-01-16 16:30"),
        (2000, "0002000-24-000002", "SC 13D/A", "2024-02-01", "2024-02-01 10:00"),
        (2001, "0002001-24-000003", "144", "2024-03-01", "2024-03-01 11:00"),
        (2000, "0002000-23-000009", "SCHEDULE 13D", "2023-06-01", "2023-06-01 09:00"),
        (2000, "0002000-23-000008", "SC 13D", "2023-05-01", "2023-05-01 09:00"),
    ]
    m = pd.DataFrame(zeilen, columns=["cik", "accession", "form", "filing_date", "annahme"])
    m["filing_date"] = pd.to_datetime(m["filing_date"])
    m["annahme_utc"] = pd.to_datetime([pd.Timestamp(a, tz=ET).tz_convert("UTC") for a in m["annahme"]], utc=True) \
        .astype("datetime64[us, UTC]")
    m["verfuegbar_ab"] = handelbar_ab_serie(m["annahme_utc"]).astype("datetime64[us, UTC]")
    for jahr, teil in m.drop(columns="annahme").groupby(m["filing_date"].dt.year):
        ablage.schreibe_bereinigt("edgar_meldungen", str(jahr), teil)
    archiv = Archiv({"0002000-24-000001": KOPF_13D, "0002000-24-000002": KOPF_13D.replace("SC 13D", "SC 13D/A"),
                     "0002001-24-000003": KOPF_144, "0002000-23-000009": "ohne Abschnitte",
                     "0002000-23-000008": None})
    return ablage, archiv


def test_rollen_und_parameter(lage):
    ablage, archiv = lage
    p, info, hinweise = r.lauf(ablage, abruf=archiv, budget=Zeitbudget(5))
    assert len(archiv.aufrufe) == 5 and info["gelesen"] == 3 and info["ohne_rolle"] == 1 and info["fehlt"] == 1
    z = p.set_index("stand")
    assert z.loc["0002000-24-000001", "parameter_id"] == "IH5-01" and z.loc["0002000-24-000001", "cik"] == 1000
    assert z.loc["0002000-24-000001", "verfuegbar_ab"] == pd.Timestamp("2024-01-17 09:30", tz=ET)
    assert z.loc["0002000-24-000002", "parameter_id"] == "IH5-02"
    assert z.loc["0002001-24-000003", "parameter_id"] == "IH1-14"
    assert len(p) == 3                                   # der Einreicher (2000) erhält kein Ereignis
    r.lauf(ablage, abruf=archiv, budget=Zeitbudget(5))
    assert len(archiv.aufrufe) == 5                      # nichts erneut gelesen


def test_neueste_zuerst_und_fortsetzung(lage):
    ablage, archiv = lage

    class EinAbruf(Zeitbudget):
        def __init__(self):
            self.n = 0

        def abgelaufen(self):
            self.n += 1
            return self.n > 1

    p, info, hinweise = r.lauf(ablage, modus="rueckwaerts", abruf=archiv, budget=EinAbruf())
    assert archiv.aufrufe[0].endswith("0002001-24-000003.txt") and info["offen"] == 4
    assert (ablage.wurzel / "FORTSETZEN__edgar_rollen").exists()
    assert list(p["parameter_id"]) == ["IH1-14"]
    p, info, _ = r.lauf(ablage, modus="rueckwaerts", abruf=archiv, budget=Zeitbudget(5))
    assert info["offen"] == 0 and len(p) == 3
