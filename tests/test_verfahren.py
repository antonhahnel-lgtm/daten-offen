import re
from datetime import date
from types import SimpleNamespace

import pandas as pd

from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zeit import ET
from daten_offen.quellen import sec_verfahren as v


def zeile(zeit, adresse, beteiligte, kennung, akte="", anlagen=(), anf='"'):
    """Eine Tabellenzeile wie auf sec.gov: Zeitstempel, verlinkte Beteiligte, Unterfelder."""
    teile = [f'<div class="view-table_subfield view-table_subfield_release_number">\n'
             f'<span class="view-table_subfield_label">Release No.</span>\n<span class="view-table_subfield_value">{kennung}</span>\n</div>']
    if anlagen:
        links = " , ".join(f'<span class="media media--type-static-file"><span class="file file--mime-application-pdf">'
                           f'<a href="/files/x.pdf" type="application/pdf">{a}</a></span></span>' for a in anlagen)
        teile.append(f'<div class="view-table_subfield view-table_subfield_see_also"><span class="view-table_subfield_label">See Also: </span>'
                     f'<span class="view-table_subfield_value">{links}</span></div>')
    if akte:
        teile.append(f'<div class="view-table_subfield view-table_subfield_file_number"><span class="view-table_subfield_label">File Number:</span>'
                     f'\n<span class="view-table_subfield_value">{akte}</span></div>')
    return (f'<tr class="pr-list-page-row">\n<td headers="a" class="views-field views-field-field-publish-date is-active">'
            f'<time datetime="{zeit}" class="datetime">egal</time>\n</td>\n<td headers="b" class="views-field">'
            f'<div class="release-view__respondents"><a href={anf}{adresse}{anf}>{beteiligte}</a></div>\n' + "\n".join(teile) + "</td>\n</tr>")


def seite(zeilen):
    return ('<html><body><main><form><select name="year"><option>2026</option></select></form><table><thead><tr><th>Date</th>'
            '<th>Respondents</th></tr></thead><tbody>' + "\n".join(zeilen) + "</tbody></table></main></body></html>")


LR = "/enforcement-litigation/litigation-releases/"
DATEI = "https://www.sec.gov/files/litigation/"
LR_26685 = zeile("2026-11-12T18:52:20Z", LR + "lr-26685", "Alpha Corp and John Doe", "LR-26685", anlagen=["SEC Complaint"])
LR_26657 = zeile("2026-09-30T20:00:00Z", LR + "lr-26657", "Travel Co.; Beta Inc. (f/k/a Gamma Corp.), Relief Defendant", "LR-26657, AAER-4603",
                 anlagen=["SEC Complaint", "Final Judgment - Beta"])
LR_16500 = zeile("2000-05-04T13:11:20Z", DATEI + "litreleases/lr16500.txt", "Alpha Corp", "LR-16500")
LR_PERSONEN = zeile("2005-03-03T14:00:00Z", DATEI + "litreleases/lr19118.txt", "Scott, Kenneth C. Tomich, Mark S. &quot;Mike&quot;", "LR-19118")
AP_FOLGE = zeile("2017-08-10T13:24:14Z", DATEI + "admin/2017/34-81378.pdf", "Alpha Corp Delta Mining Inc. (f/k/aPenola, Inc.)", "34-81378",
                 akte="3-18095", anf="'")
AP_ERST = zeile("2017-08-02T13:24:15Z", DATEI + "admin/2017/34-81295.pdf", "Alpha Corp Delta Mining Inc. (f/k/aPenola, Inc.)", "34-81295",
                akte="3-18095", anf="'")
AP_AAER = zeile("2019-09-23T13:25:47Z", DATEI + "admin/2019/34-87063.pdf", "Beta Inc. and Jane Roe, CPA", "34-87063, AAER-4089", akte="3-19000")
AAER_AP = zeile("2019-09-23T13:25:47Z", DATEI + "admin/2019/34-87063.pdf", "Beta Inc. and Jane Roe, CPA", "34-87063, AAER-4089")
AAER_ALT = zeile("1968-03-12T04:41:41Z", "https://www.sec.gov/files/alj/aljdec/1968/id19680311sb.pdf", "Keystone Co., Inc. (8-12228) Samuel Bind",
                 "3-785, AAER-1248", anlagen=["Opinion"])
SEITEN = {"litigation-releases": [[LR_26685, LR_26657], [LR_16500], [LR_PERSONEN]],
          "administrative-proceedings": [[AP_FOLGE, AP_ERST], [AP_AAER]],
          "accounting-auditing-enforcement-releases": [[AAER_AP, LR_26657], [AAER_ALT]]}


class Quelle:
    def __init__(self, seiten=None):
        self.seiten, self.anfragen = seiten or SEITEN, []

    def hole(self, url, **kw):
        self.anfragen.append(url)
        pfad, nr = re.search(r"enforcement-litigation/([\w-]+)\?page=(\d+)", url).groups()
        seiten = self.seiten[pfad]
        return SimpleNamespace(text=seite(seiten[int(nr)] if int(nr) < len(seiten) else ["<tr><td>No results found.</td></tr>"]))


def firmen():
    gamma = '[{"name": "Gamma Corp", "from": "2001-02-01T00:00:00.000Z", "to": "2010-06-30T00:00:00.000Z"}]'
    penola = '[{"name": "Penola, Inc.", "from": "2010-01-05T00:00:00.000Z", "to": "2012-03-01T00:00:00.000Z"}]'
    # EDGAR führt den heutigen Namen meist selbst unter den früheren, mit seinem Beginn
    travel = ('[{"name": "TRAVEL CO", "from": "1994-02-01T05:00:00.000Z", "to": "2026-11-13T05:00:00.000Z"}, '
              '{"name": "Old Travel Inc", "from": "1990-01-01T00:00:00.000Z", "to": "1994-02-01T00:00:00.000Z"}]')
    return pd.DataFrame({"cik": [10, 11, 12, 13, 14, 15, 16, 17], "sic": ["1000"] * 8,
                         "name": ["ALPHA CORP", "Beta Inc.", "Delta Mining Inc.", "TRAVEL CO", "CITIGROUP INC", "MORGAN STANLEY", "Zeta Inc", "Zeta Inc"],
                         "tickers": ["ALP", None, None, "TVL", "C", "MS", None, None],
                         "fruehere_namen": ["[]", gamma, penola, travel, "[]", "[]", "[]", "[]"]})


def test_seite_lesen():
    z = v.lies_seite(seite([LR_26657, AP_FOLGE, AAER_ALT, "<tr><td>No results found.</td></tr>"]))
    assert [x["adresse"] for x in z] == [LR + "lr-26657", "/files/litigation/admin/2017/34-81378.pdf", "/files/alj/aljdec/1968/id19680311sb.pdf"]
    assert z[0]["kennung"] == "LR-26657, AAER-4603" and z[0]["aaer"] and z[0]["anlagen"] == "SEC Complaint , Final Judgment - Beta"
    assert z[0]["beteiligte"] == "Travel Co.; Beta Inc. (f/k/a Gamma Corp.), Relief Defendant" and z[0]["aktenzeichen"] == ""
    assert z[1]["aktenzeichen"] == "3-18095" and not z[1]["aaer"] and z[1]["anlagen"] == ""
    # der Tag gilt in New Yorker Zeit: 04:41 UTC gehört zum Vortag
    assert [x["tag"] for x in z] == [pd.Timestamp("2026-09-30"), pd.Timestamp("2017-08-10"), pd.Timestamp("1968-03-11")]


def test_namen_im_text():
    s = v.Suche(firmen())
    tag = pd.Timestamp("2017-08-10")
    finde = lambda text, t=tag: [(name, cik, art) for name, cik, _, art in s.suche(text, t)]
    assert finde("Alpha Corp., Ward A. Cavanaugh and James H.Johnsen") == [("Alpha Corp", 10, "exakt")]
    assert finde("Gary V. Morris, Alpha Corporation and Robert Charles Muchmore, Jr.") == [("Alpha Corporation", 10, "exakt")]
    # ohne Trennzeichen aneinandergereiht; früherer Name hinter f/k/a ohne Zwischenraum
    assert finde("Alpha Corp Delta Mining Inc. (f/k/aPenola, Inc.) Unbekannt,Inc.") == [
        ("Alpha Corp", 10, "exakt"), ("Delta Mining Inc", 12, "exakt"), ("Penola, Inc", 12, "frueher"), ("Unbekannt, Inc", None, "keiner")]
    # Töchter mit Zeitraum: Morgan Stanley Smith Barney zählt erst ab 2009 zu Morgan Stanley
    assert finde("Citigroup Global Markets, Inc., Morgan Stanley Smith Barney LLC") == [
        ("Citigroup Global Markets, Inc", 14, "tochter"), ("Morgan Stanley Smith Barney LLC", 15, "tochter")]
    assert finde("Morgan Stanley Smith Barney LLC", pd.Timestamp("2008-01-01")) == [("Morgan Stanley Smith Barney LLC", None, "keiner")]
    # ein einzelnes Wort zählt nur mit Rechtsform; Namen in der Mitte eines längeren Namens zählen nicht
    assert finde("Travel, Morgan Stanley et al.") == [("Morgan Stanley", 15, "exakt")]
    assert finde("First Alpha Corp and Travel Co. Holdings LLC") == [("First Alpha Corp", None, "keiner"), ("Travel Co", 13, "exakt"),
                                                                     ("Holdings LLC", None, "keiner")]
    # ein Name gilt erst ab seinem Auftreten bei EDGAR (ein Jahr Toleranz); gleichnamige Firmen ohne Ticker bleiben offen
    assert finde("Penola, Inc.", pd.Timestamp("2005-01-01")) == [("Penola, Inc", None, "keiner")]
    assert finde("Beta Inc.", pd.Timestamp("2005-01-01")) == [("Beta Inc", None, "keiner")]
    assert finde("Gamma Corp.", pd.Timestamp("2005-01-01")) == [("Gamma Corp", 11, "frueher")]
    assert finde("Zeta Inc.") == [("Zeta Inc", None, "mehrdeutig")]
    assert finde("Travel Co. and Old Travel Inc.", pd.Timestamp("2000-01-01")) == [("Travel Co", 13, "exakt"), ("Old Travel Inc", 13, "frueher")]
    assert v.abschnitte("W.L. Ware Enterprises, Inc., et al. and Warren L. Ware (Defendants); John Does 1-5") == [
        "W.L. Ware Enterprises, Inc", "and Warren L. Ware"]


def test_lauf(tmp_path):
    ablage = Ablage(tmp_path / "aus")
    ablage.schreibe_bereinigt("edgar_firmen", "alle", firmen())
    quelle = Quelle()
    p, info, hinweise = v.lauf(ablage, abruf=quelle, heute=date(2026, 11, 15))
    assert len(quelle.anfragen) == 4 + 3 + 3                               # alle Seiten und je eine leere am Ende
    assert info["ereignisse"] == {"aaer": 1, "ap": 3, "lr": 4} and info["mit_aaer"] == 3 and info["mit_firma"] == 6
    e = ablage.lies_bereinigt("verfahren_ereignisse")
    assert list(e.columns) == v.SPALTEN and len(e) == 8
    doppelt = e[e["kennung"] == "34-87063, AAER-4089"].iloc[0]             # steht in zwei Listen: eine Zeile, Aktenzeichen bleibt
    assert (doppelt["liste"], doppelt["aktenzeichen"], doppelt["art"]) == ("ap", "3-19000", 12)
    assert e.set_index("kennung")["art"].to_dict() == {"3-785, AAER-1248": 12, "LR-16500": 1, "LR-19118": 1, "34-81295": 2, "34-81378": 3,
                                                       "34-87063, AAER-4089": 12, "LR-26657, AAER-4603": 11, "LR-26685": 1}
    werte = {(int(z.cik), z.stand): z.wert for z in p.itertuples()}
    # vor 2001 kein Parameter; die Folgemeldung desselben Aktenzeichens trägt 3; Gamma und Beta sind dieselbe Firma
    assert werte == {(10, "lr:LR-26685"): 1.0, (13, "lr:LR-26657, AAER-4603"): 11.0, (11, "lr:LR-26657, AAER-4603"): 11.0,
                     (10, "ap:34-81295"): 2.0, (12, "ap:34-81295"): 2.0, (10, "ap:34-81378"): 3.0, (12, "ap:34-81378"): 3.0,
                     (11, "ap:34-87063, AAER-4089"): 12.0}
    zeile_ = p[p["stand"] == "lr:LR-26685"].iloc[0]
    assert zeile_["ereignis_zeit"] == pd.Timestamp("2026-11-12 00:00", tz=ET) and zeile_["parameter_id"] == "PR4-01"
    assert zeile_["verfuegbar_ab"] == pd.Timestamp("2026-11-13 09:30", tz=ET)
    z = ablage.lies_bereinigt("verfahren_zuordnung")
    assert z[z["cik"].isna()]["name"].tolist() == ["Keystone Co., Inc"] and info["haeufig_ohne_treffer"] == {"Keystone Co., Inc": 1}
    assert set(z["art"]) == {"exakt", "frueher", "keiner"}

    # Folgelauf: gelesen wird je Liste nur, bis eine Seite nichts Neues mehr zeigt; der Bestand bleibt
    neu = zeile("2026-11-13T15:00:00Z", LR + "lr-26690", "Alpha Corp", "LR-26690")
    kuenftig = zeile("2026-11-17T15:00:00Z", LR + "lr-26691", "Alpha Corp", "LR-26691")
    seiten = {**SEITEN, "litigation-releases": [[kuenftig, neu], [LR_26685, LR_26657], [LR_16500], [LR_PERSONEN]]}
    quelle = Quelle(seiten)
    p2, info, _ = v.lauf(ablage, abruf=quelle, heute=date(2026, 11, 15))
    assert len(quelle.anfragen) == 2 + 2 + 2 and info["seiten_gelesen"] == {"lr": 2, "ap": 2, "aaer": 2}
    assert len(p2) == len(p) + 1 and info["ereignisse"] == {"aaer": 1, "ap": 3, "lr": 5}
    assert len(ablage.lies_bereinigt("verfahren_ereignisse")) == 9
