import zipfile
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import sec_ftd as f

KOPF = "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE"


def baue_zip(pfad, teile: dict[str, list[str]], kopf=KOPF):
    with zipfile.ZipFile(pfad, "w") as z:
        for name, zeilen in teile.items():
            text = "\r\n".join([kopf] + zeilen + [f"Trailer record count {len(zeilen)}",
                                                  "Trailer total quantity of shares 1"]) + "\r\n"
            z.writestr(name, text.encode("latin-1"))
    return pfad


JAN_A = ["20240102|111111111|ALPH|15000|ALPHA CORP COM|10.50",
         "20240103|111111111|ALPH|9000|ALPHA CORP COM|10.40",                # unter der Schwelle
         "20240103|111111112|ALPHW|50000|ALPHA CORP WT EXP 2027|1.00",       # Optionsschein
         "20240104|222222222|BETA|20000|BETA HLDGS INC COM|.",               # ohne heutiges Kürzel -> Name
         "20240105|333333333|GAM|30000|OLDGAMMA CORP CL A|.",                # früherer Name
         "20240105|333333334|GAMB|12000|GAMMA INC CL B|.",                   # zweite Gattung -> Summe
         "20240108|444444444|DLT|99999|DELTA ETF TR SHS|.",                  # Fonds
         "20240109|555555555|OMG|40000|OMEGA CORP COM|5.00"]
Q1_2008 = {"cnsp_sec_fails_200801.txt": ["20080115|666666666|OMG|25000|OTHER MINING GROUP COM|."],   # Kürzel später neu vergeben
           "cnsp_sec_fails_200802.txt": ["20080220|222222222|BETA|11000|BETA HLDGS INC COM|."]}
JAN_B = ["20240116|111111111|ALPH|70000|ALPHA CORP COM|10.00"]


@pytest.fixture()
def lage(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", pd.DataFrame({
        "cik": [10, 11, 12, 13, 14],
        "name": ["ALPHA CORP", "BETA HOLDINGS INC", "GAMMA INC", "DELTA ETF TRUST", "OMEGA CORP"],
        "sic": ["2834", "6021", "3570", "6726", "1000"],
        "tickers": ["ALPH", None, "GAM", "DLT", "OMG"],
        "fruehere_namen": ["[]", "[]", '[{"name": "OLDGAMMA CORP"}]', "[]", "[]"]}))
    ordner = tmp_path / "ftd"
    ordner.mkdir()
    baue_zip(ordner / "cnsfails202401a.zip", {"cnsfails202401a.txt": JAN_A})
    baue_zip(ordner / "cnsp_sec_fails_2008q1.zip", Q1_2008)
    return ablage, ordner, tmp_path


def test_schluessel_und_fristen():
    assert f.periode("202401a") == (date(2024, 1, 15), False)
    assert f.periode("202412b") == (date(2024, 12, 31), False)
    assert f.periode("202402b") == (date(2024, 2, 29), False)
    assert f.periode("2008q1") == (date(2008, 3, 31), True)
    # Änderungszeitpunkt im Fenster zählt, auch wenn er nach der festen Frist liegt (verspätete Datei)
    spaet = datetime(2024, 3, 20, 15, 0, tzinfo=timezone.utc)
    assert f.veroeffentlicht_am("202401a", spaet) == spaet
    # außerhalb des Fensters (später neu hochgeladen) oder unbekannt: feste Frist, 09:30 ET
    alt = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)
    assert f.veroeffentlicht_am("202401a", alt) == pd.Timestamp("2024-02-14 09:30", tz=ET)
    assert f.veroeffentlicht_am("2008q1", None) == pd.Timestamp("2008-05-30 09:30", tz=ET)
    # ein Zeitpunkt vor dem Periodenende kann keine Veröffentlichung sein
    assert f.veroeffentlicht_am("202401a", datetime(2024, 1, 10, tzinfo=timezone.utc)) == pd.Timestamp("2024-02-14 09:30", tz=ET)


def test_links():
    html = ('<a href="/files/data/fails-deliver-data/cnsfails202610a.zip">x</a>'
            '<a href="/files/data/other/fails-deliver-data/cnsfails202308b_0.zip">x</a>'
            '<a href="https://www.sec.gov/files/data/frequently-requested/cnsp_sec_fails_2006q4.zip">x</a>'
            '<a href="/files/node/add/data_distribution/cnsfails202610a.zip">doppelt</a><a href="/anderes.zip">y</a>')
    assert f.links_aus_seite(html) == {
        "202610a": "https://www.sec.gov/files/data/fails-deliver-data/cnsfails202610a.zip",
        "202308b": "https://www.sec.gov/files/data/other/fails-deliver-data/cnsfails202308b_0.zip",
        "2006q4": "https://www.sec.gov/files/data/frequently-requested/cnsp_sec_fails_2006q4.zip"}


def test_bezeichnung():
    assert f.teile_bezeichnung("APPLE INC COM") == ("APPLE INC", "COM")
    assert f.teile_bezeichnung("BERKSHIRE HATHAWAY INC DEL CL B") == ("BERKSHIRE HATHAWAY INC", "DEL CL B")
    assert f.teile_bezeichnung("ALPHABET INC CAP STK CL C") == ("ALPHABET INC", "CAP STK CL C")
    assert f.teile_bezeichnung("ACA CAP HLDGS INC COM") == ("ACA CAP HOLDINGS INC", "COM")
    assert f.teile_bezeichnung("NEW YORK TIMES CO CL A") == ("NEW YORK TIMES CO", "CL A")
    assert f.teile_bezeichnung("ABB LTD ADS ( 1 REG SHS)") == ("ABB LTD", "ADS 1 REG SHS")
    assert f.teile_bezeichnung("NAVIOS MARITIME HOLDINGS INC W") == ("NAVIOS MARITIME HOLDINGS INC", "W")
    assert f.teile_bezeichnung("FT VEST TECHNOLOGY DIVIDEND TA") == ("FT VEST TECHNOLOGY DIVIDEND TA", "")
    assert f.teile_bezeichnung(None) == ("", "")


def test_lauf_zuordnung_und_parameter(lage):
    ablage, ordner, tmp = lage
    p, info, hinweise = f.lauf(ablage, tmp / "arb", lokal=ordner)
    werte = {(int(z.cik), z.ereignis_zeit.tz_convert(ET).strftime("%Y-%m-%d")): z.wert for z in p.itertuples()}
    assert werte == {(10, "2024-01-02"): 15000.0, (11, "2024-01-04"): 20000.0, (12, "2024-01-05"): 42000.0,
                     (14, "2024-01-09"): 40000.0, (11, "2008-02-20"): 11000.0}
    neu = p[p["cik"] == 10].iloc[0]
    assert neu["verfuegbar_ab"] == pd.Timestamp("2024-02-14 09:30", tz=ET) and neu["stand"] == "202401a"
    assert neu["ereignis_zeit"] == pd.Timestamp("2024-01-02 18:00", tz=ET)
    alt = p[p["stand"] == "2008q1"].iloc[0]
    assert alt["verfuegbar_ab"] == pd.Timestamp("2008-05-30 09:30", tz=ET)
    assert (p["ereignis_zeit"] <= p["verfuegbar_ab"]).all()

    w = ablage.lies_bereinigt("ftd_wertpapiere").set_index("cusip")
    assert w.loc["111111111", ["cik", "art"]].tolist() == [10, "kuerzel_name"]
    assert w.loc["222222222", ["cik", "art"]].tolist() == [11, "exakt"]                 # HLDGS -> HOLDINGS
    assert w.loc["333333333", ["cik", "art"]].tolist() == [12, "kuerzel_name"]          # früherer Name
    assert w.loc["333333334", "cik"] == 12 and w.loc["333333334", "art"] == "exakt"
    assert pd.isna(w.loc["111111112", "cik"]) and not w.loc["111111112", "stamm"]       # Optionsschein
    assert pd.isna(w.loc["444444444", "cik"])                                           # Fonds
    assert pd.isna(w.loc["666666666", "cik"])                                           # altes Kürzel, anderer Name
    assert w.loc["222222222", "erster_tag"] == pd.Timestamp("2008-02-20")
    assert "preis" not in " ".join(ablage.lies_bereinigt("ftd_tage").columns).lower()
    assert info["dateien_gelesen"] == 2 and info["nachsatz_abweichung"] == 0 and info["juengste_datei"] == "202401a"
    # aktive Stammaktien: fünf, alle zugeordnet (Fonds und Optionsschein zählen nicht als Stammaktie)
    assert info["trefferquote"]["zeilen"] == 5 and info["trefferquote"]["quote"] == pytest.approx(1.0)
    assert any("feste Frist bei 2" in h for h in hinweise)


def test_fortschreibung_ohne_dubletten(lage):
    ablage, ordner, tmp = lage
    f.lauf(ablage, tmp / "arb", lokal=ordner)
    baue_zip(ordner / "cnsfails202401b.zip", {"cnsfails202401b.txt": JAN_B})
    p, info, _ = f.lauf(ablage, tmp / "arb", lokal=ordner)          # die jüngsten Dateien werden neu gelesen
    assert len(p) == 6 and not p.duplicated(["cik", "ereignis_zeit"]).any()
    assert p[p["stand"] == "202401b"]["wert"].tolist() == [70000.0]
    tage = ablage.lies_bereinigt("ftd_tage")
    assert len(tage) == 11 and not tage.duplicated(["tag", "cusip"]).any()
    assert sorted(ablage.lies_bereinigt("ftd_dateien")["datei"]) == ["2008q1", "202401a", "202401b"]
    assert info["dateien_gelesen"] == 3


class Antwort:
    def __init__(self, inhalt: bytes, kopf=None):
        self.inhalt, self.headers, self.text = inhalt, kopf or {}, inhalt.decode("latin-1")

    def iter_content(self, chunk_size=1):
        yield self.inhalt

    def close(self):
        pass


class Abruf:
    def __init__(self, seiten):
        self.seiten, self.aufrufe = seiten, []

    def hole(self, url, stream=False, **kw):
        self.aufrufe.append(url)
        return self.seiten[url]


def test_abruf_mit_aenderungszeitpunkt(lage):
    ablage, ordner, tmp = lage
    adresse = "https://www.sec.gov/files/data/fails-deliver-data/cnsfails202401a.zip"
    abruf = Abruf({f.SEITE: Antwort(f'<a href="{adresse[19:]}">Januar</a>'.encode()),
                   adresse: Antwort((ordner / "cnsfails202401a.zip").read_bytes(),
                                    {"Last-Modified": "Fri, 02 Feb 2024 15:00:00 GMT"})})
    p, info, hinweise = f.lauf(ablage, tmp / "arb", abruf=abruf)
    # 02.02.2024 10:00 ET liegt in der Handelszeit: sofort nutzbar, früher als die feste Frist
    assert (p["verfuegbar_ab"] == pd.Timestamp("2024-02-02 15:00", tz="UTC")).all() and len(p) == 4
    assert any("aus der Datei bei 1" in h for h in hinweise)
    # ein späterer Lauf ändert den einmal festgestellten Zeitpunkt nicht mehr
    abruf.seiten[adresse].headers["Last-Modified"] = "Mon, 04 Mar 2024 15:00:00 GMT"
    p2, _, _ = f.lauf(ablage, tmp / "arb", abruf=abruf)
    assert (p2["verfuegbar_ab"] == pd.Timestamp("2024-02-02 15:00", tz="UTC")).all()
    assert not (tmp / "arb" / "ftd" / "202401a.zip").exists()


def test_pflichtspalten(tmp_path):
    z = baue_zip(tmp_path / "k.zip", {"k.txt": ["20240102|1|A"]}, kopf="DATUM|CUSIP|SYMBOL")
    with pytest.raises(KeyError, match="Pflichtspalten fehlen"):
        f.lies_archiv(z)
