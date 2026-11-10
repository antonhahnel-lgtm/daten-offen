"""Insidergeschäfte aus den amtlichen SEC-Datensätzen (Forms 3, 4, 5) und daraus die IH1-Parameter.

Quelle: SEC Insider Transactions Data Sets (je Quartal eine Zip-Datei, ab 2006).
Die Annahmezeit je Meldung stammt aus dem Meldungsverzeichnis (edgar_index).
Parameter, die Kurse brauchen (Marktkapitalisierung, Trefferbilanz), entstehen im privaten Repo.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET_XML
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.schema import MARKT_CIK, Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab_serie, monatsende_handelbar
from ..kern.zustand import Zeitbudget, merke_fortsetzung

DATEN_SEITE = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
LINK_MUSTER = re.compile(r'href="([^"]*?(\d{4}q\d)_form345\.zip)"')
AUSUEBUNG_GEWICHT = 0.25  # wie sale_oe_weight im Insider-Monitor
# Rückfall, falls die Datenseite nicht lesbar ist; die SEC hat den Ablageort schon verlegt.
DATEN_URLS = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{jahr}q{q}_form345.zip",
    "https://www.sec.gov/files/dera/data/form-345/{jahr}q{q}_form345.zip",
)
TABELLE = "insider_transaktionen"
# Für die Parameter genügen Käufe und Verkäufe; der Rest der bereinigten Tabelle bleibt auf der Platte.
RECHEN_SPALTEN = ["accession", "zeile", "trans_date", "code", "erwerb", "stueck", "preis", "bestand_danach", "form",
                  "filing_date", "issuer_cik", "owner_cik", "plan_10b5_1", "ist_direktor", "ist_officer",
                  "ist_zehn_prozent", "titel", "mit_ausuebung", "wert_usd", "quartal"]
MELDE_FORMEN = ["3", "4", "5", "3/A", "4/A", "5/A", "8-K"]
MELDE_SPALTEN = ["cik", "accession", "form", "items", "annahme_utc", "verfuegbar_ab", "annahme_geschaetzt"]
_Q = "SEC Insider Transactions Data Sets (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets)"
_L = "gemeinfrei (US-Behörde)"
_G = "gesetzlich: Section 16(a) Exchange Act, Form 4, Frist 2 Geschäftstage"
VORSTAND = re.compile(r"\b(?:ceo|chief executive|principal executive|cfo|chief financial|principal financial|"
                      r"chairman|chairwoman|chair of the board|executive chair|chair)\b", re.I)


def _p(id_, name, definition, einheit, schwaechen="", frequenz="je Kaufmeldung", historie="2006", vor=True):
    return Parameter(id=id_, name=name, definition=definition, einheit=einheit, frequenz=frequenz,
                     offenlegung=_G, quelle=_Q, lizenz=_L, historie_ab=historie,
                     verzoegerung="Annahmezeit der Meldung (aus edgar_index)", schwaechen=schwaechen,
                     ereignis_vor_verfuegbar=vor)


registriere(
    _p("IH1-01", "Clusterkauf (30 Tage)",
       "Zahl verschiedener firmeneigener Insider (ohne 10-%-Eigner ohne Amt) mit Käufen am offenen Markt "
       "(Code P) bei derselben Firma in den 30 Tagen bis zum Kauf, einschließlich des Käufers; nur zum "
       "Meldezeitpunkt bereits bekannte Käufe (entspricht n_cluster_1m im Insider-Monitor)",
       "Anzahl Personen"),
    _p("IH1-02", "Rang des Käufers",
       "4 = CEO/CFO/Chair, 3 = sonstiger Officer, 2 = nur Direktor (externer Direktor), "
       "1 = 10-%-Eigner ohne Amt, 0 = Sonstige", "Stufe 0–4",
       schwaechen="Titel sind Freitext; bei mehreren Meldenden zählt die erstgenannte Person"),
    _p("IH1-03", "Kaufsumme", "Summe Stück × Preis der Käufe einer Meldung", "US-Dollar",
       schwaechen="Verhältnis zu Marktkapitalisierung und Gehalt wird im privaten Repo gebildet"),
    _p("IH1-04", "Routine- oder opportunistischer Kauf",
       "1 = Routine (Kauf derselben Aktie im selben Kalendermonat in mindestens zwei Vorjahren), "
       "0 = opportunistisch (Käufe in mindestens zwei Vorjahren, nie im selben Monat); externe Käufer und "
       "Käufer mit weniger Historie ohne Wert. Definition des Insider-Monitors (f_routine, f_opportun)",
       "Kennzeichen 0/1", historie="2008"),
    _p("IH1-05", "Tage seit letzter Zahlenmeldung",
       "Kalendertage zwischen der letzten 8-K mit Item 2.02 der Firma und dem Kauftag", "Tage",
       schwaechen="Meldungen am Kauftag selbst zählen nicht; Abstand zum nächsten Termin fehlt "
                  "(Terminschätzung im privaten Repo)"),
    _p("IH1-06", "Netto-Kaufquote der Firma (6 Monate)",
       "(Käufe − Verkäufe) / (Käufe + Verkäufe) in US-Dollar, Codes P und S aller Insider der Firma in den "
       "182 Tagen bis zum Kauf; Verkäufe aus Meldungen mit Optionsausübung (Code M) zählen zu 25 % "
       "(wie sale_oe_weight im Insider-Monitor); nur zum Meldezeitpunkt bekannte Geschäfte", "Quote −1 bis +1",
       schwaechen="Kurzfrist-Händler werden anders als im Insider-Monitor nicht abgewertet"),
    _p("IH1-07", "10b5-1-Kennzeichen", "1 = Meldung als Geschäft unter einem 10b5-1-Plan gekennzeichnet, 0 = nicht",
       "Kennzeichen 0/1", historie="04/2023", schwaechen="vor 04/2023 nicht vorhanden"),
    _p("IH1-09", "Vorlauf bis Meldung", "Kalendertage zwischen letztem Kauftag und Einreichungsdatum", "Tage"),
    _p("IH1-10", "Bestandsaufstockung", "gekaufte Stück / Bestand vor dem Kauf", "Verhältnis",
       schwaechen="nur wenn der Bestand nach dem Kauf gemeldet ist und über der Kaufmenge liegt"),
    _p("IH1-17", "Käufer verkauft binnen 30 Tagen",
       "Verkauf (Code S) derselben Person höchstens 30 Tage nach einem eigenen Kauf; Zeile am Verkaufstag",
       "Kennzeichen (1 = Ereignis)", frequenz="je Verkaufsmeldung"),
    _p("IH1-18", "Tagescluster",
       "Zahl anderer firmeneigener Insider mit Käufen bei derselben Firma am Kauftag oder in den zwei Tagen "
       "davor; nur zum Meldezeitpunkt bekannte Käufe (Alldredge & Blank 2019). Neu vergebene ID, im Katalog "
       "nachzutragen",
       "Anzahl Personen"),
    _p("WS3-01", "Wochentag und Tageszeit der Meldung",
       "Für Kaufmeldungen: Wochentag (0 = Montag) + Stunde/24 der Annahmezeit in Ostküstenzeit",
       "Wochentag + Tagesbruchteil", schwaechen="nur bei bekannter Annahmezeit"),
    Parameter(id="IH1-16", name="Insider-Kaufanteil des Marktes",
              definition="Anteil der Kaufmeldungen an allen Kauf- und Verkaufsmeldungen ab 25.000 US-Dollar, "
                         "je Monat der Verfügbarkeit", einheit="Anteil 0–1", frequenz="monatlich",
              offenlegung=_G, quelle=_Q, lizenz=_L, historie_ab="2006",
              verzoegerung="Eröffnung des ersten Handelstags nach Monatsende",
              schwaechen="Marktweite Größe (cik = 0)"),
)


# --------------------------------------------------------------------------- Einlesen
def links_aus_seite(html: str) -> dict[str, str]:
    """Quartal -> Download-Adresse aus der SEC-Datenseite."""
    aus = {}
    for href, teil in LINK_MUSTER.findall(html):
        aus[teil] = href if href.startswith("http") else "https://www.sec.gov" + href
    return aus


def quartale(ab_jahr: int, heute: date) -> list[tuple[int, int]]:
    """Alle abgeschlossenen Quartale von ``ab_jahr`` bis vor ``heute``."""
    aus = []
    for jahr in range(ab_jahr, heute.year + 1):
        for q in range(1, 5):
            ende = date(jahr + (q == 4), q * 3 % 12 + 1, 1)
            if ende <= heute:
                aus.append((jahr, q))
    return aus


def _lies_tsv(archiv: zipfile.ZipFile, name: str) -> pd.DataFrame:
    treffer = [n for n in archiv.namelist() if Path(n).name.upper() == name.upper()]
    if not treffer:
        raise KeyError(f"{name} fehlt im Archiv (enthalten: {archiv.namelist()})")
    with archiv.open(treffer[0]) as f:
        text = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
        df = pd.read_csv(text, sep="\t", dtype=str, quoting=csv.QUOTE_NONE, keep_default_na=False,
                         na_values=[""], on_bad_lines="skip")
    df.columns = [c.strip().upper() for c in df.columns]
    return df


def _sp(df: pd.DataFrame, name: str) -> pd.Series:
    """Spalte oder leere Spalte, falls die Quelle sie nicht führt."""
    if name in df.columns:
        return df[name]
    return pd.Series([None] * len(df), index=df.index, dtype=object)


def _datum(s: pd.Series) -> pd.Series:
    """Liest Datumsangaben im Format 31-MAR-2024 oder 2024-03-31."""
    s = s.astype("string").str.strip()
    a = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    b = pd.to_datetime(s.where(a.isna()), format="%Y-%m-%d", errors="coerce")
    return a.fillna(b)


def _wahr(s: pd.Series) -> pd.Series:
    t = s.astype("string").str.strip().str.lower()
    aus = pd.Series(np.nan, index=s.index, dtype="float64")
    aus[t.isin(["1", "true", "y", "yes"])] = 1.0
    aus[t.isin(["0", "false", "n", "no"])] = 0.0
    return aus


def lies_quartal(zip_pfad: Path, teil: str) -> pd.DataFrame:
    """Liest ein Quartalsarchiv und liefert die nicht-derivativen Geschäfte in einheitlicher Form."""
    with zipfile.ZipFile(zip_pfad) as archiv:
        sub = _lies_tsv(archiv, "SUBMISSION.tsv")
        own = _lies_tsv(archiv, "REPORTINGOWNER.tsv")
        tr = _lies_tsv(archiv, "NONDERIV_TRANS.tsv")
    pflicht = {
        "SUBMISSION": (sub, ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"]),
        "REPORTINGOWNER": (own, ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"]),
        "NONDERIV_TRANS": (tr, ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                                "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"]),
    }
    for name, (df, spalten) in pflicht.items():
        fehlend = [c for c in spalten if c not in df.columns]
        if fehlend:
            raise KeyError(f"{name}: Pflichtspalten fehlen {fehlend} (vorhanden: {list(df.columns)})")
    kopf = pd.DataFrame({
        "accession": sub["ACCESSION_NUMBER"].str.strip(),
        "form": _sp(sub, "DOCUMENT_TYPE").astype("string").str.strip(),
        "filing_date": _datum(_sp(sub, "FILING_DATE")),
        "issuer_cik": pd.to_numeric(_sp(sub, "ISSUERCIK"), errors="coerce"),
        "issuer_ticker": _sp(sub, "ISSUERTRADINGSYMBOL").astype("string").str.strip().str.upper(),
        "plan_10b5_1": _wahr(_sp(sub, "AFF10B5ONE")),
    }).drop_duplicates("accession")
    own = own.assign(_acc=own["ACCESSION_NUMBER"].str.strip())
    anzahl = own.groupby("_acc").size().rename("n_meldende")
    erster = own.drop_duplicates("_acc")
    bez = _sp(erster, "RPTOWNER_RELATIONSHIP").astype("string").str.lower().fillna("")
    person = pd.DataFrame({
        "accession": erster["_acc"].to_numpy(),
        "owner_cik": pd.to_numeric(_sp(erster, "RPTOWNERCIK"), errors="coerce").to_numpy(),
        "owner_name": _sp(erster, "RPTOWNERNAME").astype("string").str.strip().to_numpy(),
        "ist_direktor": bez.str.contains("director").to_numpy(),
        "ist_officer": bez.str.contains("officer").to_numpy(),
        "ist_zehn_prozent": bez.str.contains("ten").to_numpy(),
        "titel": _sp(erster, "RPTOWNER_TITLE").astype("string").str.strip().to_numpy(),
    }).merge(anzahl, left_on="accession", right_index=True, how="left")
    gesch = pd.DataFrame({
        "accession": tr["ACCESSION_NUMBER"].str.strip(),
        "zeile": np.arange(len(tr)),
        "trans_date": _datum(_sp(tr, "TRANS_DATE")),
        "code": _sp(tr, "TRANS_CODE").astype("string").str.strip().str.upper(),
        "erwerb": _sp(tr, "TRANS_ACQUIRED_DISP_CD").astype("string").str.strip().str.upper(),
        "stueck": pd.to_numeric(_sp(tr, "TRANS_SHARES"), errors="coerce"),
        "preis": pd.to_numeric(_sp(tr, "TRANS_PRICEPERSHARE"), errors="coerce"),
        "bestand_danach": pd.to_numeric(_sp(tr, "SHRS_OWND_FOLWNG_TRANS"), errors="coerce"),
        "direkt_indirekt": _sp(tr, "DIRECT_INDIRECT_OWNERSHIP").astype("string").str.strip().str.upper(),
    })
    mit_ausuebung = set(gesch.loc[gesch["code"] == "M", "accession"])
    gesch["mit_ausuebung"] = gesch["accession"].isin(mit_ausuebung)
    df = gesch.merge(kopf, on="accession", how="inner").merge(person, on="accession", how="left")
    df["wert_usd"] = df["stueck"] * df["preis"]
    df["quartal"] = teil
    df["herkunft"] = "datensatz"
    df = df[df["issuer_cik"].notna() & df["owner_cik"].notna() & df["filing_date"].notna()].copy()
    df["issuer_cik"] = df["issuer_cik"].astype("int64")
    df["owner_cik"] = df["owner_cik"].astype("int64")
    for s in ("ist_direktor", "ist_officer", "ist_zehn_prozent", "mit_ausuebung"):
        df[s] = df[s].fillna(False).astype(bool)
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- Laufende Ergänzung aus Form-4-Dateien
XML_STAND = "insider_xml_stand"
ARCHIV = "https://www.sec.gov/Archives/edgar/data/{cik}/{ordner}/{datei}"
SPALTEN = ["accession", "zeile", "trans_date", "code", "erwerb", "stueck", "preis", "bestand_danach",
           "direkt_indirekt", "mit_ausuebung", "form", "filing_date", "issuer_cik", "issuer_ticker", "plan_10b5_1",
           "owner_cik", "owner_name", "ist_direktor", "ist_officer", "ist_zehn_prozent", "titel", "n_meldende",
           "wert_usd", "quartal", "herkunft"]


def xml_adresse(cik: int, accession: str, primary_document: str | None) -> str | None:
    """Adresse der Rohdatei einer Form-4-Meldung. Das Verzeichnis nennt die Ansichtsfassung
    (``xslF345X05/datei.xml``); die Rohdatei liegt ohne diesen Ordner daneben."""
    if not primary_document or not str(primary_document).lower().endswith(".xml"):
        return None
    datei = str(primary_document).split("/")[-1]
    return ARCHIV.format(cik=int(cik), ordner=accession.replace("-", ""), datei=datei)


def _text(knoten, pfad: str) -> str | None:
    """Text eines Unterknotens; viele Felder tragen ihren Wert in einem Unterknoten <value>."""
    if knoten is None:
        return None
    k = knoten.find(pfad)
    if k is None:
        return None
    w = k.find("value")
    t = (w.text if w is not None else k.text) or ""
    return t.strip() or None


def _ja(text: str | None) -> bool:
    return str(text or "").strip().lower() in ("1", "true", "y", "yes")


def lies_form4_xml(inhalt: bytes, accession: str, filing_date, teil: str) -> pd.DataFrame:
    """Liest eine Form-4-Rohdatei (ownershipDocument) in die Form der Quartalsdatensätze."""
    wurzel = ET_XML.fromstring(inhalt)
    if wurzel.tag != "ownershipDocument":
        raise ValueError(f"unerwartetes Wurzelelement {wurzel.tag}")
    personen = wurzel.findall("reportingOwner")
    erste = personen[0] if personen else None
    bez = erste.find("reportingOwnerRelationship") if erste is not None else None
    plan = _text(wurzel, "aff10b5One")
    kopf = {
        "accession": accession, "form": _text(wurzel, "documentType"),
        "filing_date": pd.Timestamp(filing_date),
        "issuer_cik": pd.to_numeric(_text(wurzel, "issuer/issuerCik"), errors="coerce"),
        "issuer_ticker": (_text(wurzel, "issuer/issuerTradingSymbol") or "").upper() or None,
        "plan_10b5_1": np.nan if plan is None else float(_ja(plan)),
        "owner_cik": pd.to_numeric(_text(erste, "reportingOwnerId/rptOwnerCik"), errors="coerce"),
        "owner_name": _text(erste, "reportingOwnerId/rptOwnerName"),
        "ist_direktor": _ja(_text(bez, "isDirector")), "ist_officer": _ja(_text(bez, "isOfficer")),
        "ist_zehn_prozent": _ja(_text(bez, "isTenPercentOwner")), "titel": _text(bez, "officerTitle"),
        "n_meldende": len(personen), "quartal": teil, "herkunft": "xml",
    }
    zeilen = []
    for i, t in enumerate(wurzel.findall("nonDerivativeTable/nonDerivativeTransaction")):
        tag = (_text(t, "transactionDate") or "")[:10]
        zeilen.append({
            "zeile": i, "trans_date": pd.to_datetime(tag, format="%Y-%m-%d", errors="coerce"),
            "code": (_text(t, "transactionCoding/transactionCode") or "").upper() or None,
            "erwerb": (_text(t, "transactionAmounts/transactionAcquiredDisposedCode") or "").upper() or None,
            "stueck": pd.to_numeric(_text(t, "transactionAmounts/transactionShares"), errors="coerce"),
            "preis": pd.to_numeric(_text(t, "transactionAmounts/transactionPricePerShare"), errors="coerce"),
            "bestand_danach": pd.to_numeric(_text(t, "postTransactionAmounts/sharesOwnedFollowingTransaction"), errors="coerce"),
            "direkt_indirekt": (_text(t, "ownershipNature/directOrIndirectOwnership") or "").upper() or None,
        })
    if not zeilen or pd.isna(kopf["issuer_cik"]) or pd.isna(kopf["owner_cik"]):
        return pd.DataFrame(columns=SPALTEN)
    df = pd.DataFrame(zeilen).assign(**kopf)
    df["mit_ausuebung"] = (df["code"] == "M").any()
    df["wert_usd"] = df["stueck"] * df["preis"]
    df["issuer_cik"] = df["issuer_cik"].astype("int64")
    df["owner_cik"] = df["owner_cik"].astype("int64")
    return df[SPALTEN]


def _quartal_von(tag: date) -> tuple[int, int]:
    return tag.year, (tag.month - 1) // 3 + 1


def amtliche_quartale(ablage: Ablage) -> set[str]:
    """Quartale, die aus einem amtlichen Datensatz stammen (nicht aus einzelnen Form-4-Dateien)."""
    aus = set()
    for pfad in ablage.bereinigt.glob(f"bereinigt__{TABELLE}__*.parquet"):
        teil = pfad.name.split("__")[2].removesuffix(".parquet")
        if "herkunft" not in pq.read_schema(pfad).names:
            aus.add(teil)
            continue
        herkunft = set(pq.read_table(pfad, columns=["herkunft"]).column("herkunft").unique().to_pylist())
        if herkunft == {"datensatz"}:
            aus.add(teil)
    return aus


def ergaenze_aus_xml(ablage: Ablage, abruf, budget: Zeitbudget, teil: str, meldungen: pd.DataFrame,
                     max_fehler: int = 25) -> dict:
    """Baut oder erweitert ein Quartal, für das die SEC noch keinen Datensatz veröffentlicht hat,
    aus den einzelnen Form-4-Dateien. ``meldungen``: Verzeichniszeilen der Formulare 4 und 4/A des Quartals.
    Bereits gelesene Aktenzeichen werden nicht erneut abgerufen."""
    stand_pfad = ablage.bereinigt / f"bereinigt__{XML_STAND}__{teil}.parquet"
    daten_pfad = ablage.bereinigt / f"bereinigt__{TABELLE}__{teil}.parquet"
    gesehen = pd.read_parquet(stand_pfad) if stand_pfad.exists() else pd.DataFrame(columns=["accession", "status"])
    alt = pd.read_parquet(daten_pfad) if daten_pfad.exists() else pd.DataFrame(columns=SPALTEN)
    if len(alt) and "herkunft" in alt.columns and (alt["herkunft"] == "datensatz").all():
        return {"quartal": teil, "neu": 0, "offen": 0, "amtlicher_datensatz": True}
    kandidaten = meldungen.sort_values("annahme_utc").drop_duplicates("accession")
    kandidaten = kandidaten[~kandidaten["accession"].isin(set(gesehen["accession"]))]
    neu, status, fehler_in_folge, abgebrochen = [], [], 0, False
    for z in kandidaten.itertuples(index=False):
        if budget.abgelaufen():
            abgebrochen = True
            break
        url = xml_adresse(z.cik, z.accession, z.primary_document)
        if url is None:
            status.append((z.accession, "keine_xml"))
            continue
        try:
            antwort = abruf.hole(url, erlaube_404=True)
        except QuelleNichtErreichbar:
            fehler_in_folge += 1
            if fehler_in_folge >= max_fehler:
                raise
            continue                      # beim nächsten Lauf erneut versuchen
        fehler_in_folge = 0
        if antwort is None:
            status.append((z.accession, "fehlt"))
            continue
        try:
            df = lies_form4_xml(antwort.content, z.accession, z.filing_date, teil)
        except (ET_XML.ParseError, ValueError):
            status.append((z.accession, "unlesbar"))
            continue
        status.append((z.accession, "gelesen" if len(df) else "ohne_geschaeft"))
        if len(df):
            neu.append(df)
    if neu or not daten_pfad.exists():
        teile = [t for t in [alt] + neu if len(t)]
        gesamt = pd.concat(teile, ignore_index=True) if teile else pd.DataFrame(columns=SPALTEN)
        if len(gesamt):
            ablage.schreibe_bereinigt(TABELLE, teil, gesamt)
    if status:
        ablage.schreibe_bereinigt(XML_STAND, teil, pd.concat(
            [gesehen, pd.DataFrame(status, columns=["accession", "status"])], ignore_index=True))
    zaehlung = pd.Series([s for _, s in status]).value_counts().to_dict() if status else {}
    return {"quartal": teil, "neu": len(neu), "offen": int(len(kandidaten) - len(status)) if abgebrochen else 0,
            "abgebrochen": abgebrochen, **zaehlung}


# --------------------------------------------------------------------------- Aufbereitung
def bereinige(roh: pd.DataFrame, meldungen: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Entfernt Nachtrags-Dubletten und unplausible Daten, ergänzt Annahmezeit und ``verfuegbar_ab``."""
    df = roh.sort_values(["filing_date", "accession", "zeile"], kind="stable").reset_index(drop=True)
    n0 = len(df)
    schluessel = ["issuer_cik", "owner_cik", "trans_date", "code", "erwerb", "stueck", "preis"]
    nachtrag = df["form"].astype("string").fillna("").str.endswith("/A")
    original = df.loc[~nachtrag, schluessel].drop_duplicates()
    original["_orig"] = True
    df = df.merge(original, on=schluessel, how="left")
    df = df[~(df["form"].astype("string").fillna("").str.endswith("/A")
              & df["_orig"].fillna(False).astype(bool))].drop(columns="_orig")
    n_dubletten = n0 - len(df)
    plausibel = (df["trans_date"].notna() & (df["trans_date"] <= df["filing_date"])
                 & (df["trans_date"] >= df["filing_date"] - pd.Timedelta(days=3 * 366)))
    n_unplausibel = int((~plausibel).sum())
    df = df[plausibel].copy()

    zeit = pd.DataFrame(columns=["accession", "annahme_utc", "verfuegbar_ab", "annahme_geschaetzt"])
    if not meldungen.empty:
        zeit = (meldungen[["accession", "annahme_utc", "verfuegbar_ab", "annahme_geschaetzt"]]
                .sort_values("annahme_utc").drop_duplicates("accession"))
    df = df.merge(zeit, on="accession", how="left")
    fehlt = df["annahme_utc"].isna()
    ersatz = (df.loc[fehlt, "filing_date"] + pd.Timedelta(hours=17, minutes=30)).dt.tz_localize(
        ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    df["annahme_utc"] = pd.to_datetime(df["annahme_utc"], utc=True).astype("datetime64[us, UTC]")
    df.loc[fehlt, "annahme_utc"] = ersatz.astype("datetime64[us, UTC]")
    df["annahme_geschaetzt"] = df["annahme_geschaetzt"].astype("boolean").fillna(True).astype(bool) | fehlt
    df["verfuegbar_ab"] = pd.to_datetime(df["verfuegbar_ab"], utc=True).astype("datetime64[us, UTC]")
    df.loc[fehlt, "verfuegbar_ab"] = handelbar_ab_serie(df.loc[fehlt, "annahme_utc"]).astype("datetime64[us, UTC]")
    df["ereignis_zeit"] = df["trans_date"].dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward") \
        .dt.tz_convert("UTC").astype("datetime64[us, UTC]")
    info = {"zeilen_roh": n0, "nachtrags_dubletten": n_dubletten, "unplausible_daten": n_unplausibel,
            "ohne_annahmezeit": int(fehlt.sum()), "zeilen": len(df)}
    return df.reset_index(drop=True), info


def _rang(e: pd.DataFrame) -> np.ndarray:
    vorstand = e["ist_officer"] & e["titel"].fillna("").str.contains(VORSTAND)
    rang = np.zeros(len(e))
    rang[(e["ist_zehn_prozent"] & ~e["ist_officer"]).to_numpy()] = 1
    rang[(e["ist_direktor"] & ~e["ist_officer"] & ~e["ist_zehn_prozent"]).to_numpy()] = 2
    rang[e["ist_officer"].to_numpy()] = 3
    rang[vorstand.to_numpy()] = 4
    return rang


def ereignisse(df: pd.DataFrame, code: str, erwerb: str) -> pd.DataFrame:
    """Fasst die Geschäfte einer Meldung (Firma, Person) zu einem Ereignis zusammen."""
    t = df[(df["code"] == code) & (df["erwerb"] == erwerb) & (df["stueck"] > 0) & (df["preis"] > 0)]
    if t.empty:
        return pd.DataFrame()
    t = t.sort_values(["accession", "zeile"], kind="stable")
    g = t.groupby(["accession", "issuer_cik", "owner_cik"], sort=False)
    e = g.agg(stueck=("stueck", "sum"), wert_usd=("wert_usd", "sum"), erster_tag=("trans_date", "min"),
              letzter_tag=("trans_date", "max"), bestand_danach=("bestand_danach", "last"),
              filing_date=("filing_date", "first"), annahme_utc=("annahme_utc", "first"),
              verfuegbar_ab=("verfuegbar_ab", "first"), annahme_geschaetzt=("annahme_geschaetzt", "first"),
              plan_10b5_1=("plan_10b5_1", "first"), ist_direktor=("ist_direktor", "first"),
              ist_officer=("ist_officer", "first"), ist_zehn_prozent=("ist_zehn_prozent", "first"),
              titel=("titel", "first"), mit_ausuebung=("mit_ausuebung", "first")).reset_index()
    # Extern = 10-%-Eigner ohne Amt (wie f_external im Insider-Monitor)
    e["extern"] = e["ist_zehn_prozent"] & ~e["ist_officer"] & ~e["ist_direktor"]
    tag_utc = e["letzter_tag"].dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward") \
        .dt.tz_convert("UTC").astype("datetime64[us, UTC]")
    # Ein Geschäft kann nicht nach der Annahme seiner Meldung liegen (Schutz gegen Datumsfehler der Quelle)
    e["ereignis_zeit"] = tag_utc.where(tag_utc <= e["annahme_utc"], e["annahme_utc"])
    return e.sort_values(["issuer_cik", "verfuegbar_ab", "accession"], kind="stable").reset_index(drop=True)


def _fenster(kauf: pd.DataFrame, verkauf: pd.DataFrame) -> pd.DataFrame:
    """Cluster (30 T), Tagescluster und Netto-Kaufquote (182 T) je Kaufereignis, stichtagsecht."""
    n = len(kauf)
    cluster = np.zeros(n)
    tages = np.zeros(n)
    quote = np.zeros(n)
    k_tag = kauf["letzter_tag"].to_numpy().astype("datetime64[D]").astype("int64")
    k_vab = kauf["verfuegbar_ab"].values.astype("datetime64[us]").astype("int64")
    k_own = kauf["owner_cik"].to_numpy()
    k_eigen = ~kauf["extern"].to_numpy(dtype=bool)
    k_wert = kauf["wert_usd"].to_numpy(dtype="float64")
    grenzen = np.flatnonzero(np.r_[True, kauf["issuer_cik"].to_numpy()[1:] != kauf["issuer_cik"].to_numpy()[:-1], True])
    v_gruppen = {}
    if len(verkauf):
        for cik, t in verkauf.groupby("issuer_cik", sort=False):
            gewicht = np.where(t["mit_ausuebung"].to_numpy(dtype=bool), AUSUEBUNG_GEWICHT, 1.0)
            v_gruppen[cik] = (t["letzter_tag"].to_numpy().astype("datetime64[D]").astype("int64"),
                              t["verfuegbar_ab"].values.astype("datetime64[us]").astype("int64"),
                              t["wert_usd"].to_numpy(dtype="float64") * gewicht)
    firmen = kauf["issuer_cik"].to_numpy()
    for a, b in zip(grenzen[:-1], grenzen[1:]):
        tag, vab, own, wert, eigen = k_tag[a:b], k_vab[a:b], k_own[a:b], k_wert[a:b], k_eigen[a:b]
        v_tag, v_vab, v_wert = v_gruppen.get(firmen[a], (np.empty(0, "int64"), np.empty(0, "int64"), np.empty(0)))
        for i in range(b - a):
            bekannt = vab <= vab[i]
            in30 = bekannt & eigen & (tag >= tag[i] - 30) & (tag <= tag[i])
            cluster[a + i] = len(np.unique(own[in30]))
            in2 = bekannt & eigen & (tag >= tag[i] - 2) & (tag <= tag[i]) & (own != own[i])
            tages[a + i] = len(np.unique(own[in2]))
            k_sum = wert[bekannt & (tag > tag[i] - 182) & (tag <= tag[i])].sum()
            v_sum = v_wert[(v_vab <= vab[i]) & (v_tag > tag[i] - 182) & (v_tag <= tag[i])].sum() if len(v_tag) else 0.0
            quote[a + i] = (k_sum - v_sum) / (k_sum + v_sum) if (k_sum + v_sum) > 0 else np.nan
    return pd.DataFrame({"cluster30": cluster, "tagescluster": tages, "netto_kaufquote": quote}, index=kauf.index)


def _routine(kauf: pd.DataFrame) -> np.ndarray:
    """1 = Routine, 0 = opportunistisch, NaN = nicht einstufbar; Definition des Insider-Monitors.

    Routine: dieselbe Person kaufte dieselbe Aktie in mindestens zwei Vorjahren im selben Monat.
    Opportunistisch: Käufe in mindestens zwei Vorjahren, aber nie im selben Monat.
    Externe (10-%-Eigner ohne Amt) werden nicht eingestuft.
    """
    jahr = kauf["letzter_tag"].dt.year.to_numpy()
    monat = kauf["letzter_tag"].dt.month.to_numpy()
    aus = np.full(len(kauf), np.nan)
    extern = kauf["extern"].to_numpy(dtype=bool)
    for _, idx in kauf.groupby(["issuer_cik", "owner_cik"], sort=False).indices.items():
        jahre = set(jahr[idx])
        if len(jahre) < 3:
            continue
        paare = set(zip(jahr[idx], monat[idx]))
        for i in idx:
            if extern[i]:
                continue
            vorjahre = sum(1 for j in jahre if j < jahr[i])
            routine = sum(1 for j in jahre if j < jahr[i] and (j, monat[i]) in paare)
            if routine >= 2:
                aus[i] = 1.0
            elif vorjahre >= 2 and routine == 0:
                aus[i] = 0.0
    return aus


def baue_parameter(df: pd.DataFrame, meldungen: pd.DataFrame) -> pd.DataFrame:
    kauf = ereignisse(df, "P", "A")
    verkauf = ereignisse(df, "S", "D")
    if kauf.empty:
        return leer()
    teile = []

    def zeilen(e: pd.DataFrame, pid: str, wert, maske=None) -> None:
        t = pd.DataFrame({"cik": e["issuer_cik"].to_numpy(), "parameter_id": pid,
                          "ereignis_zeit": e["ereignis_zeit"].values, "verfuegbar_ab": e["verfuegbar_ab"].values,
                          "wert": np.asarray(wert, dtype="float64"), "stand": e["accession"].to_numpy()})
        if maske is not None:
            t = t[np.asarray(maske)]
        teile.append(t)

    fenster = _fenster(kauf, verkauf)
    zeilen(kauf, "IH1-01", fenster["cluster30"])
    zeilen(kauf, "IH1-18", fenster["tagescluster"])
    zeilen(kauf, "IH1-06", fenster["netto_kaufquote"])
    zeilen(kauf, "IH1-02", _rang(kauf))
    zeilen(kauf, "IH1-03", kauf["wert_usd"])
    zeilen(kauf, "IH1-04", _routine(kauf))
    zeilen(kauf, "IH1-07", kauf["plan_10b5_1"])
    zeilen(kauf, "IH1-09", (kauf["filing_date"] - kauf["letzter_tag"]).dt.days)
    vorher = kauf["bestand_danach"] - kauf["stueck"]
    zeilen(kauf, "IH1-10", (kauf["stueck"] / vorher).where(vorher > 0))
    lokal = kauf["annahme_utc"].dt.tz_convert(ET)
    bruch = (lokal.dt.hour * 3600 + lokal.dt.minute * 60 + lokal.dt.second) / 86400.0
    zeilen(kauf, "WS3-01", (lokal.dt.weekday + bruch).round(4), maske=~kauf["annahme_geschaetzt"].to_numpy())

    # Tage seit der letzten Zahlenmeldung (8-K Item 2.02), nur bereits veröffentlichte Meldungen
    if not meldungen.empty:
        zahlen = meldungen[(meldungen["form"] == "8-K") & meldungen["items"].fillna("").str.contains(r"(?:^|,)\s*2\.02")]
        zahlen = zahlen[["cik", "annahme_utc"]].rename(columns={"cik": "issuer_cik", "annahme_utc": "zahlen_zeit"})
        zahlen["zahlen_zeit"] = zahlen["zahlen_zeit"].astype("datetime64[us, UTC]")
        if not zahlen.empty:
            links = kauf[["issuer_cik", "ereignis_zeit"]].reset_index().sort_values("ereignis_zeit", kind="stable")
            paar = pd.merge_asof(links, zahlen.sort_values("zahlen_zeit"), left_on="ereignis_zeit",
                                 right_on="zahlen_zeit", by="issuer_cik", direction="backward")
            tag = lambda z: z.dt.tz_convert(ET).dt.tz_localize(None).dt.normalize()
            tage = (tag(paar["ereignis_zeit"]) - tag(paar["zahlen_zeit"])).dt.days.astype("float64")
            tage.index = paar["index"]
            zeilen(kauf, "IH1-05", tage.reindex(kauf.index))

    # Verkauf des Käufers binnen 30 Tagen nach eigenem Kauf (Zeile am Verkauf)
    if not verkauf.empty:
        k = kauf[["issuer_cik", "owner_cik", "letzter_tag"]].rename(columns={"letzter_tag": "kauftag"}) \
            .sort_values("kauftag", kind="stable")
        v = verkauf.reset_index().sort_values("erster_tag", kind="stable")
        paar = pd.merge_asof(v, k, left_on="erster_tag", right_on="kauftag", by=["issuer_cik", "owner_cik"],
                             direction="backward", allow_exact_matches=False)
        treffer = paar[(paar["erster_tag"] - paar["kauftag"]).dt.days <= 30]
        if not treffer.empty:
            zeilen(treffer, "IH1-17", np.ones(len(treffer)))

    # Marktweiter Kaufanteil je Monat der Verfügbarkeit, Geschäfte ab 25.000 US-Dollar
    alle = pd.concat([kauf.assign(_kauf=1.0), verkauf.assign(_kauf=0.0)] if len(verkauf) else [kauf.assign(_kauf=1.0)])
    gross = alle[alle["wert_usd"] >= 25_000]
    if not gross.empty:
        monat = gross["verfuegbar_ab"].dt.tz_convert(ET).dt.tz_localize(None).dt.to_period("M")
        letzter = (df["filing_date"].max() + pd.Timedelta(days=4)).to_period("M") - 1
        anteil = gross.groupby(monat)["_kauf"].mean()
        anteil = anteil[anteil.index <= letzter]
        if len(anteil):
            vab = [monatsende_handelbar(p.year, p.month) for p in anteil.index]
            ende = [pd.Timestamp(p.end_time.floor("s"), tz=ET).tz_convert("UTC") for p in anteil.index]
            teile.append(pd.DataFrame({"cik": MARKT_CIK, "parameter_id": "IH1-16", "ereignis_zeit": ende,
                                       "verfuegbar_ab": vab, "wert": anteil.to_numpy(dtype="float64"),
                                       "stand": [str(p) for p in anteil.index]}))
    return als_parameter(pd.concat([t for t in teile if len(t)], ignore_index=True))


# --------------------------------------------------------------------------- Lauf
def lauf(ablage: Ablage, arbeits: Path, ab_jahr: int = 2006, heute: date | None = None, abruf: Abruf | None = None,
         budget: Zeitbudget | None = None, auffrischen: int = 2,
         lokal: Path | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    """Lädt fehlende Quartale (und die jüngsten erneut), bereinigt und rechnet alle Parameter neu.

    ``lokal``: Ordner mit bereits vorliegenden Archiven ``<jahr>q<q>_form345.zip`` (Offline-Lauf, kein Abruf).
    """
    arbeits = Path(arbeits)
    heute = heute or date.today()
    budget = budget or Zeitbudget()
    hinweise: list[str] = []
    gewollt = quartale(ab_jahr, heute)
    vorhanden = {p.name.split("__")[2].removesuffix(".parquet") for p in ablage.bereinigt.glob(f"bereinigt__{TABELLE}__*.parquet")}
    neueste = {f"{j}q{q}" for j, q in gewollt[-auffrischen:]}
    offen = [(j, q) for j, q in gewollt if f"{j}q{q}" not in vorhanden or f"{j}q{q}" in neueste]
    unvollstaendig = False
    seitenlinks: dict[str, str] | None = None
    for jahr, q in offen:
        if budget.abgelaufen():
            unvollstaendig = True
            break
        teil = f"{jahr}q{q}"
        if lokal is not None:
            pfad = Path(lokal) / f"{teil}_form345.zip"
            if not pfad.exists():
                continue
            ablage.schreibe_bereinigt(TABELLE, teil, lies_quartal(pfad, teil))
            continue
        abruf = abruf or Abruf()
        if seitenlinks is None:
            try:
                seitenlinks = links_aus_seite(abruf.hole(DATEN_SEITE).text)
            except Exception as fehler:  # Seite nicht lesbar: feste Pfade versuchen
                seitenlinks = {}
                hinweise.append(f"SEC-Datenseite nicht lesbar ({type(fehler).__name__}); feste Pfade versucht")
        kandidaten = ([seitenlinks[teil]] if teil in seitenlinks else []) + \
            [m.format(jahr=jahr, q=q) for m in DATEN_URLS]
        pfad = None
        for url in dict.fromkeys(kandidaten):
            pfad = abruf.hole_datei(url, arbeits / f"{teil}_form345.zip", erlaube_404=True)
            if pfad is not None:
                break
        if pfad is None:
            hinweise.append(f"Quartal {teil} bei der SEC noch nicht veröffentlicht")
            continue
        ablage.schreibe_bereinigt(TABELLE, teil, lies_quartal(pfad, teil))
        pfad.unlink(missing_ok=True)
    if unvollstaendig:
        merke_fortsetzung(ablage.wurzel, "edgar_insider")
        hinweise.append("Zeitbudget erreicht; Lauf wird fortgesetzt")
        return leer(), {"unvollstaendig": True}, hinweise

    # Quartale nach dem letzten amtlichen Datensatz aus den einzelnen Form-4-Dateien ergänzen
    xml_info: list[dict] = []
    if lokal is None or abruf is not None:
        amtlich = amtliche_quartale(ablage)
        if amtlich:
            j0, q0 = map(int, max(amtlich, key=lambda t: tuple(map(int, t.split("q")))).split("q"))
            start = date(j0 + (q0 == 4), q0 * 3 % 12 + 1, 1)
            verzeichnis = ablage.lies_bereinigt(
                "edgar_meldungen", spalten=["cik", "accession", "form", "filing_date", "primary_document", "annahme_utc"],
                filter=[("form", "in", ["4", "4/A"]), ("filing_date", ">=", pd.Timestamp(start).to_pydatetime())])
            if verzeichnis.empty:
                hinweise.append(f"Keine Form-4-Meldungen ab {start} im Meldungsverzeichnis; laufende Ergänzung entfällt")
            else:
                abruf = abruf or Abruf()
                jq = _quartal_von(start)
                while jq <= _quartal_von(heute):
                    teil = f"{jq[0]}q{jq[1]}"
                    im_quartal = verzeichnis[(verzeichnis["filing_date"].dt.year == jq[0])
                                             & ((verzeichnis["filing_date"].dt.month - 1) // 3 + 1 == jq[1])]
                    ergebnis = ergaenze_aus_xml(ablage, abruf, budget, teil, im_quartal)
                    xml_info.append(ergebnis)
                    if ergebnis.get("abgebrochen"):
                        merke_fortsetzung(ablage.wurzel, "edgar_insider")
                        hinweise.append(f"Zeitbudget erreicht bei {teil} ({ergebnis['offen']} Meldungen offen); "
                                        "Lauf wird fortgesetzt")
                        return leer(), {"unvollstaendig": True, "xml": xml_info}, hinweise
                    jq = (jq[0] + (jq[1] == 4), jq[1] % 4 + 1)
    roh = ablage.lies_bereinigt(TABELLE, spalten=RECHEN_SPALTEN, filter=[("code", "in", ["P", "S"])])
    if roh.empty:
        raise RuntimeError("Keine Insiderdaten vorhanden")
    for s in ("code", "erwerb", "form", "quartal"):
        roh[s] = roh[s].astype("category")
    fehlend = sorted({f"{j}q{q}" for j, q in gewollt[:-auffrischen]} - set(roh["quartal"].unique()))
    if fehlend:
        hinweise.append(f"Fehlende Quartale: {', '.join(fehlend)}")
    meldungen = ablage.lies_bereinigt("edgar_meldungen", spalten=MELDE_SPALTEN, filter=[("form", "in", MELDE_FORMEN)])
    if meldungen.empty:
        hinweise.append("Meldungsverzeichnis fehlt; Annahmezeiten werden aus dem Einreichungsdatum geschätzt")
    df, info = bereinige(roh, meldungen)
    parameter = baue_parameter(df, meldungen)
    ablage.schreibe_parameter("edgar_insider", parameter)
    info["quartale"] = int(roh["quartal"].nunique())
    info["fehlende_quartale"] = fehlend
    info["xml"] = xml_info
    return parameter, info, hinweise
