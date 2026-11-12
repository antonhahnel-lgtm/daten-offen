from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.http import QuelleNichtErreichbar
from daten_offen.kern.zeit import ET
from daten_offen.quellen import uspto_patente as u

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
    siehe("ALPHA CORP", ("Miller, Ann; and Chu, Bo", "12000001"), ("Lee, Kim", "12000004"), anker="ALPHA"),
    siehe("Alpha Corp.", ("Miller, Ann", "D900001"), ("Miller, Ann", "RE50001")),
    siehe("Boeing Company, The", ("Lee, Kim", "12000004")),
    erst("Chu, Bo; to Google LLC|Custom news feed systems &#x26; methods", "12000002", anker="CHU"),
    siehe("Chu, Bo", ("Miller, Ann; and Chu, Bo", "12000001")),
    siehe("Google LLC", ("Chu, Bo", "12000002")),
])
SEITE_M = seite([
    erst("Lee, Kim, to Alpha Corp; and The Boeing Company|Wing with a twist", "12000004"),
    erst("Miller, Ann; and Chu, Bo, to Alpha Corp|Method of making things", "12000001", anker="MILLER"),
    erst("Miller, Ann, to Alpha Corp.|Case with headphones", "D900001"),
    erst("Miller, Ann, to Alpha Corp.|Reissued thing", "RE50001"),
    erst("Solo, Han|Mud flap holder device, to be mounted", "12000003"),
    siehe("Solo Systems LLC", ("Solo, Han", "12000003")),          # steht nicht hinter „to“: kein Inhaber
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
    return pd.DataFrame({"cik": [10, 1652044, 12927, 99], "name": ["ALPHA CORP", "Alphabet Inc.", "BOEING CO", "Solo Systems LLC"],
                         "tickers": ["ALP", "GOOGL,GOOG", "BA", None], "sic": ["3720"] * 4, "fruehere_namen": ["[]"] * 4})


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
    # sechs Patente; „to“ steht auch in einem Titel, zählt dort aber keinen Inhaber
    assert info == {"patente": 6, "mit_inhaber": 6, "inhaber_erkannt": 5, "erfindungspatente": 4, "woche": 45, "seiten": 2}
    paare = set(zip(tabelle["inhaber"], tabelle["nummer"], tabelle["art"]))
    # Erfinder (Chu, Bo) und ein Name, der nicht hinter „to“ steht (Solo Systems LLC), sind keine Inhaber
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


def test_zuordnung():
    inhaber = pd.DataFrame({"inhaber": ["ALPHA CORP", "Alpha Corp.", "Google LLC", "Boeing Company, The", "Raytheon Company",
                                        "Unbekannt GmbH"], "patente": [2, 2, 1, 1, 3, 4]})
    z, unbekannt = u.ordne_zu(inhaber, firmen())
    assert z.set_index("inhaber")[["cik", "art"]].astype(object).where(z.set_index("inhaber")["cik"].notna(), None).values.tolist() == [
        [10, "exakt"], [10, "exakt"], [1652044, "tochter"], [12927, "exakt"], [None, None], [None, None]]
    assert z.loc[z["inhaber"] == "Raytheon Company", "art"].item() == "keiner"        # Mutter RTX fehlt in dieser Firmentabelle
    assert "RTX Corp" in unbekannt and "Alphabet Inc." not in unbekannt


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
    z = ablage.lies_bereinigt("patente_zuordnung").set_index("inhaber")
    assert z.loc["Google LLC", ["cik", "art", "patente"]].tolist() == [1652044, "tochter", 1]
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
