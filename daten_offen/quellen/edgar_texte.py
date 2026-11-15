"""Texte der Jahres- und Quartalsberichte (10-K, 10-Q) → UA5-01, UA5-03, UA5-04, UA2-05.

Je Bericht wird das Hauptdokument aus dem EDGAR-Archiv gelesen, in Wörter zerlegt und mit dem Bericht derselben Art
ein Jahr zuvor verglichen (Cohen, Malloy & Nguyen 2020, „Lazy Prices“): Kosinus-Ähnlichkeit der Worthäufigkeiten und
Jaccard-Ähnlichkeit der Wortmengen, für den ganzen Text und für den Abschnitt Item 1A (Risikofaktoren) der 10-K.
Dazu Textlänge und der Hinweis auf erhebliche Zweifel an der Fortführung (Going Concern).

Gespeichert werden nur Kennzahlen, nicht die Texte.

  edgar_texte__<jahr>   je Bericht: Vorgänger, Wörter, Ähnlichkeiten, Risikoteil, Going Concern, Stand des Abrufs
"""
from __future__ import annotations

import html
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab_serie
from ..kern.zustand import Zeitbudget, merke_fortsetzung

TABELLE = "edgar_texte"
ARCHIV = "https://www.sec.gov/Archives/edgar/data/{cik}/{ordner}/{datei}"
JAHR = {"10-K", "10-K405", "10-KSB", "10-KT"}
QUARTAL = {"10-Q", "10-QSB", "10-QT"}
VORJAHR_TAGE = (330, 400)          # Berichtsstichtag des Vorgängers: 330 bis 400 Tage früher
MIN_WOERTER = 500                  # kürzere Texte sind Deckblätter oder Verweise auf Anlagen
MIN_RISIKO = 200                   # kürzere Risikoteile sind Verweise („nicht anwendbar“)
PARALLEL = 8
SPALTEN = ["accession", "cik", "form", "report_date", "filing_date", "status", "bytes", "woerter", "vorgaenger",
           "cosinus", "jaccard", "risiko_woerter", "risiko_cosinus", "risiko_jaccard", "going_concern"]
STOPP = set("""a about above after again against all also am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here hers him his
how i if in into is it its itself just me more most my no nor not now of off on once only or other our ours out over own same
she should so some such than that the their theirs them then there these they this those through to too under until up very
was we were what when where which while who whom why will with would you your yours shall may might must upon within without
per via""".split())

WORT = re.compile(r"[a-z]{2,}")
IX_KOPF = re.compile(rb"<ix:header>.*?</ix:header>", re.S | re.I)
SKRIPT = re.compile(rb"<(script|style)\b.*?</\1\s*>", re.S | re.I)
MARKE = re.compile(rb"<[^>]*>", re.S)
DOKUMENT = re.compile(rb"<DOCUMENT>.*?</DOCUMENT>", re.S | re.I)
LEER = re.compile(r"\s+")
_T = r"\s*[.:\-–—]?\s*"
RISIKO_ANFANG = re.compile(r"item\s*1a" + _T + r"risk\s+factors")
RISIKO_ENDE = re.compile(r"item\s*(?:1b" + _T + r"unresolved\s+staff\s+comments|1c" + _T + r"cybersecurity|2" + _T + r"properties)")
ZWEIFEL = re.compile(r"substantial doubt")
AFFIRMATIV = re.compile(r"\b(?:raise|raises|raised|there is|there was|there exists|exists|existed|indicate|indicates|"
                        r"indicated|create|creates|created|give rise to|gives rise to|gave rise to)\b[^.]{0,15}$")
BEDINGT = re.compile(r"\b(?:could|may|might|would|will|if|whether|not|no|cannot|can|potential|possible|unless)\b[^.]{0,25}$")
VORSCHRIFT = re.compile(r"\b(?:asu|accounting standards update|standard|guidance|requires?|evaluate whether|assess whether)\b")

_G = "gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise)"
_Q = "SEC EDGAR, Hauptdokument des Berichts im Archiv (https://www.sec.gov/Archives/edgar/data/)"


def _p(id_, name, definition, einheit, schwaechen, frequenz="je Bericht"):
    return Parameter(id=id_, name=name, definition=definition, einheit=einheit, frequenz=frequenz, offenlegung=_G, quelle=_Q,
                     lizenz="gemeinfrei (US-Behörde); gespeichert werden nur Kennzahlen", historie_ab="2006 (Vergleich ab 2007)",
                     verzoegerung="Annahmezeit des Berichts (aus edgar_index)", schwaechen=schwaechen)


registriere(
    _p("UA5-01", "Änderungsgrad des Berichts",
       "Kosinus-Ähnlichkeit der Worthäufigkeiten des Berichts mit dem Bericht derselben Art ein Jahr zuvor (10-K mit "
       "10-K, 10-Q mit dem 10-Q desselben Quartals); Wörter aus mindestens zwei Buchstaben ohne Füllwörter, ohne Zahlen. "
       "Niedrig = stark geändert (Cohen, Malloy & Nguyen 2020). Die Jaccard-Ähnlichkeit steht in edgar_texte",
       "Ähnlichkeit 0–1", "Nur das Hauptdokument, ohne Anlagen; Berichte unter 500 Wörtern (Verweise auf Anlagen) ohne Wert"),
    _p("UA5-03", "Änderung der Risikofaktoren",
       "Kosinus-Ähnlichkeit des Abschnitts Item 1A (Risikofaktoren) des 10-K mit dem Abschnitt des Vorjahres-10-K; "
       "nur wenn beide Abschnitte mindestens 200 Wörter haben", "Ähnlichkeit 0–1",
       "Abschnitt über die Überschriften „Item 1A Risk Factors“ bis „Item 1B“, „Item 1C“ oder „Item 2“ gefunden; "
       "abweichende Gliederungen fehlen. Item 3 (Rechtsstreitigkeiten) ist nicht getrennt", frequenz="je Jahresbericht"),
    _p("UA5-04", "Länge des Berichts", "Zahl der Wörter des Hauptdokuments (Loughran & McDonald 2014: Dateigröße als "
       "Maß der Lesbarkeit)", "Wörter", "Ohne Anlagen; seit 2019 zählen die Zahlen der Inline-XBRL-Tabellen nicht mit"),
    _p("UA2-05", "Zweifel an der Fortführung (Going Concern)",
       "1 = der Bericht stellt erhebliche Zweifel an der Fortführung fest („substantial doubt … going concern“, nicht in "
       "bedingter oder verneinter Form), 0 = nicht", "Kennzeichen 0/1",
       "Textsuche statt des Prüfvermerks; bedingte Aussagen in Risikofaktoren werden verworfen, erkannt aber nur an "
       "Signalwörtern unmittelbar davor"),
)


# --------------------------------------------------------------------------- Text
def text_aus(inhalt: bytes) -> str:
    """Lesbarer Text in Kleinbuchstaben; bei einer vollständigen Einreichung (.txt) nur das erste Dokument."""
    erstes = DOKUMENT.search(inhalt)
    if erstes:
        inhalt = erstes.group(0)
    inhalt = MARKE.sub(b" ", SKRIPT.sub(b" ", IX_KOPF.sub(b" ", inhalt)))
    return LEER.sub(" ", html.unescape(inhalt.decode("utf-8", errors="replace"))).lower()


def woerter(text: str) -> Counter:
    return Counter(w for w in WORT.findall(text) if w not in STOPP)


def risikoteil(text: str) -> str:
    """Längster Abschnitt von einer Überschrift „Item 1A Risk Factors“ bis zur nächsten folgenden Überschrift."""
    enden = [m.start() for m in RISIKO_ENDE.finditer(text)]
    beste = (0, 0)
    for m in RISIKO_ANFANG.finditer(text):
        ende = next((e for e in enden if e > m.start()), None)
        if ende is not None and ende - m.start() > beste[1] - beste[0]:
            beste = (m.start(), ende)
    return text[beste[0]:beste[1]]


def going_concern(text: str) -> bool:
    """Feststellung erheblicher Zweifel an der Fortführung: „substantial doubt“ mit „going concern“ im selben Satz,
    unmittelbar davor ein feststellendes Verb (raise, there is, indicate …), kein bedingendes oder verneinendes Wort
    und keine Beschreibung der Rechnungslegungsvorschrift (ASU 2014-15)."""
    for m in ZWEIFEL.finditer(text):
        nach = text[m.end():m.end() + 150].split(".")[0]
        vor_satz = text[max(0, m.start() - 150):m.start()].split(".")[-1]
        if "going concern" not in nach and "going concern" not in vor_satz:
            continue
        davor = text[max(0, m.start() - 60):m.start()]
        if AFFIRMATIV.search(davor) and not BEDINGT.search(davor) and not VORSCHRIFT.search(text[max(0, m.start() - 200):m.start()]):
            return True
    return False


def aehnlichkeit(a: Counter | None, b: Counter | None) -> tuple[float, float]:
    """Kosinus der Häufigkeiten und Jaccard der Wortmengen."""
    if not a or not b:
        return np.nan, np.nan
    klein, gross = (a, b) if len(a) < len(b) else (b, a)
    punkt = sum(n * gross.get(w, 0) for w, n in klein.items())
    norm = np.sqrt(sum(n * n for n in a.values())) * np.sqrt(sum(n * n for n in b.values()))
    gemeinsam = sum(1 for w in klein if w in gross)
    return float(punkt / norm), float(gemeinsam / (len(a) + len(b) - gemeinsam))


def merkmale(inhalt: bytes, jahresbericht: bool) -> dict:
    text = text_aus(inhalt)
    tf = woerter(text)
    n = sum(tf.values())
    risiko = woerter(risikoteil(text)) if jahresbericht else Counter()
    return {"bytes": len(inhalt), "woerter": n, "tf": tf if n >= MIN_WOERTER else None,
            "risiko_woerter": sum(risiko.values()) if jahresbericht else np.nan,
            "risiko_tf": risiko if sum(risiko.values()) >= MIN_RISIKO else None, "going_concern": float(going_concern(text))}


# --------------------------------------------------------------------------- Berichte und Vorgänger
def berichte(meldungen: pd.DataFrame) -> pd.DataFrame:
    """Erstfassungen der 10-K und 10-Q mit Vorgänger (Bericht derselben Art, Stichtag 330 bis 400 Tage früher)."""
    b = meldungen[meldungen["form"].isin(JAHR | QUARTAL) & meldungen["report_date"].notna()].copy()
    b["art"] = np.where(b["form"].isin(JAHR), "K", "Q")
    b["report_date"] = pd.to_datetime(b["report_date"])
    b = b.sort_values(["cik", "art", "report_date", "filing_date"], kind="stable").drop_duplicates(["cik", "art", "report_date"])
    b = b.reset_index(drop=True)
    vorgaenger = [None] * len(b)
    for (_, _), g in b.groupby(["cik", "art"], sort=False):
        tage = g["report_date"].to_numpy().astype("datetime64[D]").astype("int64")
        accs = g["accession"].to_numpy()
        for i, idx in enumerate(g.index):
            beste = None
            for j in range(i - 1, -1, -1):
                abstand = tage[i] - tage[j]
                if abstand > VORJAHR_TAGE[1]:
                    break
                if abstand >= VORJAHR_TAGE[0] and (beste is None or abs(abstand - 365) < beste[0]):
                    beste = (abs(abstand - 365), accs[j])
            vorgaenger[idx] = beste[1] if beste else None
    b["vorgaenger"] = vorgaenger
    return b


def adresse(cik: int, accession: str, dokument: str | None) -> str | None:
    if not dokument or not isinstance(dokument, str):
        return None
    return ARCHIV.format(cik=int(cik), ordner=accession.replace("-", ""), datei=dokument.split("/")[-1])


def _hole(abruf, zeile) -> tuple[str, str, dict | None]:
    url = adresse(zeile.cik, zeile.accession, zeile.primary_document)
    if url is None:
        return zeile.accession, "kein_dokument", None
    try:
        antwort = abruf.hole(url, erlaube_404=True)
    except QuelleNichtErreichbar:
        return zeile.accession, "fehler", None
    if antwort is None:
        return zeile.accession, "fehlt", None
    try:
        return zeile.accession, "gelesen", merkmale(antwort.content, zeile.art == "K")
    except Exception:  # ein kaputtes Dokument darf den Lauf nicht beenden
        return zeile.accession, "unlesbar", None


def bearbeite(abruf, offen: pd.DataFrame, alle: pd.DataFrame, pool: ThreadPoolExecutor) -> list[dict]:
    """Liest die offenen Berichte einer Firma und ihre Vorgänger und vergleicht sie."""
    noetig = set(offen["accession"]) | set(offen["vorgaenger"].dropna())
    holen = alle[alle["accession"].isin(noetig)]
    ergebnisse = {acc: (status, m) for acc, status, m in pool.map(lambda z: _hole(abruf, z), holen.itertuples(index=False))}
    zeilen = []
    for z in offen.itertuples(index=False):
        status, m = ergebnisse.get(z.accession, ("fehler", None))
        if status == "fehler":
            continue                                   # beim nächsten Lauf erneut versuchen
        vor = ergebnisse.get(z.vorgaenger, (None, None))[1] if isinstance(z.vorgaenger, str) else None
        cos, jac = aehnlichkeit(m["tf"] if m else None, vor["tf"] if vor else None)
        rcos, rjac = aehnlichkeit(m["risiko_tf"] if m else None, vor["risiko_tf"] if vor else None)
        zeilen.append({"accession": z.accession, "cik": int(z.cik), "form": z.form, "report_date": z.report_date,
                       "filing_date": z.filing_date, "status": status, "bytes": m["bytes"] if m else np.nan,
                       "woerter": m["woerter"] if m else np.nan, "vorgaenger": z.vorgaenger, "cosinus": cos, "jaccard": jac,
                       "risiko_woerter": m["risiko_woerter"] if m else np.nan, "risiko_cosinus": rcos, "risiko_jaccard": rjac,
                       "going_concern": m["going_concern"] if m else np.nan})
    return zeilen


# --------------------------------------------------------------------------- Parameter
def baue_parameter(ergebnisse: pd.DataFrame, meldungen: pd.DataFrame) -> pd.DataFrame:
    e = ergebnisse[ergebnisse["status"] == "gelesen"].copy()
    if e.empty:
        return leer()
    zeit = meldungen[["accession", "annahme_utc", "verfuegbar_ab"]].sort_values("annahme_utc").drop_duplicates("accession")
    e = e.merge(zeit[["accession", "verfuegbar_ab"]], on="accession", how="left")
    e["verfuegbar_ab"] = pd.to_datetime(e["verfuegbar_ab"], utc=True).astype("datetime64[us, UTC]")
    fehlt = e["verfuegbar_ab"].isna()
    if fehlt.any():
        ersatz = (pd.to_datetime(e.loc[fehlt, "filing_date"]) + pd.Timedelta(hours=17, minutes=30)).dt.tz_localize(
            ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
        e.loc[fehlt, "verfuegbar_ab"] = handelbar_ab_serie(ersatz).astype("datetime64[us, UTC]")
    e["ereignis_zeit"] = pd.to_datetime(e["report_date"]).dt.tz_localize(ET).dt.tz_convert("UTC")
    lang = e["woerter"] >= MIN_WOERTER
    jahr = e["form"].isin(JAHR)
    teile = []
    for pid, maske, spalte in (("UA5-01", e["cosinus"].notna(), "cosinus"), ("UA5-03", jahr & e["risiko_cosinus"].notna(), "risiko_cosinus"),
                               ("UA5-04", lang, "woerter"), ("UA2-05", lang, "going_concern")):
        t = e[maske]
        if len(t):
            teile.append(pd.DataFrame({"cik": t["cik"].to_numpy(dtype="int64"), "parameter_id": pid,
                                       "ereignis_zeit": t["ereignis_zeit"].to_numpy(), "verfuegbar_ab": t["verfuegbar_ab"].to_numpy(),
                                       "wert": t[spalte].to_numpy(dtype="float64"), "stand": t["accession"].to_numpy()}))
    return als_parameter(pd.concat(teile, ignore_index=True)) if teile else leer()


# --------------------------------------------------------------------------- Lauf
def lauf(ablage: Ablage, abruf=None, budget: Zeitbudget | None = None, parallel: int = PARALLEL) -> tuple[pd.DataFrame, dict, list[str]]:
    """Liest alle Berichte ohne Ergebnis, Firma für Firma (Firmen mit Börsenticker zuerst), bis das Zeitbudget endet."""
    hinweise: list[str] = []
    budget = budget or Zeitbudget()
    meldungen = ablage.lies_bereinigt("edgar_meldungen", spalten=["cik", "accession", "form", "report_date", "filing_date",
                                                                  "primary_document", "annahme_utc", "verfuegbar_ab"],
                                      filter=[("form", "in", sorted(JAHR | QUARTAL))])
    if meldungen.empty:
        raise RuntimeError("Meldungsverzeichnis fehlt (Quelle edgar_index zuerst ausführen)")
    alle = berichte(meldungen)
    bestand = ablage.lies_bereinigt(TABELLE)
    fertig = set(bestand["accession"]) if len(bestand) else set()
    offen = alle[~alle["accession"].isin(fertig)]
    firmen = ablage.lies_bereinigt("edgar_firmen", spalten=["cik", "tickers"])
    boerse = set(firmen.loc[firmen["tickers"].notna(), "cik"].astype(int)) if len(firmen) else set()
    reihenfolge = sorted(offen["cik"].unique(), key=lambda c: (int(c) not in boerse, int(c)))
    abruf = abruf or Abruf()
    neu, abgebrochen, firmen_fertig = [], False, 0
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        nach_firma = dict(tuple(offen.groupby("cik", sort=False)))
        for cik in reihenfolge:
            if budget.abgelaufen():
                abgebrochen = True
                break
            neu += bearbeite(abruf, nach_firma[cik], alle[alle["cik"] == cik], pool)
            firmen_fertig += 1
    if neu:
        frisch = pd.DataFrame(neu, columns=SPALTEN)
        bestand = pd.concat([bestand, frisch], ignore_index=True) if len(bestand) else frisch
    if bestand.empty:
        if not abgebrochen:
            raise RuntimeError("kein Bericht gelesen")
        merke_fortsetzung(ablage.wurzel, "edgar_texte")
        return leer(), {"berichte": int(len(alle)), "neu": 0, "offen": int(len(offen)), "unvollstaendig": True}, hinweise
    bestand["filing_date"] = pd.to_datetime(bestand["filing_date"])
    bestand["report_date"] = pd.to_datetime(bestand["report_date"])
    for jahr, teil in bestand.groupby(bestand["filing_date"].dt.year):
        ablage.schreibe_bereinigt(TABELLE, str(int(jahr)), teil.sort_values(["filing_date", "accession"]).reset_index(drop=True)[SPALTEN])
    parameter = baue_parameter(bestand, meldungen)
    ablage.schreibe_parameter("edgar_texte", parameter)
    rest = int(len(offen) - len(neu))
    if abgebrochen:
        merke_fortsetzung(ablage.wurzel, "edgar_texte")
        hinweise.append(f"Zeitbudget erreicht: {rest} Berichte offen; der Lauf setzt sich fort")
    status = bestand["status"].value_counts().to_dict()
    gelesen = bestand[bestand["status"] == "gelesen"]
    info = {"berichte": int(len(alle)), "neu": len(neu), "offen": rest, "firmen_bearbeitet": firmen_fertig,
            "unvollstaendig": abgebrochen, "status": {k: int(v) for k, v in status.items()},
            "anteil_mit_vergleich": round(float(gelesen["cosinus"].notna().mean()), 4) if len(gelesen) else 0.0,
            "anteil_risikoteil_10k": round(float((gelesen.loc[gelesen["form"].isin(JAHR), "risiko_woerter"] >= MIN_RISIKO).mean()), 4)
            if len(gelesen) else 0.0,
            "anteil_going_concern": round(float(gelesen["going_concern"].mean()), 4) if len(gelesen) else 0.0,
            "abrufe": int(abruf.anfragen) if isinstance(getattr(abruf, "anfragen", None), int) else 0}
    return parameter, info, hinweise
