"""Bestände institutioneller Anleger aus den Form-13F-Datensätzen der SEC (ab Berichtsquartal 2013 Q2).

Je Berichtsquartal zählen nur fristgerechte Erstmeldungen (13F-HR, eingereicht bis zur Frist von 45 Tagen
nach Quartalsende, an Wochenenden und Feiertagen bis zum nächsten Handelstag), ohne Optionen und ohne
Nennbeträge. Je Manager zählt die jüngste solche Meldung. Gespeichert werden Stückzahl und
Portfoliogewicht je Position, nicht der gemeldete Kurswert (keine Kurse im öffentlichen Repo).

Die Zuordnung CUSIP -> CIK kommt aus ``ftd_wertpapiere`` (Quelle sec_ftd). Die Kennzahlen entstehen auf
Firmenebene: Alle Stammaktien-CUSIP einer Firma zählen zusammen, damit ein CUSIP-Wechsel (Aktiensplit,
Umfirmierung, Sitzwechsel) nicht wie ein Aus- und Einstieg aller Halter aussieht.

  edgar_13f_quartal   je CUSIP: halter, stueck
  edgar_13f_firmen    je Firma: halter, beste_idee, breite_aenderung, manager, manager_beide, herkunft

Der Datensatz der SEC erscheint erst Wochen nach der Meldefrist. Bis dahin entsteht das jüngste Quartal aus den
einzelnen Meldungen (eine Einreichungsdatei je 13F-HR, Auswahl über das Meldungsverzeichnis), sobald das
Verzeichnis über den letzten Tag der Frist hinausreicht. Der Datensatz ersetzt dieses Quartal, wenn er erscheint.
"""
from __future__ import annotations

import csv
import io
import os
import re
import threading
import xml.etree.ElementTree as ET_XML
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.namen import trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab, ist_handelstag
from ..kern.zustand import Zeitbudget, merke_fortsetzung

SEITE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
LINK_MUSTER = re.compile(r'href="([^"]*?/(\d{4}q[1-4]|\d{2}[a-z]{3}\d{4}-\d{2}[a-z]{3}\d{4})_form13f\.zip)"', re.I)
FRIST_TAGE = 45
MIN_POSITIONEN, MAX_POSITIONEN = 10, 200
MINDEST_KONFIDENZ = 0.90
MONATE = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
TABELLE_DATEIEN, TABELLE_BESTAND = "edgar_13f_dateien", "edgar_13f_bestaende"
TABELLE_QUARTAL, TABELLE_FIRMEN = "edgar_13f_quartal", "edgar_13f_firmen"
SPALTEN_MELDUNG = ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]
SPALTEN_POSITION = ["ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"]
RELEASE_URL = "https://github.com/{repo}/releases/download/bereinigt-edgar/{datei}"
MELDUNG_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt"
EINZEL = "einzel-"                 # Vorsatz in edgar_13f_dateien: Quartal aus Einzelmeldungen
MAX_AUSFALL = 0.02                 # höchstens dieser Anteil der Meldungen darf fehlen oder unlesbar sein
PARALLEL = 4                       # gleichzeitige Abrufe; die Anfragegrenze des Abrufs gilt für alle zusammen
KOPF_FELD = re.compile(rb"^[ \t]*(CONFORMED SUBMISSION TYPE|CONFORMED PERIOD OF REPORT|FILED AS OF DATE|"
                       rb"CENTRAL INDEX KEY):[ \t]*(\S+)", re.M)
TABELLE_XML = re.compile(rb"<TYPE>INFORMATION TABLE.*?<XML>\s*(.*?)</XML>", re.S)
XML_FELDER = {"cusip", "value", "sshPrnamt", "sshPrnamtType", "putCall"}

_OFFEN = "amtlich offen: Form 13F (§ 13(f) Exchange Act), Frist 45 Tage nach Quartalsende"
_SCHWAECHEN = ("Nur Manager über 100 Mio. $ und nur gemeldete Long-Bestände; Nachträge und verspätete Meldungen "
               "bleiben außen vor; Zuordnung über die CUSIP-Tabelle der Lieferausfälle zum Zeitpunkt der Berechnung "
               "(Trefferquote im Prüfbericht); bis der Datensatz der SEC erscheint (Wochen nach der Frist), stammt "
               "das jüngste Quartal aus den Einzelmeldungen (Stand „… Einzelmeldungen“) und kann sich mit dem "
               "Datensatz geringfügig ändern")


def _p(id_, name, definition, einheit, schwaechen=""):
    return Parameter(id=id_, name=name, definition=definition, einheit=einheit, frequenz="je Berichtsquartal",
                     offenlegung=_OFFEN, quelle=SEITE, lizenz="gemeinfrei (US-Behörde)", historie_ab="2013",
                     verzoegerung="Eröffnung des ersten Handelstags nach Ablauf der Meldefrist",
                     schwaechen=(schwaechen + " " + _SCHWAECHEN).strip())


registriere(
    _p("IH5-04", "Eigentümerbreite (Änderung)",
       "Halter der Firma im Quartal minus Halter im Vorquartal, geteilt durch die Zahl der Manager; gezählt werden "
       "nur Manager, die in beiden Quartalen gemeldet haben (Chen, Hong & Stein 2002). Die Zahl der Halter selbst "
       "steht in der bereinigten Tabelle edgar_13f_firmen", "Anteil der Manager"),
    _p("IH5-03", "Beste Ideen der Manager",
       f"Zahl der Manager mit {MIN_POSITIONEN} bis {MAX_POSITIONEN} zugeordneten Aktien, deren größtes Übergewicht "
       "(Gewicht im Aktienportfolio des Managers minus Gewicht im Aktienbestand aller Manager) diese Firma ist; "
       "nur Werte ab 1", "Anzahl",
       "Vereinfachung von Anton, Cohen & Polk: Vergleich mit dem Gesamtbestand der 13F-Manager statt mit dem "
       "Marktgewicht, ohne Gewichtung mit der Kursschwankung."),
)


# --------------------------------------------------------------------------- Dateien und Zeitbezug
def links_aus_seite(html: str) -> dict[str, str]:
    aus: dict[str, str] = {}
    for href, schluessel in LINK_MUSTER.findall(html):
        aus.setdefault(schluessel.lower(), href if href.startswith("http") else "https://www.sec.gov" + href)
    return aus


def fensterende(schluessel: str) -> date:
    """Letzter Einreichungstag, den ein Datensatz abdeckt (zum Ordnen der Datensätze)."""
    m = re.fullmatch(r"(\d{4})q([1-4])", schluessel)
    if m:
        jahr, monat = int(m.group(1)), int(m.group(2)) * 3
        return date(jahr + (monat == 12), monat % 12 + 1, 1) - timedelta(days=1)
    m = re.fullmatch(r"\d{2}[a-z]{3}\d{4}-(\d{2})([a-z]{3})(\d{4})", schluessel)
    if not m or m.group(2) not in MONATE:
        raise ValueError(f"unbekannter Dateischlüssel: {schluessel}")
    return date(int(m.group(3)), MONATE[m.group(2)], int(m.group(1)))


def quartal_name(periode) -> str:
    p = pd.Timestamp(periode)
    return f"{p.year}q{(p.month - 1) // 3 + 1}"


def frist(periode) -> date:
    """Letzter fristgerechter Einreichungstag: 45 Tage nach Quartalsende, sonst der nächste Handelstag
    (z. B. 17.02.2026 für das vierte Quartal 2025: der 14.02. war ein Samstag, der 16.02. Presidents' Day)."""
    tag = pd.Timestamp(periode).date() + timedelta(days=FRIST_TAGE)
    while not ist_handelstag(tag):
        tag += timedelta(days=1)
    return tag


def verfuegbar_ab(periode) -> datetime:
    """Eröffnung des ersten Handelstags nach Ablauf der Frist: dann sind alle gezählten Meldungen öffentlich."""
    return handelbar_ab(datetime.combine(frist(periode), time(18, 0), tzinfo=ET))


def _datum(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    d = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    return d.fillna(pd.to_datetime(s.where(d.isna()), format="%Y-%m-%d", errors="coerce"))


def _mitglied(archiv: zipfile.ZipFile, name: str) -> str:
    for n in archiv.namelist():
        if n.rsplit("/", 1)[-1].upper() == name.upper():
            return n
    raise KeyError(f"{name} fehlt im Archiv (enthalten: {archiv.namelist()})")


def _kopf(archiv: zipfile.ZipFile, mitglied: str, pflicht: list[str]) -> dict[str, str]:
    """Ordnet den Pflichtspalten die Schreibweise der Datei zu."""
    with archiv.open(mitglied) as f:
        vorhanden = pd.read_csv(f, sep="\t", nrows=0, dtype=str, quoting=csv.QUOTE_NONE).columns.tolist()
    nach_name = {str(c).strip().upper(): c for c in vorhanden}
    fehlend = [s for s in pflicht if s not in nach_name]
    if fehlend:
        raise KeyError(f"Pflichtspalten fehlen {fehlend} in {mitglied} (vorhanden: {vorhanden})")
    return {nach_name[s]: s for s in pflicht}


def lies_archiv(zip_pfad: Path, blockgroesse: int = 1_000_000) -> tuple[pd.DataFrame, dict]:
    """Positionen der fristgerechten Erstmeldungen: periode, filer_cik, cusip, stueck, wert (wie gemeldet)."""
    with zipfile.ZipFile(zip_pfad) as archiv:
        m_sub, m_info = _mitglied(archiv, "SUBMISSION.tsv"), _mitglied(archiv, "INFOTABLE.tsv")
        spalten = _kopf(archiv, m_sub, SPALTEN_MELDUNG)
        with archiv.open(m_sub) as f:
            sub = pd.read_csv(f, sep="\t", dtype=str, usecols=list(spalten), quoting=csv.QUOTE_NONE).rename(columns=spalten)
        meldungen = len(sub)
        sub = sub[sub["SUBMISSIONTYPE"].astype(str).str.strip().str.upper() == "13F-HR"].copy()
        sub["eingereicht"], sub["periode"] = _datum(sub["FILING_DATE"]), _datum(sub["PERIODOFREPORT"])
        sub["filer_cik"] = pd.to_numeric(sub["CIK"], errors="coerce")
        sub = sub[sub["eingereicht"].notna() & sub["periode"].notna() & sub["filer_cik"].notna()]
        sub = sub[sub["periode"].dt.is_quarter_end]
        erst = int(len(sub))
        letzter_tag = sub["periode"].map({p: pd.Timestamp(frist(p)) for p in sub["periode"].unique()})
        sub = sub[(sub["eingereicht"] > sub["periode"]) & (sub["eingereicht"] <= letzter_tag)]
        sub = sub.sort_values(["eingereicht", "ACCESSION_NUMBER"]).drop_duplicates(["filer_cik", "periode"], keep="last")
        nach_acc = sub.set_index("ACCESSION_NUMBER")[["filer_cik", "periode"]]
        spalten = _kopf(archiv, m_info, SPALTEN_POSITION)
        teile, zeilen = [], 0
        with archiv.open(m_info) as f:
            for block in pd.read_csv(f, sep="\t", dtype=str, usecols=list(spalten), quoting=csv.QUOTE_NONE,
                                     on_bad_lines="skip", chunksize=blockgroesse, encoding="utf-8",
                                     encoding_errors="replace", keep_default_na=False):
                block = block.rename(columns=spalten)
                zeilen += len(block)
                block = block[block["ACCESSION_NUMBER"].isin(nach_acc.index)
                              & (block["PUTCALL"].str.strip() == "")
                              & (block["SSHPRNAMTTYPE"].str.strip().str.upper() == "SH")]
                block = block.assign(cusip=block["CUSIP"].str.strip().str.upper(),
                                     stueck=pd.to_numeric(block["SSHPRNAMT"], errors="coerce"),
                                     wert=pd.to_numeric(block["VALUE"], errors="coerce").fillna(0.0))
                block = block[(block["cusip"].str.len() == 9) & (block["stueck"] > 0) & (block["wert"] >= 0)]
                teile.append(block.groupby(["ACCESSION_NUMBER", "cusip"], as_index=False)[["stueck", "wert"]].sum())
    info = {"meldungen": int(meldungen), "erstmeldungen": erst, "fristgerecht": int(len(sub)), "positionszeilen": int(zeilen)}
    if not teile or not len(sub):
        return pd.DataFrame(columns=["periode", "filer_cik", "cusip", "stueck", "wert"]), info
    pos = pd.concat(teile, ignore_index=True).groupby(["ACCESSION_NUMBER", "cusip"], as_index=False)[["stueck", "wert"]].sum()
    pos = pos.join(nach_acc, on="ACCESSION_NUMBER")
    pos["filer_cik"] = pos["filer_cik"].astype("int64")
    return pos[["periode", "filer_cik", "cusip", "stueck", "wert"]], info


# --------------------------------------------------------------------------- Einzelmeldungen (Quartal ohne Datensatz)
def periode_von(name: str) -> pd.Timestamp:
    """Quartalsende zu einem Namen wie ``2026q3``."""
    m = re.fullmatch(r"(\d{4})q([1-4])", str(name).strip().lower())
    if not m:
        raise ValueError(f"kein Quartal: {name}")
    return (pd.Timestamp(int(m.group(1)), int(m.group(2)) * 3, 1) + pd.offsets.MonthEnd(0)).normalize()


def vorlaeufige_quartale(dateien: pd.DataFrame) -> set[pd.Timestamp]:
    """Berichtsquartale aus Einzelmeldungen, die noch in keinem gelesenen Datensatz der SEC stehen."""
    if dateien.empty:
        return set()
    einzel = dateien["datei"].astype(str).str.startswith(EINZEL)

    def namen(s: pd.Series) -> set[str]:
        return {n for text in s for n in str(text).split(",") if n}

    return {periode_von(n) for n in namen(dateien.loc[einzel, "quartale"]) - namen(dateien.loc[~einzel, "quartale"])}


def offene_quartale(letztes, stand: date) -> list[pd.Timestamp]:
    """Berichtsquartale nach ``letztes``, deren Meldefrist vor dem Stand des Meldungsverzeichnisses abgelaufen ist.

    ``stand`` ist das jüngste Einreichungsdatum im Verzeichnis. Liegt es nach dem letzten Tag der Frist, enthält
    das Verzeichnis alle fristgerechten Meldungen: Ein späteres Datum tragen nur Meldungen, die nach dem
    Annahmeschluss (17:30 Uhr Ostküste) des letzten Tags eingegangen sind."""
    aus, p = [], (pd.Timestamp(letztes) + pd.offsets.QuarterEnd(1)).normalize()
    while frist(p) < stand:
        aus.append(p)
        p = (p + pd.offsets.QuarterEnd(1)).normalize()
    return aus


def waehle_meldungen(meldungen: pd.DataFrame, periode) -> pd.DataFrame:
    """Erstmeldungen (13F-HR) eines Berichtsquartals im Meldungsverzeichnis, eingereicht bis zur Frist.
    Meldungen ohne Berichtsdatum im Verzeichnis bleiben dabei; ihr Kopf entscheidet."""
    periode = pd.Timestamp(periode)
    m = meldungen[(meldungen["form"] == "13F-HR") & (meldungen["filing_date"] > periode)
                  & (meldungen["filing_date"] <= pd.Timestamp(frist(periode)))
                  & (meldungen["report_date"].isna() | (meldungen["report_date"] == periode))]
    return m.sort_values(["filing_date", "accession"], kind="stable").drop_duplicates("accession").reset_index(drop=True)


def _zahl(text: str | None) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return float("nan")


def lies_meldung(inhalt: bytes) -> tuple[dict, pd.DataFrame]:
    """Kopf und Positionen einer Einreichungsdatei (13F-HR), Auswahl wie in :func:`lies_archiv`:
    ohne Optionen, nur Stückzahlen, je CUSIP summiert. Rückgabe: Kopf und Tabelle cusip, stueck, wert."""
    ende = inhalt.find(b"</SEC-HEADER>")
    felder: dict[str, str] = {}
    for name, wert in KOPF_FELD.findall(inhalt[:ende if ende >= 0 else 20_000]):
        felder.setdefault(name.decode("ascii"), wert.decode("latin-1"))
    tabellen = TABELLE_XML.findall(inhalt)
    if not tabellen:
        raise ValueError("keine Informationstabelle")
    summe: dict[str, list[float]] = {}
    zeilen = 0
    for xml in tabellen:
        feld: dict[str, str] = {}
        for _, k in ET_XML.iterparse(io.BytesIO(xml)):
            name = k.tag.rsplit("}", 1)[-1]
            if name in XML_FELDER:
                feld[name] = (k.text or "").strip()
            elif name == "infoTable":
                zeilen += 1
                if not feld.get("putCall") and feld.get("sshPrnamtType", "").upper() == "SH":
                    cusip, stueck, wert = feld.get("cusip", "").upper(), _zahl(feld.get("sshPrnamt")), _zahl(feld.get("value"))
                    wert = 0.0 if wert != wert else wert
                    if len(cusip) == 9 and stueck > 0 and wert >= 0:
                        s = summe.setdefault(cusip, [0.0, 0.0])
                        s[0] += stueck
                        s[1] += wert
                feld = {}
                k.clear()
    kopf = {"form": felder.get("CONFORMED SUBMISSION TYPE"),
            "periode": pd.to_datetime(felder.get("CONFORMED PERIOD OF REPORT", ""), format="%Y%m%d", errors="coerce"),
            "eingereicht": pd.to_datetime(felder.get("FILED AS OF DATE", ""), format="%Y%m%d", errors="coerce"),
            "filer_cik": pd.to_numeric(felder.get("CENTRAL INDEX KEY", ""), errors="coerce"), "zeilen": zeilen}
    pos = pd.DataFrame({"cusip": list(summe), "stueck": [s[0] for s in summe.values()],
                        "wert": [s[1] for s in summe.values()]}).astype({"cusip": str, "stueck": "float64", "wert": "float64"})
    return kopf, pos


def lies_einzelmeldungen(kandidaten: pd.DataFrame, periode, abruf, budget: Zeitbudget,
                         max_fehler: int = 25) -> tuple[pd.DataFrame | None, dict]:
    """Positionen eines Berichtsquartals aus den einzelnen Meldungen, in der Form von :func:`lies_archiv`.

    Je Manager zählt die jüngste fristgerechte Meldung. Fehlen zu viele Meldungen (Abruf, Aufbau, Zeitbudget),
    ist das Ergebnis ``None``: Ein halb gelesenes Quartal sähe wie ein Rückgang der Halter aus."""
    periode = pd.Timestamp(periode)
    letzter = pd.Timestamp(frist(periode))
    koepfe, teile, status, fehler_in_folge = [], {}, Counter(), 0
    abbruch = threading.Event()

    def hole(z) -> tuple[str, tuple | None]:
        if abbruch.is_set() or budget.abgelaufen():
            return "offen", None
        try:
            antwort = abruf.hole(MELDUNG_URL.format(cik=int(z.cik), accession=z.accession), erlaube_404=True)
        except QuelleNichtErreichbar:
            return "abruffehler", None
        if antwort is None:
            return "fehlt", None
        try:
            return "gelesen", lies_meldung(antwort.content)
        except (ET_XML.ParseError, ValueError):
            return "unlesbar", None

    # mehrere Abrufe zugleich: die Antwortzeit der SEC, nicht die Anfragegrenze, bestimmt sonst die Dauer
    with ThreadPoolExecutor(max_workers=PARALLEL) as becken:
        zeilen = list(kandidaten.itertuples(index=False))
        for nr, (z, (art, ergebnis)) in enumerate(zip(zeilen, becken.map(hole, zeilen))):
            if nr and nr % 1000 == 0:
                print(f"13F {quartal_name(periode)}: {nr} von {len(zeilen)} Meldungen gelesen", flush=True)
            fehler_in_folge = fehler_in_folge + 1 if art == "abruffehler" else 0
            if fehler_in_folge >= max_fehler:
                abbruch.set()                                 # die übrigen Abrufe enden sofort
                raise QuelleNichtErreichbar(f"{max_fehler} Abruffehler in Folge bei den 13F-Einzelmeldungen")
            if ergebnis is None:
                status[art] += 1
                continue
            kopf, pos = ergebnis
            eingereicht = kopf["eingereicht"] if pd.notna(kopf["eingereicht"]) else pd.Timestamp(z.filing_date)
            if kopf["form"] != "13F-HR" or kopf["periode"] != periode or pd.isna(kopf["filer_cik"]) \
                    or not (periode < eingereicht <= letzter):
                status["anderes_quartal"] += 1
                continue
            status["gelesen"] += 1
            koepfe.append((z.accession, int(kopf["filer_cik"]), eingereicht, kopf["zeilen"]))
            teile[z.accession] = pos
    ausfall = status["offen"] + status["abruffehler"] + status["fehlt"] + status["unlesbar"]
    info = {"meldungen": int(len(kandidaten)), "erstmeldungen": int(status["gelesen"]), "fristgerecht": 0,
            "positionszeilen": int(sum(k[3] for k in koepfe)), "status": dict(status)}
    if not koepfe or ausfall > MAX_AUSFALL * len(kandidaten):
        return None, info
    k = pd.DataFrame(koepfe, columns=["accession", "filer_cik", "eingereicht", "zeilen"])
    k = k.sort_values(["eingereicht", "accession"]).drop_duplicates("filer_cik", keep="last")
    info["fristgerecht"] = int(len(k))
    stuecke = [teile[a].assign(filer_cik=c) for a, c in zip(k["accession"], k["filer_cik"]) if len(teile[a])]
    if not stuecke:
        return None, info
    pos = pd.concat(stuecke, ignore_index=True).assign(periode=periode)
    return pos[["periode", "filer_cik", "cusip", "stueck", "wert"]], info


def vergleiche(alt: pd.DataFrame, neu: pd.DataFrame) -> dict:
    """Übereinstimmung zweier Zählungen der Halter je CUSIP (Einzelmeldungen gegen Datensatz)."""
    a, b = alt.set_index("cusip")["halter"], neu.set_index("cusip")["halter"]
    alle = a.index.union(b.index)
    a, b = a.reindex(alle, fill_value=0), b.reindex(alle, fill_value=0)
    return {"papiere": int(len(alle)), "halter_gleich": round(float((a == b).mean()), 4) if len(alle) else 0.0,
            "halter_alt": int(a.sum()), "halter_neu": int(b.sum())}


def _verzeichnis(ablage: Ablage, ab_jahr: int) -> tuple[pd.DataFrame, date | None]:
    """13F-HR-Meldungen ab ``ab_jahr`` und das jüngste Einreichungsdatum im Meldungsverzeichnis."""
    pfade = sorted(ablage.bereinigt.glob("bereinigt__edgar_meldungen__*.parquet"))
    if not pfade:
        return pd.DataFrame(), None
    stand = pd.read_parquet(pfade[-1], columns=["filing_date"])["filing_date"].max()
    spalten = ["cik", "accession", "form", "filing_date", "report_date"]
    teile = [pd.read_parquet(p, columns=spalten, filters=[("form", "in", ["13F-HR"])]) for p in pfade
             if int(p.name.split("__")[2].removesuffix(".parquet")) >= ab_jahr]
    teile = [t for t in teile if len(t)]
    meldungen = pd.concat(teile, ignore_index=True) if teile else pd.DataFrame(columns=spalten)
    return meldungen, (None if pd.isna(stand) else pd.Timestamp(stand).date())


# --------------------------------------------------------------------------- Kennzahlen je Quartal
def verdichte(pos: pd.DataFrame, zu_firma: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Aus den Positionen eines Quartals: Bestand mit Portfoliogewicht, Kennzahlen je CUSIP, Kennzahlen je Firma.

    ``zu_firma``: CUSIP -> CIK für Stammaktien. Die besten Ideen entstehen im Aktienportfolio je Manager
    (nur zugeordnete Aktien, Gattungen einer Firma zusammengefasst).
    """
    summe = pos.groupby("filer_cik")["wert"].transform("sum")
    gewicht = (pos["wert"] / summe.where(summe > 0)).astype("float64")
    bestand = pd.DataFrame({"filer_cik": pos["filer_cik"].to_numpy(), "cusip": pos["cusip"].to_numpy(),
                            "stueck": pos["stueck"].round().astype("int64").to_numpy(),
                            "gewicht": gewicht.astype("float32").to_numpy()})
    bestand = bestand.sort_values(["filer_cik", "cusip"], kind="stable").reset_index(drop=True)
    je_cusip = pos.groupby("cusip").agg(halter=("filer_cik", "nunique"), stueck=("stueck", "sum"))
    je_cusip["stueck"] = je_cusip["stueck"].round().astype("int64")
    manager = int(pos["filer_cik"].nunique())

    cik = pos["cusip"].map(zu_firma)
    a = pos[cik.notna()].assign(cik=cik[cik.notna()].astype("int64"))
    if a.empty:
        return bestand, je_cusip.reset_index(), pd.DataFrame(columns=["cik", "halter", "beste_idee", "manager"])
    je_firma = a.groupby("cik").agg(halter=("filer_cik", "nunique"))
    # Wert einer Firma im Gesamtbestand: Stückzahl mal mittlerem gemeldetem Wert je Stück (Median über die
    # Manager); der Median fängt Manager ab, die in der falschen Einheit melden (Tausend statt Dollar)
    mitte = (a["wert"] / a["stueck"]).where(a["wert"] > 0).groupby(a["cusip"]).median()
    je_papier = a.groupby("cusip").agg(stueck=("stueck", "sum"), cik=("cik", "first"))
    gesamt = (je_papier["stueck"] * mitte.reindex(je_papier.index)).fillna(0.0).groupby(je_papier["cik"]).sum()
    vergleich = gesamt / gesamt.sum() if gesamt.sum() > 0 else gesamt
    fa = a.groupby(["filer_cik", "cik"], as_index=False)["wert"].sum()
    je_manager = fa.groupby("filer_cik")["wert"].agg(["sum", "size"])
    aktiv = fa["filer_cik"].map((je_manager["size"] >= MIN_POSITIONEN) & (je_manager["size"] <= MAX_POSITIONEN)
                                & (je_manager["sum"] > 0)).to_numpy()
    je_firma["beste_idee"] = 0
    if aktiv.any():
        f = fa[aktiv]
        ueber = f["wert"] / f["filer_cik"].map(je_manager["sum"]) - f["cik"].map(vergleich)
        beste = f.loc[ueber.groupby(f["filer_cik"]).idxmax(), "cik"].value_counts()
        je_firma["beste_idee"] = beste.reindex(je_firma.index).fillna(0).astype("int64")
    je_firma["manager"] = manager
    return bestand, je_cusip.reset_index(), je_firma.reset_index()


def breite_aenderung(heute: pd.DataFrame, vor: pd.DataFrame, zu_firma: pd.Series) -> pd.DataFrame:
    """Änderung der Eigentümerbreite je Firma unter Managern, die in beiden Quartalen gemeldet haben.

    ``heute`` und ``vor``: Bestände (filer_cik, cusip). Firmen, die niemand mehr hält, erscheinen mit negativem Wert.
    """
    beide = np.intersect1d(heute["filer_cik"].unique(), vor["filer_cik"].unique())
    if not len(beide):
        return pd.DataFrame(columns=["cik", "breite_aenderung", "manager_beide"])

    def halter(bestand: pd.DataFrame) -> pd.Series:
        b = bestand[bestand["filer_cik"].isin(beide)]
        cik = b["cusip"].map(zu_firma)
        return b[cik.notna()].groupby(cik[cik.notna()].astype("int64"))["filer_cik"].nunique()

    h1, h0 = halter(heute), halter(vor)
    alle = h1.index.union(h0.index)
    d = (h1.reindex(alle, fill_value=0) - h0.reindex(alle, fill_value=0)) / len(beide)
    return pd.DataFrame({"cik": alle.to_numpy(dtype="int64"), "breite_aenderung": d.to_numpy(dtype="float64"),
                         "manager_beide": len(beide)})


def baue_parameter(firmen: pd.DataFrame) -> pd.DataFrame:
    if firmen.empty:
        return leer()
    q = firmen.assign(periode=pd.to_datetime(firmen["periode"]))
    einzel = set(q.loc[q["herkunft"] == "einzelmeldungen", "periode"]) if "herkunft" in q.columns else set()
    zeit = {p: (pd.Timestamp(datetime.combine(p.date(), time(18, 0), tzinfo=ET)).tz_convert("UTC"),
                pd.Timestamp(verfuegbar_ab(p)), quartal_name(p) + (" Einzelmeldungen" if p in einzel else ""))
            for p in q["periode"].drop_duplicates()}
    teile = []
    for pid, tabelle, spalte in (("IH5-04", q[q["breite_aenderung"].notna()], "breite_aenderung"),
                                 ("IH5-03", q[q["beste_idee"] >= 1], "beste_idee")):
        if tabelle.empty:
            continue
        teile.append(pd.DataFrame({
            "cik": tabelle["cik"].to_numpy(dtype="int64"), "parameter_id": pid,
            "ereignis_zeit": [zeit[p][0] for p in tabelle["periode"]],
            "verfuegbar_ab": [zeit[p][1] for p in tabelle["periode"]],
            "wert": tabelle[spalte].to_numpy(dtype="float64"), "stand": [zeit[p][2] for p in tabelle["periode"]]}))
    return als_parameter(pd.concat(teile, ignore_index=True)) if teile else leer()


# --------------------------------------------------------------------------- Lauf
def _bestand_pfad(ablage: Ablage, periode) -> Path:
    return ablage.bereinigt / f"bereinigt__{TABELLE_BESTAND}__{quartal_name(periode)}.parquet"


def _lies_bestand(ablage: Ablage, arbeits: Path, periode, fern: bool) -> pd.DataFrame | None:
    """Manager und CUSIP eines Quartals: aus der Ablage, sonst aus dem Release (die Bestände früherer Quartale
    werden im Tagesbetrieb nicht mitgeführt; gebraucht wird nur das Vorquartal eines neuen Datensatzes)."""
    pfad = _bestand_pfad(ablage, periode)
    if not pfad.exists():
        repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        if not fern or not repo:
            return None
        try:
            pfad = Abruf(anfragen_pro_sekunde=2, kontakt_noetig=False).hole_datei(
                RELEASE_URL.format(repo=repo, datei=pfad.name), Path(arbeits) / "f13" / pfad.name, erlaube_404=True)
        except QuelleNichtErreichbar:
            return None
        if pfad is None:
            return None
    return pd.read_parquet(pfad, columns=["filer_cik", "cusip"]).astype({"cusip": str})


def lauf(ablage: Ablage, arbeits: Path, modus: str = "laufend", abruf: Abruf | None = None, lokal: Path | None = None,
         budget: Zeitbudget | None = None, pruefe_quartal: str | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    """``pruefe_quartal``: liest ein Quartal, das schon aus einem Datensatz stammt, zusätzlich aus den
    Einzelmeldungen und meldet die Übereinstimmung (schreibt nichts)."""
    hinweise: list[str] = []
    zuordnung = ablage.lies_bereinigt("ftd_wertpapiere", spalten=["cusip", "cik", "konfidenz", "stamm", "art"])
    if zuordnung.empty:
        raise RuntimeError("CUSIP-Zuordnung fehlt (Quelle sec_ftd zuerst ausführen)")
    gut = zuordnung[zuordnung["cik"].notna() & zuordnung["stamm"] & (zuordnung["konfidenz"] >= MINDEST_KONFIDENZ)]
    zu_firma = gut.drop_duplicates("cusip").set_index("cusip")["cik"].astype("int64")
    if lokal is not None:
        quellen = links_aus_seite(" ".join(f'href="/{p.name}"' for p in sorted(Path(lokal).glob("*.zip"))))
        quellen = {k: str(Path(lokal) / Path(v).name) for k, v in quellen.items()}
    else:
        abruf = abruf or Abruf()
        quellen = links_aus_seite(abruf.hole(SEITE).text)
    if not quellen:
        raise RuntimeError("Datenseite nennt keine Datensätze (Aufbau geändert?)")
    budget = budget or Zeitbudget()
    dateien = ablage.lies_bereinigt(TABELLE_DATEIEN)
    quartal = ablage.lies_bereinigt(TABELLE_QUARTAL)
    firmen = ablage.lies_bereinigt(TABELLE_FIRMEN)
    for tabelle in (quartal, firmen):
        if len(tabelle):
            tabelle["periode"] = pd.to_datetime(tabelle["periode"])
    if "herkunft" in firmen.columns:
        firmen = firmen.drop(columns="herkunft")             # wird am Ende aus dem Stand der Dateien gesetzt
    gelesen = set(dateien["datei"]) if len(dateien) else set()
    offen = [k for k in sorted(quellen, key=fensterende, reverse=True) if k not in gelesen]      # neueste zuerst
    neu, neu_einzel, geaendert, abgebrochen = [], [], set(), False
    vorhanden = set(quartal["periode"]) if len(quartal) else set()
    vorlaeufig = vorlaeufige_quartale(dateien) & vorhanden   # aus Einzelmeldungen, noch ohne Datensatz der SEC

    def nimm_auf(periode: pd.Timestamp, teil: pd.DataFrame) -> pd.DataFrame:
        nonlocal quartal, firmen
        periode = pd.Timestamp(periode).as_unit("ns")
        vorhanden.add(periode)
        geaendert.add(periode)
        bestand, je_cusip, je_firma = verdichte(teil, zu_firma)
        ablage.schreibe_bereinigt(TABELLE_BESTAND, quartal_name(periode), bestand.astype({"cusip": "category"}))
        je_cusip = je_cusip.assign(periode=periode)
        je_firma = je_firma.assign(periode=periode, breite_aenderung=np.nan, manager_beide=0)
        quartal = pd.concat([quartal, je_cusip], ignore_index=True) if len(quartal) else je_cusip
        firmen = pd.concat([firmen, je_firma], ignore_index=True) if len(firmen) else je_firma
        return je_cusip

    for schluessel in offen:
        if budget.abgelaufen():
            abgebrochen = True
            break
        if lokal is not None:
            pfad = Path(quellen[schluessel])
        else:
            pfad = abruf.hole_datei(quellen[schluessel], Path(arbeits) / "f13" / f"{schluessel}.zip")
        pos, info = lies_archiv(pfad)
        if lokal is None:
            pfad.unlink(missing_ok=True)
        for periode, teil in pos.groupby("periode"):
            periode = pd.Timestamp(periode)
            if periode in vorhanden and periode not in vorlaeufig:      # ein Quartal wird nur einmal geschrieben
                continue
            alt = None
            if periode in vorlaeufig:                        # der Datensatz ersetzt das Quartal aus Einzelmeldungen
                alt = quartal[quartal["periode"] == periode]
                quartal, firmen = quartal[quartal["periode"] != periode], firmen[firmen["periode"] != periode]
                vorlaeufig.discard(periode)
            je_cusip = nimm_auf(periode, teil)
            if alt is not None:
                v = vergleiche(alt, je_cusip)
                hinweise.append(f"{quartal_name(periode)}: Datensatz der SEC ersetzt die Einzelmeldungen; Zahl der Halter "
                                f"gleich bei {v['halter_gleich']:.1%} von {v['papiere']} Wertpapieren (Summe "
                                f"{v['halter_alt']} -> {v['halter_neu']})")
        neu.append({"datei": schluessel, **info, "quartale": ",".join(sorted(quartal_name(p) for p in pos["periode"].unique()))})

    # Quartale ohne Datensatz der SEC: aus den einzelnen Meldungen, sobald das Verzeichnis die Frist abdeckt
    einzel_info: dict = {}
    meldungen, stand = (pd.DataFrame(), None)
    if vorhanden and not abgebrochen:
        ab_jahr = min([max(vorhanden).year] + ([periode_von(pruefe_quartal).year] if pruefe_quartal else []))
        meldungen, stand = _verzeichnis(ablage, ab_jahr)
        if stand is None:
            hinweise.append("Meldungsverzeichnis fehlt: Quartale ohne Datensatz der SEC werden nicht ergänzt")
        for periode in (offene_quartale(max(vorhanden), stand) if stand is not None else []):
            name = quartal_name(periode)
            kandidaten = waehle_meldungen(meldungen, periode)
            if kandidaten.empty:
                hinweise.append(f"{name}: keine 13F-HR im Meldungsverzeichnis")
                break
            abruf = abruf or Abruf()
            pos, e = lies_einzelmeldungen(kandidaten, periode, abruf, budget)
            einzel_info[name] = {**e, "vollstaendig": pos is not None}
            if pos is None:                                  # spätere Quartale brauchen dieses als Vorquartal
                hinweise.append(f"{name}: Einzelmeldungen unvollständig ({e['status']}); der nächste Lauf liest neu")
                break
            nimm_auf(periode, pos)
            vorlaeufig.add(periode)
            neu_einzel.append({"datei": EINZEL + name, **{k: v for k, v in e.items() if k != "status"}, "quartale": name})
            hinweise.append(f"{name}: aus {e['erstmeldungen']} Einzelmeldungen gebaut ({e['status']}); gilt, bis der "
                            "Datensatz der SEC erscheint")
    if neu or neu_einzel:
        zusatz = pd.DataFrame(neu + neu_einzel)
        dateien = pd.concat([dateien, zusatz], ignore_index=True) if len(dateien) else zusatz
    if dateien.empty or quartal.empty:
        raise RuntimeError("kein Datensatz gelesen")
    ablage.schreibe_bereinigt(TABELLE_DATEIEN, "alle", dateien)
    quartal = quartal.sort_values(["periode", "cusip"], kind="stable").reset_index(drop=True)
    ablage.schreibe_bereinigt(TABELLE_QUARTAL, "alle", quartal)

    # Breite: für jedes neue Quartal und für das Quartal nach einem neuen, sofern beide Bestände vorliegen
    ohne_vorquartal = 0
    for p in sorted(vorhanden):
        vor = (p - pd.offsets.QuarterEnd(1)).normalize()
        if (p not in geaendert and vor not in geaendert) or vor not in vorhanden:
            continue
        heute = _lies_bestand(ablage, arbeits, p, fern=lokal is None)
        davor = _lies_bestand(ablage, arbeits, vor, fern=lokal is None) if heute is not None else None
        if heute is None or davor is None:
            ohne_vorquartal += p in geaendert
            continue
        d = breite_aenderung(heute, davor, zu_firma)
        teil = firmen[firmen["periode"] == p].drop(columns=["breite_aenderung", "manager_beide"])
        manager = int(teil["manager"].max()) if len(teil) else int(heute["filer_cik"].nunique())
        teil = teil.merge(d, on="cik", how="outer").assign(periode=p, manager=manager)
        for s in ("halter", "beste_idee"):
            teil[s] = teil[s].fillna(0).astype("int64")
        teil["manager_beide"] = int(d["manager_beide"].max()) if len(d) else 0
        teil["breite_aenderung"] = teil["breite_aenderung"].fillna(0.0)      # nur von neuen Managern gehalten
        firmen = pd.concat([firmen[firmen["periode"] != p], teil], ignore_index=True)
    if len(firmen):
        firmen = firmen.astype({"cik": "int64"}).sort_values(["periode", "cik"], kind="stable").reset_index(drop=True)
        firmen["herkunft"] = np.where(firmen["periode"].isin(list(vorlaeufig)), "einzelmeldungen", "datensatz")
        ablage.schreibe_bereinigt(TABELLE_FIRMEN, "alle", firmen)

    parameter = baue_parameter(firmen)
    ablage.schreibe_parameter("edgar_13f", parameter)

    vergleich: dict = {}
    if pruefe_quartal:                                       # Gegenprobe: Einzelmeldungen gegen ein Quartal des Datensatzes
        periode = periode_von(pruefe_quartal)
        amtlich = quartal[quartal["periode"] == periode]
        kandidaten = waehle_meldungen(meldungen, periode) if len(meldungen) else meldungen
        if amtlich.empty or periode in vorlaeufig or kandidaten.empty:
            vergleich = {"quartal": pruefe_quartal, "vollstaendig": False, "grund": "Quartal oder Meldungsverzeichnis fehlt"}
        else:
            pos, e = lies_einzelmeldungen(kandidaten, periode, abruf or Abruf(), budget)
            vergleich = {"quartal": pruefe_quartal, "vollstaendig": pos is not None, **e}
            if pos is not None:
                je_cusip = verdichte(pos, zu_firma)[1]
                vergleich.update(vergleiche(amtlich, je_cusip), manager_einzel=int(pos["filer_cik"].nunique()),
                                 manager_datensatz=int(firmen.loc[firmen["periode"] == periode, "manager"].max()))
                hinweise.append(f"Gegenprobe {pruefe_quartal}: Zahl der Halter aus Einzelmeldungen und Datensatz gleich bei "
                                f"{vergleich['halter_gleich']:.1%} von {vergleich['papiere']} Wertpapieren")
    rest = len([k for k in quellen if k not in set(dateien["datei"])])
    if abgebrochen and modus == "rueckwaerts":
        merke_fortsetzung(ablage.wurzel, "edgar_13f")
    if rest:
        hinweise.append(f"{rest} Datensätze noch nicht gelesen (Zeitbudget; der nächste Lauf setzt fort)")
    if ohne_vorquartal:
        hinweise.append(f"{ohne_vorquartal} neue Quartale ohne Bestand des Vorquartals: Änderung der Breite fehlt")
    juengstes = quartal[(quartal["periode"] == quartal["periode"].max()) & (quartal["halter"] >= 10)].reset_index(drop=True)
    z = juengstes[["cusip"]].merge(gut[["cusip", "cik", "art"]].drop_duplicates("cusip"), on="cusip", how="left")
    z["art"] = z["art"].fillna("keiner")
    quote = trefferquote(z, gewicht=juengstes["halter"].astype("float64")) if len(z) else {"zeilen": 0, "quote": 0.0, "arten": {}}
    hinweise.append(f"Zuordnung: {quote.get('quote', 0):.1%} der Wertpapiere mit mindestens 10 Haltern im jüngsten Quartal "
                    f"({quote.get('quote_gewichtet', 0):.1%} nach Haltern gewichtet); der Rest sind vor allem Fonds")
    amtlich_gelesen = int((~dateien["datei"].astype(str).str.startswith(EINZEL)).sum())
    info = {"datensaetze_verzeichnis": len(quellen), "datensaetze_gelesen": amtlich_gelesen, "datensaetze_neu": len(neu),
            "quartale": int(quartal["periode"].nunique()), "juengstes_quartal": quartal_name(quartal["periode"].max()),
            "manager_juengstes": int(firmen.loc[firmen["periode"] == firmen["periode"].max(), "manager"].max()) if len(firmen) else 0,
            "firmen_juengstes": int((firmen["periode"] == firmen["periode"].max()).sum()) if len(firmen) else 0,
            "trefferquote": quote, "aus_einzelmeldungen": sorted(quartal_name(p) for p in vorlaeufig)}
    if einzel_info:
        info["einzelmeldungen"] = einzel_info
    if vergleich:
        info["vergleich"] = vergleich
    return parameter, info, hinweise
