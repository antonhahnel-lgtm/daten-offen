from collections import Counter

import numpy as np
import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET, handelbar_ab_serie
from daten_offen.kern.zustand import Zeitbudget
from daten_offen.quellen import edgar_texte as t

FUELL = " ".join(f"wort{chr(97 + i % 26)}{chr(97 + i // 26 % 26)}" for i in range(600))   # 600 verschiedene Wörter


def bericht(kern: str, risiko: str = "", zweifel: bool = False) -> bytes:
    gc = "<p>These conditions raise substantial doubt about our ability to continue as a going concern.</p>" if zweifel else ""
    return f"""<html><body><ix:header><ix:hidden>9999 versteckt versteckt</ix:hidden></ix:header>
<script>var x = 1;</script><p>Table of Contents Item 1A. Risk Factors 12 Item 2. Properties 30</p>
<p>{kern}</p><p>Item 1A. Risk&nbsp;Factors</p><p>{risiko}</p>{gc}<p>Item 1B. Unresolved Staff Comments None.</p>
<p>Item 2. Properties We lease offices. 2024 1,234</p></body></html>""".encode()


RISIKO_ALT = " ".join(["competition", "regulation", "supply"] * 100)
RISIKO_NEU = " ".join(["competition", "regulation", "pandemic", "tariffs"] * 100)


def test_text_und_aehnlichkeit():
    text = t.text_aus(bericht("Revenue grew &amp; margins improved " + FUELL, RISIKO_ALT))
    assert "versteckt" not in text and "var x" not in text and "revenue grew & margins" in text
    tf = t.woerter(text)
    assert tf["revenue"] == 1 and "the" not in tf and "2024" not in tf and tf["competition"] == 100
    r = t.risikoteil(text)
    assert r.startswith("item 1a. risk factors competition") and "unresolved" not in r      # nicht das Inhaltsverzeichnis
    cos, jac = t.aehnlichkeit(Counter(a=2, b=1), Counter(a=2, c=1))
    assert cos == pytest.approx(4 / 5) and jac == pytest.approx(1 / 3)
    assert np.isnan(t.aehnlichkeit(None, Counter(a=1))[0])
    m = t.merkmale(bericht(FUELL, RISIKO_ALT, zweifel=True), jahresbericht=True)
    assert m["going_concern"] == 1.0 and m["risiko_woerter"] >= 300 and m["tf"] is not None
    assert t.merkmale(bericht("kurz"), jahresbericht=False)["tf"] is None                     # Verweis auf Anlagen
    # vollständige Einreichung als Text: nur das erste Dokument
    txt = b"<SEC-DOCUMENT><DOCUMENT><TYPE>10-K<TEXT>Annual report alpha</TEXT></DOCUMENT><DOCUMENT><TYPE>EX-21<TEXT>beta</TEXT></DOCUMENT>"
    assert "alpha" in t.text_aus(txt) and "beta" not in t.text_aus(txt)


def meldungen():
    zeilen = [  # cik, accession, form, Stichtag, eingereicht, Dokument, Annahme
        (10, "K-2023", "10-K", "2023-12-31", "2024-02-20", "k23.htm", "2024-02-20 16:30"),
        (10, "K-2024", "10-K", "2024-12-31", "2025-02-21", "k24.htm", "2025-02-21 10:00"),
        (10, "K-2024A", "10-K/A", "2024-12-31", "2025-04-01", "k24a.htm", "2025-04-01 10:00"),
        (10, "Q-2024-1", "10-Q", "2024-03-31", "2024-05-01", "q241.htm", "2024-05-01 10:00"),
        (10, "Q-2025-1", "10-Q", "2025-03-31", "2025-05-01", "q251.htm", "2025-05-01 10:00"),
        (10, "Q-2025-2", "10-Q", "2025-06-30", "2025-08-01", "q252.htm", "2025-08-01 10:00"),
        (11, "K-B-2024", "10-K", "2024-12-31", "2025-03-01", "b.htm", "2025-03-03 08:00"),
        (12, "K-C-2024", "10-K", "2024-12-31", "2025-03-01", None, "2025-03-03 08:00"),
    ]
    df = pd.DataFrame(zeilen, columns=["cik", "accession", "form", "report_date", "filing_date", "primary_document", "annahme"])
    df["report_date"], df["filing_date"] = pd.to_datetime(df["report_date"]), pd.to_datetime(df["filing_date"])
    df["annahme_utc"] = pd.to_datetime([pd.Timestamp(a, tz=ET).tz_convert("UTC") for a in df["annahme"]], utc=True).astype("datetime64[us, UTC]")
    df["verfuegbar_ab"] = handelbar_ab_serie(df["annahme_utc"]).astype("datetime64[us, UTC]")
    return df.drop(columns="annahme")


class Archiv:
    def __init__(self, dateien):
        self.dateien, self.anfragen = dateien, []

    def hole(self, url, erlaube_404=False, **kw):
        self.anfragen.append(url)
        inhalt = self.dateien.get(url.rsplit("/", 1)[1])
        return None if inhalt is None else type("A", (), {"content": inhalt})()


DATEIEN = {"k23.htm": bericht(FUELL + " alpha", RISIKO_ALT), "k24.htm": bericht(FUELL + " beta", RISIKO_NEU, zweifel=True),
           "q241.htm": bericht(FUELL), "q251.htm": bericht(FUELL + " " + FUELL), "q252.htm": bericht("kurz"), "b.htm": bericht(FUELL)}


def test_vorgaenger():
    b = t.berichte(meldungen()).set_index("accession")
    assert "K-2024A" not in b.index and b.loc["K-2024", "vorgaenger"] == "K-2023" and b.loc["Q-2025-1", "vorgaenger"] == "Q-2024-1"
    assert b.loc["Q-2025-2", "vorgaenger"] is None and b.loc["K-2023", "vorgaenger"] is None


def test_lauf(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_meldungen", "2025", meldungen())
    ablage.schreibe_bereinigt("edgar_firmen", "alle", pd.DataFrame({"cik": [10, 11, 12], "tickers": [None, "BBB", None]}))
    archiv = Archiv(DATEIEN)
    p, info, hinweise = t.lauf(ablage, abruf=archiv, parallel=2)
    assert info["neu"] == 7 and info["offen"] == 0 and len(archiv.anfragen) == 6               # jedes Dokument einmal
    assert archiv.anfragen[0].endswith("/11/KB2024/b.htm")                                    # Firma mit Ticker zuerst
    e = ablage.lies_bereinigt("edgar_texte").set_index("accession")
    assert list(ablage.lies_bereinigt("edgar_texte").columns) == t.SPALTEN
    assert e.loc["K-C-2024", "status"] == "kein_dokument" and e.loc["Q-2025-2", "woerter"] < t.MIN_WOERTER
    a, b = t.woerter(t.text_aus(DATEIEN["k23.htm"])), t.woerter(t.text_aus(DATEIEN["k24.htm"]))
    assert e.loc["K-2024", "cosinus"] == pytest.approx(t.aehnlichkeit(a, b)[0]) and e.loc["K-2024", "going_concern"] == 1.0
    assert e.loc["K-2024", "risiko_cosinus"] < 0.9 and 0.98 < e.loc["Q-2025-1", "cosinus"] < 1
    werte = {(z.parameter_id, z.stand): z.wert for z in p.itertuples()}
    assert set(p["parameter_id"]) == {"UA5-01", "UA5-03", "UA5-04", "UA2-05"}
    assert ("UA5-01", "K-2023") not in werte and ("UA2-05", "Q-2025-2") not in werte and werte[("UA2-05", "K-2023")] == 0.0
    assert werte[("UA5-03", "K-2024")] == pytest.approx(e.loc["K-2024", "risiko_cosinus"]) and ("UA5-03", "Q-2025-1") not in werte
    zeile = p[(p["stand"] == "K-2023") & (p["parameter_id"] == "UA5-04")].iloc[0]
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2024-02-21 09:30", tz=ET) and zeile["ereignis_zeit"] == pd.Timestamp("2023-12-31", tz=ET)

    # Folgelauf: ein neuer Bericht; gelesen werden nur er und sein Vorgänger
    neu = pd.concat([meldungen(), pd.DataFrame([{"cik": 10, "accession": "K-2025", "form": "10-K", "report_date": pd.Timestamp("2025-12-31"),
                                                 "filing_date": pd.Timestamp("2026-02-20"), "primary_document": "k25.htm",
                                                 "annahme_utc": pd.Timestamp("2026-02-20 15:00", tz="UTC"),
                                                 "verfuegbar_ab": pd.Timestamp("2026-02-20 15:00", tz="UTC")}])], ignore_index=True)
    ablage.schreibe_bereinigt("edgar_meldungen", "2025", neu)
    archiv = Archiv({**DATEIEN, "k25.htm": DATEIEN["k24.htm"]})
    p2, info, _ = t.lauf(ablage, abruf=archiv, parallel=2)
    assert info["neu"] == 1 and sorted(u.rsplit("/", 1)[1] for u in archiv.anfragen) == ["k24.htm", "k25.htm"]
    assert ablage.lies_bereinigt("edgar_texte").set_index("accession").loc["K-2025", "cosinus"] == pytest.approx(1.0)


def test_zeitbudget(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_meldungen", "2025", meldungen())
    archiv = Archiv(DATEIEN)
    p, info, hinweise = t.lauf(ablage, abruf=archiv, budget=Zeitbudget(0), parallel=2)
    assert info["unvollstaendig"] and info["offen"] == 7 and (ablage.wurzel / "FORTSETZEN__edgar_texte").exists()


@pytest.mark.parametrize("satz, soll", [
    ("these conditions raise substantial doubt about the company's ability to continue as a going concern.", True),
    ("there is substantial doubt as to whether we can continue as a going concern.", True),
    ("the company has suffered recurring losses from operations that raise substantial doubt about its ability to continue "
     "as a going concern.", True),
    ("if we fail to raise capital, this could raise substantial doubt about our ability to continue as a going concern.", False),
    ("asu 2014-15 requires management to evaluate whether there are conditions or events that raise substantial doubt about "
     "an entity's ability to continue as a going concern.", False),
    ("there is no substantial doubt about our ability to continue as a going concern.", False),
    ("in its 2016 annual report on form 10-k, sears indicated that substantial doubt exists related to its ability to "
     "continue as a going concern.", False),                                                   # Mieter, nicht die Firma
    ("its external auditors stated there was “substantial doubt” about the company’s ability to continue as a "
     "going concern.", False),                                                                 # Zitat über einen Kunden
    ("these factors raise substantial doubt about our ability to meet obligations.", False),
])
def test_going_concern(satz, soll):
    assert t.going_concern(satz) is soll
