import zipfile

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import cfpb


def baue_zip(pfad, zeilen, kopf=("Date received", "Product", "Company", "Complaint ID")):
    text = ",".join(kopf) + "\n" + "\n".join(",".join(f'"{v}"' for v in z) for z in zeilen) + "\n"
    with zipfile.ZipFile(pfad, "w") as z:
        z.writestr("complaints.csv", text)
    return pfad


@pytest.fixture()
def lage(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", pd.DataFrame({
        "cik": [10, 11, 12], "name": ["ALPHA BANK CORP", "BETA FINANCIAL, INC.", "DOE JANE"],
        "sic": ["6021", "6141", None], "tickers": ["ALB", None, None], "fruehere_namen": ["[]", "[]", "[]"]}))
    zeilen = ([("2024-01-05", "Kredit", "Alpha Bank Corporation", i) for i in range(3)]
              + [("01/20/2024", "Kredit", "ALPHA BANK CORP.", 9)]              # ältere Datumsform
              + [("2024-02-10", "Karte", "Alpha Bank Corporation", 10)]
              + [("2024-01-07", "Karte", "Beta Financial Inc", 20), ("2024-01-08", "Karte", "Unbekannte Firma LLC", 21)]
              + [("2024-03-02", "Karte", "Alpha Bank Corporation", 30)])        # März ist der unvollständige Monat
    return ablage, baue_zip(tmp_path / "c.zip", zeilen), tmp_path


def test_beschwerden_je_monat_und_zuordnung(lage):
    ablage, z, tmp = lage
    p, info, hinweise = cfpb.lauf(ablage, tmp / "arb", zip_pfad=z)
    werte = p.set_index(["cik", "stand"])["wert"].to_dict()
    assert werte == {(10, "2024-01"): 4.0, (10, "2024-02"): 1.0, (11, "2024-01"): 1.0}
    zeile = p[(p["cik"] == 10) & (p["stand"] == "2024-01")].iloc[0]
    # Monatsende 31.01. + 30 Tage = Freitag 01.03. nach Börsenschluss -> Montag 04.03. zur Eröffnung
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2024-03-04 09:30", tz=ET)
    assert zeile["ereignis_zeit"] <= zeile["verfuegbar_ab"]
    assert info["beschwerden"] == 7 and info["trefferquote"]["quote_gewichtet"] == pytest.approx(6 / 7, abs=1e-4)
    assert "der Beschwerden zugeordnet" in hinweise[0]
    tabelle = ablage.lies_bereinigt("cfpb_zuordnung").set_index("firma")
    assert pd.isna(tabelle.loc["Unbekannte Firma LLC", "cik"]) and tabelle.loc["Beta Financial Inc", "cik"] == 11


def test_pflichtspalten(tmp_path):
    z = baue_zip(tmp_path / "k.zip", [("2024-01-05", "x")], kopf=("Datum", "Firma"))
    with pytest.raises(KeyError, match="Pflichtspalten fehlen"):
        cfpb.zaehle_je_monat(z)
