import json
from pathlib import Path

import pandas as pd
import pytest

from daten_offen import lauf as lauf_modul
from daten_offen.datenblaetter import text as datenblatt_text
from daten_offen.kern import schema
from daten_offen.kern.pruefung import pruefe_parameter
from daten_offen.kern.zustand import Zeitbudget, Zustand
from daten_offen.quellen import edgar_ereignisse, edgar_insider  # noqa: F401
from tests.hilfen import baue_companyfacts_zip, baue_form345_zip, baue_submissions_zip


def _df(**kw):
    basis = {"cik": [1, 1], "parameter_id": ["IH1-03", "IH1-03"],
             "ereignis_zeit": pd.to_datetime(["2024-01-02", "2024-01-03"], utc=True),
             "verfuegbar_ab": pd.to_datetime(["2024-01-03", "2024-01-04"], utc=True),
             "wert": [1.0, 2.0], "stand": ["a", "b"]}
    basis.update(kw)
    return pd.DataFrame(basis)


def test_schema_ordnet_und_prueft():
    aus = schema.als_parameter(_df(wert=[1.0, None]))
    assert list(aus.columns) == schema.PARAM_SPALTEN and len(aus) == 1
    assert str(aus["verfuegbar_ab"].dtype) == "datetime64[us, UTC]"
    with pytest.raises(ValueError, match="Nicht registrierte"):
        schema.als_parameter(_df(parameter_id=["ZZ9-99", "ZZ9-99"]))
    with pytest.raises(ValueError, match="Spalten fehlen"):
        schema.als_parameter(_df().drop(columns="stand"))


def test_pruefung_findet_stichtagsverstoss_und_einbruch():
    gut = schema.als_parameter(_df())
    kennzahlen, schwer = pruefe_parameter(gut, {"IH1-03": {"zeilen": 2}})
    assert schwer == [] and kennzahlen[0]["zeilen"] == 2
    falsch = gut.copy()
    falsch.loc[0, "ereignis_zeit"] = pd.Timestamp("2024-02-01", tz="UTC")
    assert any("ereignis_zeit nach verfuegbar_ab" in s for s in pruefe_parameter(falsch)[1])
    assert any("Vorlauf" in s for s in pruefe_parameter(gut, {"IH1-03": {"zeilen": 10}})[1])


def test_zustand_und_budget(tmp_path):
    z = Zustand(tmp_path / "z.json")
    z.setze("a", [1, 2])
    assert Zustand(tmp_path / "z.json").hole("a") == [1, 2]
    assert Zeitbudget(0).abgelaufen() and not Zeitbudget(5).abgelaufen()


def test_datenblaetter_aktuell():
    datei = Path(__file__).resolve().parents[1] / "DATENBLAETTER.md"
    assert datei.read_text(encoding="utf-8").strip() == datenblatt_text().strip()


def test_gesamtlauf_ueber_kommandozeile(tmp_path, monkeypatch):
    """Alle drei Quellen nacheinander, wie im Workflow, ohne Netzzugriff."""
    aus, arb = tmp_path / "ausgabe", tmp_path / "arbeit"
    baue_submissions_zip(tmp_path / "s.zip")
    ordner = tmp_path / "insider"
    ordner.mkdir()
    sub = [["0001999-24-000010", "15-MAY-2024", "", "4", 1000, "ALPHA", "ALPH", "0"]]
    own = [["0001999-24-000010", 1999, "DOE JANE", "Director", ""]]
    tr = [["0001999-24-000010", 1, "Common", "14-MAY-2024", "P", 1000, 30, "A", 4000, "D"]]
    baue_form345_zip(ordner / "2024q2_form345.zip", sub, own, tr)
    basis = ["--ausgabe", str(aus), "--arbeits", str(arb), "--ab-jahr", "2006"]
    assert lauf_modul.main(["--quelle", "edgar_index", "--submissions-zip", str(tmp_path / "s.zip")] + basis) == 0
    assert lauf_modul.main(["--quelle", "edgar_ereignisse"] + basis) == 0
    assert lauf_modul.main(["--quelle", "edgar_insider", "--insider-ordner", str(ordner)] + basis) == 0
    p = pd.concat(pd.read_parquet(f) for f in sorted((aus / "parameter").glob("parameter__edgar_insider__*.parquet")))
    kauf = p[p["parameter_id"] == "IH1-03"].iloc[0]
    assert kauf["wert"] == 30000 and kauf["cik"] == 1000
    # Annahme 15.05.2024 19:30 ET laut Verzeichnis -> nutzbar ab 16.05. 09:30 ET
    assert kauf["verfuegbar_ab"] == pd.Timestamp("2024-05-16 09:30", tz="America/New_York")
    assert p[p["parameter_id"] == "IH1-05"]["wert"].iloc[0] == 47          # seit 8-K 2.02 vom 28.03.2024
    cf = baue_companyfacts_zip(tmp_path / "cf.zip")
    assert lauf_modul.main(["--quelle", "edgar_xbrl", "--companyfacts-zip", str(cf)] + basis) == 1
    # Das Testverzeichnis kennt die Aktenzeichen der Musterfirma nicht: Der Lauf muss das als Fehler melden
    # und darf keine Parameter veröffentlichen.
    fehler = json.loads((aus / "berichte" / "pruefbericht__edgar_xbrl.json").read_text(encoding="utf-8"))
    assert "ohne Annahmezeit" in fehler["schwer"][0]
    assert not list((aus / "parameter").glob("parameter__edgar_xbrl__*.parquet"))
    for quelle in ("edgar_index", "edgar_ereignisse", "edgar_insider"):
        bericht = json.loads((aus / "berichte" / f"pruefbericht__{quelle}.json").read_text(encoding="utf-8"))
        assert bericht["schwer"] == []
        assert (aus / "berichte" / f"manifest__{quelle}.json").exists()


def test_fehler_entfernt_parameter_und_meldet(tmp_path):
    aus = tmp_path / "ausgabe"
    code = lauf_modul.main(["--quelle", "edgar_ereignisse", "--ausgabe", str(aus), "--arbeits", str(tmp_path / "a")])
    assert code == 1
    bericht = json.loads((aus / "berichte" / "pruefbericht__edgar_ereignisse.json").read_text(encoding="utf-8"))
    assert "Meldungsverzeichnis fehlt" in bericht["schwer"][0]


def test_fehlerhaftes_verzeichnis_wird_nicht_veroeffentlicht(tmp_path):
    """Fehlen zu viele Annahmezeiten, bleibt der letzte gute Stand im Release unangetastet."""
    aus = tmp_path / "ausgabe"
    baue_submissions_zip(tmp_path / "s.zip")
    code = lauf_modul.main(["--quelle", "edgar_index", "--submissions-zip", str(tmp_path / "s.zip"),
                            "--ausgabe", str(aus), "--arbeits", str(tmp_path / "a"), "--ab-jahr", "2024"])
    assert code == 1
    assert list((aus / "bereinigt").glob("*.parquet")) == []
    bericht = json.loads((aus / "berichte" / "pruefbericht__edgar_index.json").read_text(encoding="utf-8"))
    assert "ohne Annahmezeit" in bericht["schwer"][0]


def test_xbrl_ueber_kommandozeile_ohne_verzeichnis(tmp_path):
    """Ohne Meldungsverzeichnis läuft die Quelle mit geschätzten Annahmezeiten durch und sagt das im Bericht."""
    aus = tmp_path / "ausgabe"
    cf = baue_companyfacts_zip(tmp_path / "cf.zip")
    code = lauf_modul.main(["--quelle", "edgar_xbrl", "--companyfacts-zip", str(cf), "--ausgabe", str(aus),
                            "--arbeits", str(tmp_path / "a")])
    assert code == 0
    bericht = json.loads((aus / "berichte" / "pruefbericht__edgar_xbrl.json").read_text(encoding="utf-8"))
    assert bericht["schwer"] == [] and any("Meldungsverzeichnis fehlt" in h for h in bericht["hinweise"])
    assert {"UA1-01", "UA1-02", "UA2-01", "UA3-01"} <= set(bericht["kennzahlen"])
    assert sorted(p.name for p in (aus / "bereinigt").glob("bereinigt__edgar_abschluesse__*.parquet"))[0] \
        == "bereinigt__edgar_abschluesse__2021.parquet"


def test_cfpb_ueber_kommandozeile(tmp_path):
    import zipfile
    from daten_offen.kern.ablage import Ablage
    aus = tmp_path / "ausgabe"
    Ablage(aus).schreibe_bereinigt("edgar_firmen", "alle", pd.DataFrame({
        "cik": [10], "name": ["ALPHA BANK CORP"], "sic": ["6021"], "tickers": ["ALB"], "fruehere_namen": ["[]"]}))
    z = tmp_path / "c.zip"
    with zipfile.ZipFile(z, "w") as a:
        a.writestr("complaints.csv", 'Date received,Company\n2024-01-05,"Alpha Bank Corporation"\n'
                                     '2024-01-09,"Alpha Bank Corporation"\n2024-02-01,"Alpha Bank Corporation"\n')
    basis = ["--ausgabe", str(aus), "--arbeits", str(tmp_path / "a")]
    assert lauf_modul.main(["--quelle", "cfpb", "--cfpb-zip", str(z)] + basis) == 0
    bericht = json.loads((aus / "berichte" / "pruefbericht__cfpb.json").read_text(encoding="utf-8"))
    assert bericht["kennzahlen"]["GA3-01"]["zeilen"] == 1 and any("Namensabgleich" in h for h in bericht["hinweise"])


@pytest.mark.parametrize("quelle, modul, info, erwartet", [
    ("fred", "fred", {"DGS10": 5}, 0),
    ("wikipedia", "wikipedia", {"zuordnungen": 3}, 0),
    ("edgar_rollen", "edgar_rollen", {"gelesen": 90, "ohne_rolle": 10}, 0),
    ("edgar_rollen", "edgar_rollen", {"gelesen": 30, "ohne_rolle": 30}, 1),          # Kopfformat nicht erkannt
    ("klinik", "klinik", {"trefferquote": {"studien": {"zeilen": 500, "quote": 0.4}}}, 0),
    ("klinik", "klinik", {"trefferquote": {"studien": {"zeilen": 500, "quote": 0.01}}}, 1),
])
def test_verdrahtung_der_quellen(tmp_path, monkeypatch, quelle, modul, info, erwartet):
    """Jede Quelle ist am Einstiegspunkt angeschlossen; unplausible Ergebnisse enden mit Fehlercode."""
    werte = schema.als_parameter(_df())
    monkeypatch.setattr(getattr(lauf_modul, modul), "lauf", lambda *a, **k: (werte, info, ["Hinweis"]))
    code = lauf_modul.main(["--quelle", quelle, "--ausgabe", str(tmp_path / "aus"), "--arbeits", str(tmp_path / "a")])
    assert code == erwartet
    bericht = json.loads((tmp_path / "aus" / "berichte" / f"pruefbericht__{quelle}.json").read_text(encoding="utf-8"))
    assert bool(bericht["schwer"]) == bool(erwartet) and "Hinweis" in bericht["hinweise"]
