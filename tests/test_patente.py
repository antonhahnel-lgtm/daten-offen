from datetime import date
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.http import QuelleNichtErreichbar
from daten_offen.kern.zeit import ET
from daten_offen.quellen import uspto_patente as u
from tests.hilfen import baue_patentsview

KOPF = ('<html><body><p style="text-align:center"><b>LIST OF PATENTEES</b><br /><small>TO WHOM</small><br />PATENTS WERE '
        "ISSUED ON THE {tag} DAY OF {monat}, {jahr}\n<br />AND TO WHOM<br />REEXAMINATION CERTIFICATES WERE ISSUED<br />"
        "DURING THE WEEK BEGINNING THE 2nd DAY OF {monat}, {jahr}.</p>\n")


def verweis(nummer, stempel="20261110"):
    return f'<a href="../html/1552-2/US{nummer}-{stempel}.html">{nummer}</a> Cl.&#xa0;G06K&#xa0;19/07722.'


def erst(text, nummer, anker=""):
    """Eintrag beim ersten Erfinder: „Erfinder, to Inhaber Titel Nummer“ (mit Anker schließt der Verweis vor dem Titel)."""
    if anker:
        kopf, _, titel = text.partition("|")
        return f'<div class="list_item1"><a name="{anker}">{kopf}</a> {titel} {verweis(nummer)}</div>\n'
    return f'<div class="list_item1">{text.replace("|", " ")} {verweis(nummer)}</div>\n'


def siehe(name, *zeilen, anker=""):
    kopf = f'<a name="{anker}">{name}: See--</a>' if anker else f"{name}: See--"
    return f'<div class="list_item1">{kopf}</div>' + "".join(
        f'<div class="list_item2">{erfinder} {verweis(nummer)}</div>' for erfinder, nummer in zeilen) + "\n"


def seite(eintraege, tag="10th", monat="November", jahr=2026):
    return (KOPF.format(tag=tag, monat=monat, jahr=jahr) + "".join(eintraege) + "</body></html>").encode("utf-8")


SEITE_A = seite([
    siehe("ALPHA CORP", ("Miller, Ann; and Chu, Bo", "12000001"), ("Lee, Kim", "12000004"), ("Old, Guy", "09000001"), anker="ALPHA"),
    siehe("Alpha Corp.", ("Miller, Ann", "D900001"), ("Miller, Ann", "RE050001")),
    siehe("Boeing Company, The", ("Lee, Kim", "12000004")),
    erst("Chu, Bo; to Google LLC|Custom news feed systems &#x26; methods", "12000002", anker="CHU"),
    siehe("Chu, Bo", ("Miller, Ann; and Chu, Bo", "12000001")),
    siehe("Google LLC", ("Chu, Bo", "12000002")),
])
SEITE_M = seite([
    erst("Lee, Kim; and The Boeing Company, to Alpha Corp|Wing with a twist", "12000004"),    # Mitinhaber steht vor „to“
    erst("Miller, Ann; and Chu, Bo, to Alpha Corp|Method of making things", "12000001", anker="MILLER"),
    erst("Miller, Ann, to Alpha Corp.|Case with headphones", "D900001"),
    erst("Miller, Ann, to Alpha Corp.|Reissued thing", "RE050001"),
    erst("Old, Guy, to Alpha Corp|Reexamined old thing", "09000001"),                         # Nachprüfungsbescheid
    erst("Solo, Han; and Organa, Leia|Mud flap holder device, to be mounted", "12000003"),
    siehe("Organa, Leia", ("Solo, Han", "12000003")),              # Miterfinderin, „to“ steht nur im Titel: kein Inhaber
])
LISTE = (b'<a href="issue_home.html">Home</a> <a href="patentee/alphaA.html" target="rightFrame">A</a> '
         b'<a href="patentee/alphaM.html" target="rightFrame">M</a>')


class Quelle:
    """Ersatz für den Abruf: Seiten je Wochenordner; zählt die Anfragen."""

    def __init__(self, ordner, gestoert=()):
        self.ordner, self.gestoert, self.anfragen = ordner, set(gestoert), []

    def hole(self, url, erlaube_404=False, **kw):
        self.anfragen.append(url)
        woche, _, name = url.split("patentsgazette.uspto.gov/")[1].partition("/OG/")
        if woche in self.gestoert:
            raise QuelleNichtErreichbar(url)
        inhalt = self.ordner.get(woche, {}).get(name)
        return None if inhalt is None else SimpleNamespace(content=inhalt)


def firmen():
    return pd.DataFrame({"cik": [10, 1652044, 12927, 99, 101829, 1047122],
                         "name": ["ALPHA CORP", "Alphabet Inc.", "BOEING CO", "Solo Systems LLC", "RTX Corp", "RAYTHEON CO/"],
                         "tickers": ["ALP", "GOOGL,GOOG", "BA", None, "RTX", None], "sic": ["3720"] * 6,
                         "fruehere_namen": ["[]"] * 6})


def test_ausgabetage():
    assert u.wochennummer(date(2026, 11, 10)) == 45 and u.wochennummer(date(2026, 1, 6)) == 1
    assert u.wochennummer(date(2025, 12, 30)) == 52 and u.wochennummer(date(2024, 12, 31)) == 53
    tage = u.ausgabetage(date(2026, 11, 13))
    assert tage[0] == date(2026, 11, 10) and tage[-1] == date(2025, 11, 18) and len(tage) == 52
    assert u.ausgabetage(date(2026, 11, 10))[0] == date(2026, 11, 10) and u.ausgabetage(date(2026, 11, 9))[0] == date(2026, 11, 3)


def test_lies_ausgabe(monkeypatch):
    monkeypatch.setattr(u, "MIN_PATENTE", 1)
    tag, verweise, ersteintraege = u.lies_seite(SEITE_A.decode())
    assert tag == date(2026, 11, 10) and ("Google LLC", "12000002") in verweise and ("Chu, Bo", "12000001") in verweise
    assert ersteintraege == {"12000002": "Chu, Bo; to Google LLC Custom news feed systems & methods"}
    quelle = Quelle({"week45": {u.SEITENLISTE: LISTE, "patentee/alphaA.html": SEITE_A, "patentee/alphaM.html": SEITE_M}})
    tabelle, info = u.hole_ausgabe(quelle, date(2026, 11, 10))
    # sechs Patente und ein Nachprüfungsbescheid; „to“ steht auch in einem Titel, zählt dort aber keinen Inhaber
    assert info == {"patente": 6, "mit_inhaber": 6, "inhaber_erkannt": 5, "erfindungspatente": 4, "nachpruefungen": 1,
                    "woche": 45, "seiten": 2}
    paare = set(zip(tabelle["inhaber"], tabelle["nummer"], tabelle["art"]))
    # Erfinder (Chu, Bo; Organa, Leia) sind keine Inhaber; der Mitinhaber vor „to“ zählt; Nummern ohne führende Nullen
    assert paare == {("ALPHA CORP", "12000001", "utility"), ("ALPHA CORP", "12000004", "utility"),
                     ("Boeing Company, The", "12000004", "utility"), ("Google LLC", "12000002", "utility"),
                     ("Alpha Corp.", "D900001", "design"), ("Alpha Corp.", "RE50001", "reissue")}
    assert set(tabelle["tag"]) == {pd.Timestamp("2026-11-10")}
    # der Ordner enthält noch die Ausgabe des Vorjahres
    assert u.hole_ausgabe(quelle, date(2026, 11, 3)) == (None, {"grund": "nicht vorhanden"})
    alt = Quelle({"week46": {"patentee/alphaA.html": seite([], tag="18th", jahr=2025)}})
    tabelle, info = u.hole_ausgabe(alt, date(2026, 11, 17))
    assert tabelle is None and "2025-11-18" in info["grund"] and len(alt.anfragen) == 2
    # zu wenige Patente: Aufbau geändert
    monkeypatch.setattr(u, "MIN_PATENTE", 2000)
    assert "nur 6 Patente" in u.hole_ausgabe(quelle, date(2026, 11, 10))[1]["grund"]


def test_namen_und_nummern():
    schluessel = u.als_schluessel(pa.array(["12000001", "D397841", "D0397841", "RE050717", "RE50717", "PP37146", "x-1", ""]))
    assert schluessel[1] == schluessel[2] and schluessel[3] == schluessel[4] and schluessel[0] == 12000001
    assert list(schluessel[-2:]) == [-1, -1] and len(set(schluessel[:6])) == 4
    assert [u.normiere(n) for n in ("RE050717", "PP037186", "D1105826", "12000001", "08514499", "H002259")] == [
        "RE50717", "PP37186", "D1105826", "12000001", "8514499", "H2259"]
    for name in ("Hyundai Motor Company", "BABY TREND, INC.", "W. L. Gore & Associates, Inc.", "Boeing Company, The",
                 "Dell Products, L.P.", "Airbus Operations, S.A.S.", "Wells Fargo Bank, N.A.", "Acme Pte. Ltd."):
        assert u.ist_organisation(name), name
    for name in ("Miller, Ann", "Smith, John, Jr.", "Kim, Se", "Nguyen, Co", "de la Cruz, Maria"):
        assert not u.ist_organisation(name), name
    # alte Nummern weit unter der höchsten ihres Vorsatzes sind Nachprüfungsbescheide
    assert u.nachpruefungen(["12495725", "12501842", "11064760", "08514499", "D1105979", "D0891234", "RE050703", "PP037154"]) == {
        "11064760", "08514499", "D0891234"}


def test_zuordnung():
    inhaber = pd.DataFrame({"inhaber": ["ALPHA CORP", "Alpha Corp.", "Google LLC", "Boeing Company, The", "Raytheon Company",
                                        "Unbekannt GmbH", "Zoox, Inc."], "patente": [2, 2, 1, 1, 3, 4, 5]})
    z, unbekannt = u.ordne_zu(inhaber, firmen())
    assert list(z.columns) == ["inhaber", "patente", "cik", "konfidenz", "art", "gilt_ab", "gilt_bis"]
    zeilen = [(r.inhaber, None if pd.isna(r.cik) else int(r.cik), r.art, None if pd.isna(r.gilt_ab) else str(r.gilt_ab.date()),
               None if pd.isna(r.gilt_bis) else str(r.gilt_bis.date())) for r in z.itertuples()]
    assert zeilen == [
        ("ALPHA CORP", 10, "exakt", None, None), ("Alpha Corp.", 10, "exakt", None, None),
        # Google vor der Umgründung zu Alphabet: die alte CIK fehlt in dieser Firmentabelle
        ("Google LLC", None, "keiner", None, "2015-10-02"), ("Google LLC", 1652044, "tochter", "2015-10-02", None),
        ("Boeing Company, The", 12927, "exakt", None, None),
        # Raytheon war bis zur Fusion eigenständig, seither gehört der Inhaber zu RTX
        ("Raytheon Company", 1047122, "tochter", None, "2020-04-03"), ("Raytheon Company", 101829, "tochter", "2020-04-03", None),
        ("Unbekannt GmbH", None, "keiner", None, None),
        # vor der Übernahme der Inhaber selbst (bei EDGAR unbekannt), danach die Mutter (fehlt in dieser Firmentabelle)
        ("Zoox, Inc.", None, "keiner", None, "2020-06-26"), ("Zoox, Inc.", None, "keiner", "2020-06-26", None)]
    assert "AMAZON COM INC" in unbekannt and "1288776" in unbekannt and "Alphabet Inc." not in unbekannt
    assert z["patente"].tolist() == [2, 2, 1, 1, 1, 3, 3, 4, 5, 5]
    # jede Stufenfolge ist lückenlos und aufsteigend
    for stufen in u.STUFEN.values():
        assert stufen[0][0] is None and stufen[-1][1] is None
        assert all(a[1] == b[0] for a, b in zip(stufen, stufen[1:]))


def test_lauf(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "MIN_PATENTE", 1)
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    vorwoche = seite([erst("Miller, Ann, to Alpha Corp|Older thing", "11999000").replace("20261110", "20261103"),
                      siehe("Alpha Corp", ("Miller, Ann", "11999000")).replace("20261110", "20261103")], tag="3rd")
    ordner = {"week45": {u.SEITENLISTE: LISTE, "patentee/alphaA.html": SEITE_A, "patentee/alphaM.html": SEITE_M},
              "week44": {"patentee/alphaA.html": vorwoche},                     # ohne Seitenliste: feste Seitenfolge
              "week46": {"patentee/alphaA.html": seite([], tag="18th", jahr=2025)}}
    quelle = Quelle(ordner, gestoert=["week43"])
    p, info, hinweise = u.lauf(ablage, abruf=quelle, heute=date(2026, 11, 11))
    assert info["ausgaben_neu"] == ["2026-11-10", "2026-11-03"] and info["ausgaben_gelesen"] == 2 and info["ausgaben_offen"] == 50
    assert info["juengste_ausgabe"] == "2026-11-10" and info["tage_seit_ausgabe"] == 1 and info["patente"] == 7
    werte = {(int(z.cik), z.stand): z.wert for z in p.itertuples()}
    # nur Erfindungspatente; Firma 10 unter zwei Schreibweisen; das gemeinsame Patent zählt bei beiden Inhabern
    assert werte == {(10, "2026-11-10"): 2.0, (12927, "2026-11-10"): 1.0, (1652044, "2026-11-10"): 1.0, (10, "2026-11-03"): 1.0}
    zeile = p[(p["cik"] == 10) & (p["stand"] == "2026-11-10")].iloc[0]
    assert zeile["ereignis_zeit"] == pd.Timestamp("2026-11-10 00:00", tz=ET)
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2026-11-11 09:30", tz=ET) and zeile["parameter_id"] == "GA1-01"
    assert any("Ausgabe 2026-10-27 nicht gelesen" in h for h in hinweise) and any(h.startswith("nicht gelesen: 2026-10-20") for h in hinweise)
    erteilt = ablage.lies_bereinigt("patente_erteilt")
    assert set(erteilt.columns) == {"tag", "nummer", "art", "inhaber"} and len(erteilt) == 7
    z = ablage.lies_bereinigt("patente_zuordnung")
    z = z[z["gilt_bis"].isna()].set_index("inhaber")
    assert z.loc["Google LLC", ["cik", "art", "patente"]].tolist() == [1652044, "tochter", 1]
    ausgaben = ablage.lies_bereinigt("patente_ausgaben")
    assert set(ausgaben["herkunft"]) == {"amtsblatt"} and set(ausgaben["lesart"]) == {u.LESART} and ausgaben["nachpruefungen"].sum() == 1
    assert info["trefferquote"]["quote_gewichtet"] == 1.0 and info["anteil_boerse"] == 1.0

    # Folgelauf am Dienstag danach: bekannte Ausgaben werden nicht erneut geholt; die neue ist noch nicht erschienen
    quelle = Quelle(ordner)
    p2, info, hinweise = u.lauf(ablage, abruf=quelle, heute=date(2026, 11, 17))
    assert info["ausgaben_neu"] == [] and len(p2) == 4 and info["tage_seit_ausgabe"] == 7
    assert not any("week45" in a or "week44" in a for a in quelle.anfragen)
    assert not any("2026-11-17" in h for h in hinweise)                         # am Ausgabetag selbst kein Befund
    # die neue Ausgabe erscheint
    ordner["week46"] = {"patentee/alphaA.html": seite(
        [erst("Chu, Bo; to Google LLC|Newer thing", "12000100").replace("20261110", "20261117"),
         siehe("Google LLC", ("Chu, Bo", "12000100")).replace("20261110", "20261117")], tag="17th")}
    p3, info, _ = u.lauf(ablage, abruf=Quelle(ordner), heute=date(2026, 11, 18))
    assert info["ausgaben_neu"] == ["2026-11-17"] and len(p3) == 5 and info["ausgaben_gelesen"] == 3


def test_ohne_ausgabe(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    with pytest.raises(RuntimeError, match="keine Ausgabe des Amtsblatts gelesen"):
        u.lauf(ablage, abruf=Quelle({}), heute=date(2026, 11, 11))


def gazette():
    """Zwei Ausgaben des Amtsblatts (10.11. und 03.11.2026) wie in test_lauf."""
    vorwoche = seite([erst("Miller, Ann, to Alpha Corp|Older thing", "11999000").replace("20261110", "20261103"),
                      siehe("Alpha Corp", ("Miller, Ann", "11999000")).replace("20261110", "20261103")], tag="3rd")
    return {"week45": {u.SEITENLISTE: LISTE, "patentee/alphaA.html": SEITE_A, "patentee/alphaM.html": SEITE_M},
            "week44": {"patentee/alphaA.html": vorwoche}}


def test_historie(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "MIN_PATENTE", 1)
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    u.lauf(ablage, abruf=Quelle(gazette()), heute=date(2026, 11, 11))
    # die Sammeldateien reichen bis zum 03.11.2026 und ersetzen das Amtsblatt bis dahin
    roh = baue_patentsview(tmp_path / "roh")
    quelle = Quelle(gazette())
    p, info, _ = u.lauf(ablage, abruf=quelle, heute=date(2026, 11, 11), historie=roh)
    assert info["historie"] == {"datei_inhaber": "g_assignee_not_disambiguated.tsv", "patente": 10, "zurueckgezogen": 1,
                                "ohne_datum": 0, "andere_nummern": 0, "von": "1999-12-28", "bis": "2026-11-03"}
    assert info["ausgaben_gelesen"] == 8 and info["ausgaben_amtsblatt"] == 1 and info["ausgaben_neu"] == [] and not quelle.anfragen
    ausgaben = ablage.lies_bereinigt("patente_ausgaben").set_index("tag")
    assert ausgaben["herkunft"].tolist() == ["patentsview"] * 7 + ["amtsblatt"]
    felder = ["patente", "mit_inhaber", "inhaber_erkannt", "erfindungspatente"]
    assert ausgaben.loc["2006-02-21", felder].tolist() == [3, 3, 3, 1]          # ohne das zurückgezogene Patent
    assert ausgaben.loc["2006-02-28", felder].tolist() == [1, 1, 0, 1]          # Inhaber ist eine Privatperson
    assert ausgaben.loc["2026-11-03", felder].tolist() == [2, 2, 2, 2] and ausgaben.loc["2026-11-10", "patente"] == 6
    erteilt = ablage.lies_bereinigt("patente_erteilt")
    assert sorted(p.name.split("__")[2][:4] for p in ablage.bereinigt.glob("bereinigt__patente_erteilt__*")) == [
        "1999", "2006", "2020", "2022", "2026"]
    je_tag = {str(t.date()): sorted(zip(g["nummer"], g["inhaber"], g["art"])) for t, g in erteilt.groupby("tag")}
    assert je_tag["2006-02-21"] == [("7000001", "Alpha Corp", "utility"), ("7000001", "Boeing Co", "utility"),
                                    ("D500001", "Alpha Corp", "design"), ("H2000", "Alpha Corp", "sonstige")]
    assert je_tag["2026-11-03"] == [("11999000", "Alpha Corp", "utility"), ("11999001", "BOEING CO", "utility")]
    assert len(je_tag["2026-11-10"]) == 6 and "2006-02-28" not in je_tag
    werte = {(int(z.cik), z.stand): z.wert for z in p.itertuples()}
    assert werte == {(10, "2006-02-21"): 1.0, (12927, "2006-02-21"): 1.0,
                     (1047122, "2020-03-31"): 1.0, (101829, "2020-04-07"): 1.0,       # Raytheon vor und nach der Fusion
                     (10, "2022-11-08"): 1.0, (10, "2026-11-03"): 1.0, (12927, "2026-11-03"): 1.0,
                     (10, "2026-11-10"): 2.0, (12927, "2026-11-10"): 1.0, (1652044, "2026-11-10"): 1.0}
    zeile = p[(p["cik"] == 10) & (p["stand"] == "2006-02-21")].iloc[0]
    assert zeile["verfuegbar_ab"] == pd.Timestamp("2006-02-22 09:30", tz=ET)
    assert info["trefferquote"]["quote_gewichtet"] == 1.0 and info["patente"] == 16

    # Folgelauf ohne die Sammeldateien (Tageslauf): der Bestand bleibt, nur neue Ausgaben kommen hinzu
    p2, info, _ = u.lauf(ablage, abruf=Quelle(gazette()), heute=date(2026, 11, 11))
    assert "historie" not in info and info["ausgaben_neu"] == [] and len(p2) == len(p)

    # vereinheitlichte Namen und gepackte Dateien liefern dieselbe Tabelle
    t1, tage1, _ = u.lies_patentsview(roh)
    t2, tage2, info2 = u.lies_patentsview(baue_patentsview(tmp_path / "roh2", roh=False, gepackt=True))
    assert info2["datei_inhaber"] == "g_assignee_disambiguated.tsv.zip"
    pd.testing.assert_frame_equal(t1.sort_values(["nummer", "inhaber"]).reset_index(drop=True),
                                  t2.sort_values(["nummer", "inhaber"]).reset_index(drop=True))
    pd.testing.assert_frame_equal(tage1, tage2)
    with pytest.raises(RuntimeError, match="g_patent.tsv fehlt"):
        u.lies_patentsview(tmp_path / "leer")


def test_alte_lesart(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "MIN_PATENTE", 1)
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    u.lauf(ablage, abruf=Quelle(gazette()), heute=date(2026, 11, 11))
    # Bestand der ersten Fassung: ohne Herkunft und Lesart, mit einer Ausgabe, die es nicht mehr gibt
    alt = ablage.lies_bereinigt("patente_ausgaben").drop(columns=["herkunft", "lesart", "nachpruefungen"])
    alt = pd.concat([alt, alt.iloc[[0]].assign(tag=pd.Timestamp("2026-10-27"), woche=43)], ignore_index=True)
    ablage.schreibe_bereinigt("patente_ausgaben", "alle", alt)
    erteilt = ablage.lies_bereinigt("patente_erteilt")
    zusatz = pd.DataFrame({"tag": pd.to_datetime(["2026-10-27", "2026-11-03"]), "nummer": ["11990000", "RE050002"],
                           "art": ["utility", "reissue"], "inhaber": ["Alpha Corp", "Alpha Corp"]})
    ablage.schreibe_bereinigt("patente_erteilt", "2026", pd.concat([erteilt, zusatz], ignore_index=True))
    p, info, _ = u.lauf(ablage, abruf=Quelle(gazette()), heute=date(2026, 11, 11))
    # beide vorhandenen Ausgaben werden neu gelesen; die verschwundene bleibt, wie sie war
    assert info["ausgaben_neu"] == ["2026-11-10", "2026-11-03"] and info["ausgaben_alte_lesart"] == 1
    erteilt = ablage.lies_bereinigt("patente_erteilt")
    assert "RE050002" not in set(erteilt["nummer"]) and "11990000" in set(erteilt["nummer"]) and len(erteilt) == 8
    ausgaben = ablage.lies_bereinigt("patente_ausgaben")
    assert ausgaben["lesart"].tolist() == [1, u.LESART, u.LESART] and len(ausgaben) == 3
    assert {(int(z.cik), z.stand): z.wert for z in p.itertuples()}[(10, "2026-10-27")] == 1.0


def test_historie_ersetzt_ganzes_jahr(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "MIN_PATENTE", 1)
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    u.lauf(ablage, abruf=Quelle({"week44": gazette()["week44"]}), heute=date(2026, 11, 4))
    # die Sammeldateien decken alle bisher gelesenen Ausgaben des Jahres ab
    p, info, _ = u.lauf(ablage, abruf=Quelle({}), heute=date(2026, 11, 4), historie=baue_patentsview(tmp_path / "roh"))
    erteilt = ablage.lies_bereinigt("patente_erteilt")
    assert sorted(erteilt.loc[erteilt["tag"] == "2026-11-03", "nummer"]) == ["11999000", "11999001"]
    assert info["ausgaben_amtsblatt"] == 0 and info["tage_seit_ausgabe"] == 1 and erteilt["art"].map(type).eq(str).all()
