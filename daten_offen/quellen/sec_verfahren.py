"""Verfahren der SEC gegen Firmen → PR4-01.

Drei Listen auf sec.gov/enforcement-litigation, je 100 Einträge pro Seite, neueste zuerst:

* Litigation Releases: Zivilklagen der SEC vor Bundesgerichten (seit 09/1995),
* Administrative Proceedings: Bescheide in Verwaltungsverfahren, mit Aktenzeichen (seit 09/1995),
* Accounting and Auditing Enforcement Releases: Einträge beider Listen mit AAER-Nummer, dazu ältere Entscheidungen.

Die Listen nennen die Beteiligten als freien Text. Zugeordnet wird eine Firma nur, wenn ihr Name (heutiger oder
früherer EDGAR-Name, bekannte Tochter) als abgegrenzter Teil dieses Textes vorkommt; Verfahren nur gegen Personen
werden keiner Firma zugerechnet.

  verfahren_ereignisse__alle   adresse, liste, kennung, tag, beteiligte, aktenzeichen, aaer, anlagen, art
  verfahren_zuordnung__alle    adresse, name, cik, konfidenz, art (Namen mit Rechtsform ohne Treffer: cik leer)
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser

import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.namen import RECHTSFORM, bereinige
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab

URL = "https://www.sec.gov/enforcement-litigation/{pfad}?page={seite}"
LISTEN = {"lr": "litigation-releases", "ap": "administrative-proceedings", "aaer": "accounting-auditing-enforcement-releases"}
TABELLE, TABELLE_ZUORDNUNG = "verfahren_ereignisse", "verfahren_zuordnung"
SPALTEN = ["adresse", "liste", "kennung", "tag", "beteiligte", "aktenzeichen", "aaer", "anlagen", "art"]
SCHLUESSEL = ["adresse", "beteiligte"]
MIN_SEITEN, MAX_SEITEN = 2, 400          # laufend: mindestens zwei Seiten je Liste; mehr als 400 Seiten gibt es nicht
MINDESTENS = {"lr": 10_000, "ap": 15_000, "aaer": 2_000}       # weniger Einträge: Aufbau der Seite geändert?
PARAMETER_AB = pd.Timestamp("2001-01-01")                      # der Handelskalender kennt die Schließungen ab 2001
NAME_TOLERANZ = timedelta(days=365)   # ein Name gilt ab einem Jahr vor seinem ersten Auftreten bei EDGAR
MAX_WOERTER = 12

FORMEN = RECHTSFORM | {"NA", "LLLP", "PLLC", "PC", "PA", "SPA", "OYJ", "ASA", "AB", "KK", "PTE", "PTY", "SARL", "LC"}
ALIAS = re.compile(r"\b(?:[fan]\s?/\s?k\s?/\s?a|d\s?/\s?b\s?/\s?a|(?:fka|aka|nka|dba)\b|formerly\s+known\s+as\b"
                   r"|also\s+known\s+as\b|now\s+known\s+as\b|doing\s+business\s+as\b)\.?", re.I)
BEIWERK = re.compile(r"\bet\.?\s*al\b\.?|\b(?:relief\s+|nominal\s+)?(?:defendants?|respondents?)\b\.?"
                     r"|\b(?:chief\s+)?administrative\s+law\s+judge\b|\bhearing\s+examiner\b|\btemporary\s+suspension\b"
                     r"|\bin\s+the\s+matter\s+of\b|\bjohn\s+does?\b[\s\d\-]*", re.I)
HART = re.compile(r"[;()\[\]\n\r\"“”]+")
UND = {"AND", "&"}

# Meldende Töchter und Sparten, die die SEC unter eigenem Namen nennt -> EDGAR-Name der Mutter (oder CIK).
TOCHTER_NAMEN = {
    "Citigroup Global Markets Inc.": "CITIGROUP INC", "Citigroup Global Markets, Inc.": "CITIGROUP INC",
    "Salomon Smith Barney Inc.": "CITIGROUP INC", "Smith Barney Inc.": "CITIGROUP INC", "Citibank, N.A.": "CITIGROUP INC",
    "Merrill Lynch, Pierce, Fenner & Smith Incorporated": "BANK OF AMERICA CORP /DE/",
    "Merrill Lynch, Pierce, Fenner & Smith Inc.": "BANK OF AMERICA CORP /DE/",
    "Banc of America Securities LLC": "BANK OF AMERICA CORP /DE/", "BofA Securities, Inc.": "BANK OF AMERICA CORP /DE/",
    "Bank of America, N.A.": "BANK OF AMERICA CORP /DE/",
    "J.P. Morgan Securities LLC": "JPMORGAN CHASE & CO", "J.P. Morgan Securities Inc.": "JPMORGAN CHASE & CO",
    "JPMorgan Chase Bank, N.A.": "JPMORGAN CHASE & CO", "Bear, Stearns & Co. Inc.": "JPMORGAN CHASE & CO",
    "Bear, Stearns Securities Corp.": "JPMORGAN CHASE & CO",
    "Morgan Stanley & Co. Incorporated": "MORGAN STANLEY", "Morgan Stanley & Co. LLC": "MORGAN STANLEY",
    "Morgan Stanley Smith Barney LLC": "MORGAN STANLEY", "Morgan Stanley DW Inc.": "MORGAN STANLEY",
    "Morgan Stanley Investment Management Inc.": "MORGAN STANLEY",
    "Goldman, Sachs & Co.": "GOLDMAN SACHS GROUP INC", "Goldman Sachs & Co. LLC": "GOLDMAN SACHS GROUP INC",
    "Goldman Sachs Execution & Clearing, L.P.": "GOLDMAN SACHS GROUP INC",
    "Wells Fargo Advisors, LLC": "WELLS FARGO & COMPANY/MN", "Wells Fargo Securities, LLC": "WELLS FARGO & COMPANY/MN",
    "Wells Fargo Clearing Services, LLC": "WELLS FARGO & COMPANY/MN", "Wells Fargo Bank, N.A.": "WELLS FARGO & COMPANY/MN",
    "Wells Fargo Advisors Financial Network, LLC": "WELLS FARGO & COMPANY/MN",
    "Wachovia Securities, LLC": "WELLS FARGO & COMPANY/MN", "Wachovia Capital Markets, LLC": "WELLS FARGO & COMPANY/MN",
    "UBS Securities LLC": "UBS Group AG", "UBS Financial Services Inc.": "UBS Group AG", "UBS AG": "UBS Group AG",
    "Credit Suisse Securities (USA) LLC": "CREDIT SUISSE GROUP AG", "Credit Suisse First Boston LLC": "CREDIT SUISSE GROUP AG",
    "Credit Suisse First Boston Corporation": "CREDIT SUISSE GROUP AG",
    "Deutsche Bank Securities Inc.": "DEUTSCHE BANK AKTIENGESELLSCHAFT", "Barclays Capital Inc.": "BARCLAYS PLC",
    "RBC Capital Markets, LLC": "ROYAL BANK OF CANADA", "RBC Capital Markets Corporation": "ROYAL BANK OF CANADA",
    "HSBC Securities (USA) Inc.": "HSBC HOLDINGS PLC", "BNP Paribas Securities Corp.": None,
    "Raymond James & Associates, Inc.": "RAYMOND JAMES FINANCIAL INC",
    "Raymond James Financial Services, Inc.": "RAYMOND JAMES FINANCIAL INC",
    "Charles Schwab & Co., Inc.": "SCHWAB CHARLES CORP", "TD Ameritrade, Inc.": "SCHWAB CHARLES CORP",
    "Stifel, Nicolaus & Company, Incorporated": "STIFEL FINANCIAL CORP", "Oppenheimer & Co. Inc.": "OPPENHEIMER HOLDINGS INC",
    "LPL Financial LLC": "LPL Financial Holdings Inc.", "Ameriprise Financial Services, Inc.": "AMERIPRISE FINANCIAL INC",
    "Ameriprise Financial Services, LLC": "AMERIPRISE FINANCIAL INC",
    "Robinhood Financial LLC": "Robinhood Markets, Inc.", "Robinhood Securities, LLC": "Robinhood Markets, Inc.",
    "Interactive Brokers LLC": "Interactive Brokers Group, Inc.", "E*TRADE Securities LLC": "MORGAN STANLEY",
    "Lehman Brothers Inc.": "LEHMAN BROTHERS HOLDINGS INC", "Prudential Securities Incorporated": "PRUDENTIAL FINANCIAL INC",
    "Jefferies LLC": "Jefferies Financial Group Inc.", "Jefferies & Company, Inc.": "Jefferies Financial Group Inc.",
    "Piper Jaffray & Co.": "PIPER SANDLER COMPANIES", "Cantor Fitzgerald & Co.": None,
    "Virtu Americas LLC": "Virtu Financial, Inc.", "Knight Capital Americas LLC": "Virtu Financial, Inc.",
    "State Street Bank and Trust Company": "STATE STREET CORP", "The Bank of New York Mellon": "Bank of New York Mellon Corp",
    "BNY Mellon Capital Markets, LLC": "Bank of New York Mellon Corp", "Pershing LLC": "Bank of New York Mellon Corp",
    "Western Asset Management Company": "FRANKLIN RESOURCES INC", "Legg Mason Wood Walker, Incorporated": "LEGG MASON, INC.",
    "Janus Capital Management LLC": "JANUS HENDERSON GROUP PLC", "Invesco Advisers, Inc.": "Invesco Ltd.",
    "Pacific Investment Management Company LLC": None, "Putnam Investment Management, LLC": None,
    "New York Stock Exchange LLC": "Intercontinental Exchange, Inc.", "NYSE Arca, Inc.": "Intercontinental Exchange, Inc.",
    "The Nasdaq Stock Market LLC": "NASDAQ, INC.", "Standard & Poor's Ratings Services": "S&P Global Inc.",
    "S&P Global Ratings": "S&P Global Inc.", "Moody's Investors Service, Inc.": "MOODYS CORP /DE/",
    "Western Union Financial Services, Inc.": "Western Union CO",
}
# Früherer Besitz: (gültig bis, Mutter davor); None = die Firma meldete selbst.
TOCHTER_FRUEHER = {
    "Merrill Lynch, Pierce, Fenner & Smith Incorporated": [("2009-01-01", "MERRILL LYNCH & CO., INC.")],
    "Merrill Lynch, Pierce, Fenner & Smith Inc.": [("2009-01-01", "MERRILL LYNCH & CO., INC.")],
    "Bear, Stearns & Co. Inc.": [("2008-05-30", "BEAR STEARNS COMPANIES INC")],
    "Bear, Stearns Securities Corp.": [("2008-05-30", "BEAR STEARNS COMPANIES INC")],
    "Wachovia Securities, LLC": [("2008-12-31", "WACHOVIA CORP NEW")],
    "Wachovia Capital Markets, LLC": [("2008-12-31", "WACHOVIA CORP NEW")],
    "Morgan Stanley Smith Barney LLC": [("2009-06-01", None)], "E*TRADE Securities LLC": [("2020-10-02", "E TRADE FINANCIAL CORP")],
    "TD Ameritrade, Inc.": [("2020-10-06", "TD AMERITRADE HOLDING CORP")],
    "Knight Capital Americas LLC": [("2013-07-01", "KNIGHT CAPITAL GROUP, INC."), ("2017-07-20", "KCG Holdings, Inc.")],
    "Janus Capital Management LLC": [("2017-05-30", "JANUS CAPITAL GROUP INC")],
    "Western Asset Management Company": [("2020-07-31", "LEGG MASON, INC.")],
    "New York Stock Exchange LLC": [("2007-04-04", None), ("2013-11-13", "NYSE Euronext")],
    "NYSE Arca, Inc.": [("2013-11-13", "NYSE Euronext")],
    "Piper Jaffray & Co.": [("2003-12-31", "US BANCORP \\DE\\")],
}


def _stufen() -> dict:
    stufen = {bereinige(n): [(None, None, m)] for n, m in TOCHTER_NAMEN.items()}
    for name, frueher in TOCHTER_FRUEHER.items():
        grenzen = [date.fromisoformat(bis) for bis, _ in frueher]
        stufen[bereinige(name)] = list(zip([None] + grenzen, grenzen + [None], [m for _, m in frueher] + [TOCHTER_NAMEN.get(name)]))
    return stufen


STUFEN = _stufen()

registriere(Parameter(
    id="PR4-01", name="SEC-Verfahren",
    definition="Eine Zeile je Veröffentlichung der SEC, die die Firma oder eine bekannte Tochter als Beteiligte nennt; "
               "wert: 1 = Zivilklage (Litigation Release), 2 = Verwaltungsverfahren, erster Bescheid des Aktenzeichens, "
               "3 = Verwaltungsverfahren, Folgebescheid; plus 10, wenn die Veröffentlichung eine AAER-Nummer trägt "
               "(Bilanzierung und Prüfung). Beteiligte, Aktenzeichen und Anlagen stehen in verfahren_ereignisse",
    einheit="Art (1–3, 11–13)", frequenz="je Veröffentlichung",
    offenlegung="amtliche Veröffentlichung der SEC (Litigation Releases, Administrative Proceedings, AAER)",
    quelle="sec.gov/enforcement-litigation (Litigation Releases, Administrative Proceedings, Accounting and Auditing "
           "Enforcement Releases)",
    lizenz="gemeinfrei (US-Behörde)", historie_ab="2001 (Listen ab 09/1995 in verfahren_ereignisse)",
    verzoegerung="Eröffnung des ersten Handelstags nach dem Veröffentlichungstag der Liste",
    schwaechen="Zuordnung nur über den Namen in der Beteiligtenzeile: Verfahren gegen Vorstände oder Prüfer ohne die "
               "Firma als Beteiligte fehlen, ebenso Firmen ohne EDGAR-Namen in der Zeile; gleichnamige Firmen können "
               "verwechselt werden. Zivilklagen tragen kein Aktenzeichen, Folgemeldungen (Urteil, Vergleich) sind dort "
               "nicht von der Klage zu trennen. Die Liste zeigt den Tag, nicht die Uhrzeit der Veröffentlichung"))


# --------------------------------------------------------------------------- Listen lesen
class _Liste(HTMLParser):
    """Zeilen der Ergebnistabelle: Zeitstempel, Adresse und Text der Beteiligten, Unterfelder."""
    FELDER = {"release-view__respondents": "beteiligte", "view-table_subfield_release_number": "kennung",
              "view-table_subfield_file_number": "aktenzeichen", "view-table_subfield_see_also": "anlagen"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.zeilen: list[dict] = []
        self.z: dict | None = None
        self.feld: str | None = None
        self.feld_tiefe = self.div = self.wert = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        klassen = (a.get("class") or "").split()
        if tag == "tr" and "pr-list-page-row" in klassen:
            self.z = {"zeit": None, "adresse": None, "beteiligte": "", "kennung": "", "aktenzeichen": "", "anlagen": ""}
            self.feld, self.div, self.wert = None, 0, 0
        if self.z is None:
            return
        if tag == "time" and a.get("datetime") and self.z["zeit"] is None:
            self.z["zeit"] = a["datetime"]
        elif tag == "div":
            self.div += 1
            if self.feld is None:
                for klasse, feld in self.FELDER.items():
                    if klasse in klassen:
                        self.feld, self.feld_tiefe, self.wert = feld, self.div, int(feld == "beteiligte")
        elif tag == "span" and self.feld and self.feld != "beteiligte":
            if self.wert or "view-table_subfield_value" in klassen:
                self.wert += 1
        elif tag == "a" and self.feld == "beteiligte" and a.get("href") and self.z["adresse"] is None:
            self.z["adresse"] = a["href"]

    def handle_endtag(self, tag):
        if self.z is None:
            return
        if tag == "span" and self.feld and self.feld != "beteiligte" and self.wert:
            self.wert -= 1
        elif tag == "div":
            if self.feld and self.div == self.feld_tiefe:
                self.feld, self.wert = None, 0
            self.div -= 1
        elif tag == "tr":
            self.zeilen.append(self.z)
            self.z = None

    def handle_data(self, data):
        if self.z is not None and self.feld and self.wert:
            self.z[self.feld] += data


def lies_seite(html: str) -> list[dict]:
    """Einträge einer Listenseite; Zeilen ohne Zeitstempel oder Beteiligte entfallen."""
    leser = _Liste()
    leser.feed(html)
    aus = []
    for z in leser.zeilen:
        beteiligte = " ".join(z["beteiligte"].split())
        zeit = pd.to_datetime(z["zeit"], utc=True, errors="coerce")
        if not beteiligte or pd.isna(zeit):
            continue
        kennung = " ".join(z["kennung"].split())
        adresse = re.sub(r"^https?://(?:www\.)?sec\.gov", "", (z["adresse"] or "").strip()) or f"ohne:{kennung}"
        aus.append({"adresse": adresse, "kennung": kennung, "tag": pd.Timestamp(zeit.tz_convert(ET).date()), "beteiligte": beteiligte,
                    "aktenzeichen": " ".join(z["aktenzeichen"].split()), "aaer": "AAER" in kennung.upper(),
                    "anlagen": " ".join(z["anlagen"].split())})
    return aus


def lies_liste(abruf, liste: str, bekannt: set, alles: bool) -> tuple[list[dict], int]:
    """Seiten einer Liste von vorn; laufend nur, bis eine Seite nichts Neues mehr enthält."""
    zeilen, gesehen, seite = [], set(), 0
    while seite < MAX_SEITEN:
        neu = lies_seite(abruf.hole(URL.format(pfad=LISTEN[liste], seite=seite)).text)
        schluessel = {(z["adresse"], z["beteiligte"]) for z in neu}
        if not schluessel - gesehen:             # leere Seite oder Wiederholung der letzten: Ende der Liste
            break
        zeilen += [dict(z, liste=liste) for z in neu]
        gesehen |= schluessel
        seite += 1
        if not alles and seite >= MIN_SEITEN and schluessel <= bekannt:
            break
    return zeilen, seite


def ordne_ein(ereignisse: pd.DataFrame) -> pd.DataFrame:
    """Je Veröffentlichung eine Zeile (dieselbe steht teils in zwei Listen) und die Art für den Parameter."""
    if ereignisse.empty:
        return pd.DataFrame(columns=SPALTEN)
    e = ereignisse.copy()
    e["tag"] = pd.to_datetime(e["tag"])
    e["rang"] = e["liste"].map({"lr": 0, "ap": 1, "aaer": 2})
    e["aaer"] = e.groupby(SCHLUESSEL)["aaer"].transform("max").astype(bool)
    e["aktenzeichen"] = e.groupby(SCHLUESSEL)["aktenzeichen"].transform("max")
    e = e.sort_values(["rang"], kind="stable").drop_duplicates(SCHLUESSEL, keep="first")
    e = e.sort_values(["tag", "kennung", "adresse", "beteiligte"], kind="stable").reset_index(drop=True)
    klage = (e["liste"] == "lr") | ((e["liste"] == "aaer") & e["adresse"].str.contains(r"litrel|litigation-releases|/lr-?\d", case=False))
    folge = ~klage & (e["aktenzeichen"] != "") & e.duplicated("aktenzeichen", keep="first")
    e["art"] = (1 + (~klage).astype(int) + folge.astype(int) + 10 * e["aaer"].astype(int)).astype("int64")
    return e[SPALTEN]


# --------------------------------------------------------------------------- Namen im Text der Beteiligten
def _tag(text) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def baue_verzeichnis(firmen: pd.DataFrame) -> dict[str, list[tuple]]:
    """Bereinigter Name -> [(cik, gilt_ab, hat_ticker, art)]: heutiger Name ab dem letzten Namenswechsel, frühere
    Namen ab ihrem ersten Auftreten (jeweils mit Toleranz), ohne Ende – die SEC nennt Firmen auch unter altem Namen."""
    verzeichnis: dict[str, list[tuple]] = {}
    for cik, name, tickers, fruehere in zip(firmen["cik"], firmen["name"], firmen["tickers"], firmen["fruehere_namen"]):
        cik, ticker = int(cik), isinstance(tickers, str) and bool(tickers)
        alte = []
        if isinstance(fruehere, str) and fruehere not in ("", "[]"):
            try:
                alte = [a for a in json.loads(fruehere) if isinstance(a, dict)]
            except ValueError:
                alte = []
        wechsel = max((t for t in (_tag(a.get("to")) for a in alte) if t), default=None)
        n = bereinige(name)
        if n:
            verzeichnis.setdefault(n, []).append((cik, wechsel - NAME_TOLERANZ if wechsel else None, ticker, "exakt"))
        for a in alte:
            m, ab = bereinige(a.get("name")), _tag(a.get("from"))
            if m and m != n:
                verzeichnis.setdefault(m, []).append((cik, ab - NAME_TOLERANZ if ab else None, ticker, "frueher"))
    return verzeichnis


class Suche:
    """Findet Firmen im Text der Beteiligten. Ein Name zählt nur als abgegrenzter Abschnitt: von einem Trenner
    (Komma, „and“, Semikolon, Klammer, Rechtsform) bis zu einem Trenner; der längste Treffer gewinnt."""

    def __init__(self, firmen: pd.DataFrame):
        self.verzeichnis = baue_verzeichnis(firmen)
        self.bekannt = set(firmen["cik"].astype(int))
        self.unbekannt: set[str] = set()

    def _aus_verzeichnis(self, n: str, tag: date) -> tuple[int | None, float, str]:
        gueltig = [k for k in self.verzeichnis.get(n, ()) if k[1] is None or tag >= k[1]]
        if not gueltig:
            return None, 0.0, "keiner"
        for auswahl in (gueltig, [k for k in gueltig if k[3] == "exakt"], [k for k in gueltig if k[2]],
                        [k for k in gueltig if k[2] and k[3] == "exakt"]):
            ciks = {k[0] for k in auswahl}
            if len(ciks) == 1:
                art = "exakt" if any(k[3] == "exakt" for k in auswahl) else "frueher"
                return ciks.pop(), 1.0 if art == "exakt" else 0.95, art
        return None, 0.0, "mehrdeutig"

    def finde(self, n: str, tag: date) -> tuple[int | None, float, str]:
        """``n``: bereinigter Name."""
        for ab, bis, mutter in STUFEN.get(n, ()):
            if (ab is None or tag >= ab) and (bis is None or tag < bis):
                if mutter is None:
                    break
                if isinstance(mutter, int):
                    cik = mutter if mutter in self.bekannt else None
                else:
                    cik = self._aus_verzeichnis(bereinige(mutter), tag)[0]
                if cik is None:
                    self.unbekannt.add(str(mutter))
                    return None, 0.0, "keiner"
                return cik, 0.95, "tochter"
        return self._aus_verzeichnis(n, tag)

    def suche(self, beteiligte: str, tag) -> list[tuple]:
        """[(name, cik, konfidenz, art)] – Treffer und Namen mit Rechtsform ohne Treffer (cik None)."""
        aus, tag = [], pd.Timestamp(tag).date()
        for abschnitt in abschnitte(beteiligte):
            woerter = abschnitt.split()
            form = [w.upper().replace(".", "").strip(",") in FORMEN for w in woerter]
            und = [w.upper() in UND for w in woerter]
            komma = [w.endswith(",") for w in woerter]
            anfang = [i for i in range(len(woerter)) if not und[i] and (i == 0 or und[i - 1] or komma[i - 1] or form[i - 1])]
            ende = [j for j in range(1, len(woerter) + 1) if not und[j - 1] and (j == len(woerter) or und[j] or komma[j - 1] or form[j - 1])]
            anfaenge = set(anfang)
            i = 0
            while i < len(woerter):
                treffer = None
                if i in anfaenge:
                    for j in sorted((j for j in ende if i < j <= i + MAX_WOERTER), reverse=True):
                        name = " ".join(woerter[i:j]).strip(" ,.")
                        n = bereinige(name)
                        if not n or n in FORMEN or (" " not in n and not form[j - 1]):
                            continue                     # ein einzelnes Wort zählt nur mit Rechtsform dahinter
                        cik, konfidenz, art = self.finde(n, tag)
                        if cik is not None or art == "mehrdeutig":
                            treffer = (j, (name, cik, konfidenz, art))
                            break
                if treffer:
                    aus.append(treffer[1])
                    i = treffer[0]
                    continue
                if form[i] and not (i + 1 < len(woerter) and form[i + 1]):
                    # Name mit Rechtsform ohne Treffer: kürzester Abschnitt bis hierher, für den Prüfbericht
                    start = max((a for a in anfang if a <= i and not all(form[a:i + 1])), default=None)
                    if start is not None:
                        aus.append((" ".join(woerter[start:i + 1]).strip(" ,."), None, 0.0, "keiner"))
                i += 1
        return aus


def abschnitte(beteiligte: str) -> list[str]:
    """Zerlegt die Beteiligtenzeile an harten Trennern; Beiwerk (et al., Relief Defendants, Richter) entfällt."""
    t = BEIWERK.sub(";", ALIAS.sub(";", beteiligte))
    t = re.sub(r",(?=\S)", ", ", t)                      # „NBI,Inc.“: fehlender Zwischenraum nach dem Komma
    return [a.strip(" ,.") for a in HART.split(t) if a.strip(" ,.")]


def ordne_zu(ereignisse: pd.DataFrame, firmen: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    suche = Suche(firmen)
    zeilen, merker = [], {}
    for adresse, tag, beteiligte in zip(ereignisse["adresse"], ereignisse["tag"], ereignisse["beteiligte"]):
        schluessel = (beteiligte, tag)
        if schluessel not in merker:
            merker[schluessel] = suche.suche(beteiligte, tag)
        zeilen += [(adresse, *fund) for fund in merker[schluessel]]
    z = pd.DataFrame(zeilen, columns=["adresse", "name", "cik", "konfidenz", "art"])
    z["cik"] = z["cik"].astype("Int64")
    z["konfidenz"] = z["konfidenz"].astype("float64")
    return z.drop_duplicates().reset_index(drop=True), sorted(suche.unbekannt)


def baue_parameter(ereignisse: pd.DataFrame, zuordnung: pd.DataFrame) -> pd.DataFrame:
    treffer = zuordnung[zuordnung["cik"].notna()][["adresse", "cik"]].drop_duplicates()
    z = ereignisse[ereignisse["tag"] >= PARAMETER_AB].merge(treffer, on="adresse", how="inner")
    z = z.drop_duplicates(["cik", "adresse"])
    if z.empty:
        return leer()
    zeit = {}
    for tag in z["tag"].drop_duplicates():
        d = pd.Timestamp(tag).date()
        zeit[tag] = (pd.Timestamp(datetime.combine(d, time(0, 0), tzinfo=ET)).tz_convert("UTC"),
                     pd.Timestamp(handelbar_ab(datetime.combine(d, time(18, 0), tzinfo=ET))))
    return als_parameter(pd.DataFrame({
        "cik": z["cik"].astype("int64").to_numpy(), "parameter_id": "PR4-01",
        "ereignis_zeit": [zeit[t][0] for t in z["tag"]], "verfuegbar_ab": [zeit[t][1] for t in z["tag"]],
        "wert": z["art"].to_numpy(dtype="float64"), "stand": (z["liste"] + ":" + z["kennung"]).to_numpy()}))


# --------------------------------------------------------------------------- Lauf
def lauf(ablage: Ablage, abruf=None, heute: date | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    hinweise: list[str] = []
    firmen = ablage.lies_bereinigt("edgar_firmen")
    if firmen.empty:
        raise RuntimeError("Firmentabelle fehlt (Quelle edgar_index zuerst ausführen)")
    firmen = firmen[firmen["sic"].notna() | firmen["tickers"].notna()]
    heute = heute or datetime.now(ET).date()
    abruf = abruf or Abruf(anfragen_pro_sekunde=4)

    bestand = ablage.lies_bereinigt(TABELLE)
    if len(bestand):
        bestand["tag"] = pd.to_datetime(bestand["tag"])
    neu, seiten = [], {}
    for liste in LISTEN:
        alt = bestand[bestand["liste"] == liste] if len(bestand) else bestand
        # die AAER-Liste wiederholt Einträge der beiden anderen: bekannt ist dort alles aus dem Bestand
        bekannt = set(zip(bestand["adresse"], bestand["beteiligte"])) if len(bestand) else set()
        zeilen, seiten[liste] = lies_liste(abruf, liste, bekannt, alles=not len(alt))
        neu += zeilen
    frisch = pd.DataFrame(neu, columns=[s for s in SPALTEN if s != "art"])
    gelesen = int(len(frisch))
    if len(bestand):
        frisch = pd.concat([frisch, bestand[frisch.columns]], ignore_index=True)
    frisch["tag"] = pd.to_datetime(frisch["tag"])
    ereignisse = ordne_ein(frisch[frisch["tag"] <= pd.Timestamp(heute)])
    ablage.schreibe_bereinigt(TABELLE, "alle", ereignisse)

    zuordnung, unbekannt = ordne_zu(ereignisse, firmen)
    ablage.schreibe_bereinigt(TABELLE_ZUORDNUNG, "alle", zuordnung)
    parameter = baue_parameter(ereignisse, zuordnung)
    ablage.schreibe_parameter("sec_verfahren", parameter)

    if unbekannt:
        hinweise.append("Mütter der Töchterliste ohne eindeutigen Treffer bei EDGAR: " + ", ".join(unbekannt))
    mit_firma = zuordnung[zuordnung["cik"].notna()]
    je_liste = ereignisse.groupby("liste")["adresse"].count().to_dict()
    ohne = zuordnung[zuordnung["cik"].isna() & (zuordnung["art"] == "keiner")]["name"].value_counts()
    info = {"ereignisse": {k: int(v) for k, v in je_liste.items()}, "mit_aaer": int(ereignisse["aaer"].sum()),
            "seiten_gelesen": seiten, "zeilen_gelesen": gelesen,
            "juengster_tag": ereignisse["tag"].max().date().isoformat() if len(ereignisse) else None,
            "mit_firma": int(mit_firma["adresse"].nunique()), "firmen": int(parameter["cik"].nunique()) if len(parameter) else 0,
            "arten": zuordnung["art"].value_counts().to_dict(),
            "anteil_namen_zugeordnet": round(len(mit_firma) / max(len(mit_firma) + int(ohne.sum()), 1), 4),
            "haeufig_ohne_treffer": {str(k): int(v) for k, v in ohne.head(40).items()}}
    hinweise.append(f"{info['mit_firma']} von {len(ereignisse)} Veröffentlichungen nennen eine zugeordnete Firma")
    return parameter, info, hinweise
