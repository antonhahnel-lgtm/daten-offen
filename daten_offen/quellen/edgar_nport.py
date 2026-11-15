"""Bestände und Mittelflüsse offener Fonds aus den Form-N-PORT-Datensätzen der SEC (ab 10/2019) → KD3-01, IH5-06.

Die SEC veröffentlicht je Kalenderquartal einen Datensatz mit allen in diesem Quartal eingereichten öffentlichen
Meldungen (NPORT-P, Bestand am Ende des dritten Monats eines Fondsquartals, Frist 60 Tage). Gezählt wird je Fonds
(Serie) und Berichtsquartal die jüngste fristgerechte Erstmeldung. Gespeichert werden Stückzahl und Portfoliogewicht
der Stammaktien, nicht der Kurswert (keine Kurse im öffentlichen Repo).

Mittelfluss eines Fonds = Verkäufe + Wiederanlagen − Rücknahmen der drei Monate (Item B.6) / Nettovermögen am
Berichtstag. Der Fondsflussdruck einer Aktie ist der mit dem Bestand in Stück gewichtete Mittelfluss ihrer Halter
(nach Coval & Stafford 2007 und Lou 2012, ohne Kurse).

  nport_dateien     gelesene Datensätze
  nport_fonds       je Meldung: Serie, Berichtstag, Einreichung, Nettovermögen, Mittelfluss
  nport_bestaende   je Datensatz: Meldung, CUSIP, Stück, Gewicht (Stammaktien, long)
  nport_firmen      je Firma und Berichtsquartal: fonds, stueck, fluss_gewichtet, stueck_abfluss, stueck_zufluss
"""
from __future__ import annotations

import csv
import os
import re
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab, ist_handelstag
from ..kern.zustand import Zeitbudget, merke_fortsetzung
from .edgar_13f import MINDEST_KONFIDENZ, _datum, _kopf, _mitglied, quartal_name

SEITE = "https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets"
LINK_MUSTER = re.compile(r'href="([^"]*?/(\d{4}q[1-4])_nport\.zip)"', re.I)
RELEASE_URL = "https://github.com/{repo}/releases/download/bereinigt-edgar/{datei}"
FRIST_TAGE = 60
GRENZE_FLUSS = 0.05        # Abfluss oder Zufluss über 5 % des Vermögens (Coval & Stafford: extreme Flüsse)
MIN_FONDS = 3              # so viele haltende Fonds braucht der Fondsflussdruck
TABELLE_DATEIEN, TABELLE_FONDS = "nport_dateien", "nport_fonds"
TABELLE_BESTAND, TABELLE_FIRMEN = "nport_bestaende", "nport_firmen"
SPALTEN_MELDUNG = ["ACCESSION_NUMBER", "FILING_DATE", "REPORT_DATE", "SUB_TYPE"]
SPALTEN_FONDS = ["ACCESSION_NUMBER", "SERIES_ID", "NET_ASSETS"] + [f"{a}_FLOW_MON{m}" for a in ("SALES", "REINVESTMENT", "REDEMPTION")
                                                                   for m in (1, 2, 3)]
SPALTEN_POSITION = ["ACCESSION_NUMBER", "HOLDING_ID", "ISSUER_CUSIP", "BALANCE", "UNIT", "ASSET_CAT", "PAYOFF_PROFILE", "PERCENTAGE"]
SPALTEN_KENNUNG = ["HOLDING_ID", "IDENTIFIER_ISIN"]
CUSIP = r"[0-9A-Z]{9}"
FONDS_SPALTEN = ["accession", "datei", "serie", "berichtstag", "eingereicht", "art", "vermoegen", "nettofluss", "fluss"]

_OFFEN = "amtlich offen: Form N-PORT (Rule 30b1-9), öffentlich der dritte Monat jedes Fondsquartals, Frist 60 Tage"
_SCHWAECHEN = ("Nur registrierte Fonds ohne Geldmarktfonds; Fonds mit abweichendem Geschäftsjahr berichten über andere "
               "Monate (gezählt wird je Fonds das Berichtsquartal des Berichtstags); Nachträge und verspätete Meldungen "
               "bleiben außen vor; Zuordnung über die CUSIP-Tabelle der Lieferausfälle. Das Quartal entsteht erst, wenn "
               "der Datensatz der SEC alle Meldungen bis zur Frist enthält (bis zu fünf Wochen nach der Frist)")


def _p(id_, name, definition, einheit, schwaechen=""):
    return Parameter(id=id_, name=name, definition=definition, einheit=einheit, frequenz="je Berichtsquartal",
                     offenlegung=_OFFEN, quelle=SEITE, lizenz="gemeinfrei (US-Behörde)", historie_ab="2019 (viertes Quartal)",
                     verzoegerung="Eröffnung des ersten Handelstags nach Ablauf der Frist für den letzten Monat des Quartals",
                     schwaechen=(schwaechen + " " + _SCHWAECHEN).strip())


registriere(
    _p("KD3-01", "Fondsflussdruck der Halter",
       "Mittelfluss der Fonds, die die Aktie halten, gewichtet mit ihrem Bestand in Stück: Σ Stück × Fluss / Σ Stück; "
       "Fluss = (Verkäufe + Wiederanlagen − Rücknahmen der drei Monate) / Nettovermögen am Berichtstag, begrenzt auf "
       f"±1; nur Firmen mit mindestens {MIN_FONDS} haltenden Fonds. Die Bestände der Fonds mit Abflüssen oder Zuflüssen "
       f"über {GRENZE_FLUSS:.0%} stehen in nport_firmen", "Anteil des Fondsvermögens",
       "Ohne Kurse: Gewichtung mit Stückzahlen statt mit Kurswert und ohne Bezug auf das Handelsvolumen; Fluss gegen "
       "das Vermögen am Ende statt am Anfang des Quartals."),
    _p("IH5-06", "Zahl der haltenden Fonds (N-PORT)",
       "Zahl der Fonds (Serien) mit einem Bestand an Stammaktien der Firma laut ihrer Meldung für das Berichtsquartal",
       "Anzahl"),
)


# --------------------------------------------------------------------------- Zeitbezug
def links_aus_seite(html: str) -> dict[str, str]:
    aus: dict[str, str] = {}
    for href, schluessel in LINK_MUSTER.findall(html):
        aus.setdefault(schluessel.lower(), href if href.startswith("http") else "https://www.sec.gov" + href)
    return aus


def _q(tag) -> tuple[int, int]:
    t = pd.Timestamp(tag)
    return t.year, (t.month - 1) // 3 + 1


def quartalsende(tag) -> pd.Timestamp:
    j, q = _q(tag)
    return (pd.Timestamp(j, q * 3, 1) + pd.offsets.MonthEnd(0)).normalize()


def frist(berichtstag) -> date:
    """Letzter fristgerechter Einreichungstag: 60 Tage nach dem Berichtstag, sonst der nächste Handelstag."""
    tag = pd.Timestamp(berichtstag).date() + timedelta(days=FRIST_TAGE)
    while not ist_handelstag(tag):
        tag += timedelta(days=1)
    return tag


def verfuegbar_ab(periode) -> datetime:
    return handelbar_ab(datetime.combine(frist(quartalsende(periode)), time(18, 0), tzinfo=ET))


def noetige_dateien(periode) -> list[str]:
    """Datensätze (Einreichungsquartale), die alle fristgerechten Meldungen eines Berichtsquartals enthalten."""
    ende = quartalsende(periode)
    aus, jq, schluss = [], _q(ende), _q(frist(ende))
    while jq <= schluss:
        aus.append(f"{jq[0]}q{jq[1]}")
        jq = (jq[0] + (jq[1] == 4), jq[1] % 4 + 1)
    return aus


# --------------------------------------------------------------------------- Einlesen
def lies_archiv(zip_pfad: Path, datei: str, blockgroesse: int = 1_000_000) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Meldungen mit Mittelfluss (alle Arten) und Bestände der Erstmeldungen (Stammaktien in Stück, long). Fehlt die
    CUSIP, gilt die in der ISIN enthaltene (US- und kanadische ISIN: Länderkürzel, CUSIP, Prüfziffer)."""
    with zipfile.ZipFile(zip_pfad) as archiv:
        m_sub, m_fonds, m_pos, m_kenn = (_mitglied(archiv, n) for n in ("SUBMISSION.tsv", "FUND_REPORTED_INFO.tsv",
                                                                        "FUND_REPORTED_HOLDING.tsv", "IDENTIFIERS.tsv"))
        lies = lambda m, sp: pd.read_csv(archiv.open(m), sep="\t", dtype=str, usecols=list(sp), quoting=csv.QUOTE_NONE,
                                         keep_default_na=False, encoding="utf-8", encoding_errors="replace").rename(columns=sp)
        sub = lies(m_sub, _kopf(archiv, m_sub, SPALTEN_MELDUNG))
        fonds = lies(m_fonds, _kopf(archiv, m_fonds, SPALTEN_FONDS))
        f = sub.merge(fonds, on="ACCESSION_NUMBER", how="inner")
        zahl = lambda s: pd.to_numeric(f[s], errors="coerce")
        netto = sum(zahl(f"SALES_FLOW_MON{m}").fillna(0) + zahl(f"REINVESTMENT_FLOW_MON{m}").fillna(0)
                    - zahl(f"REDEMPTION_FLOW_MON{m}").fillna(0) for m in (1, 2, 3))
        vermoegen = zahl("NET_ASSETS")
        mit_fluss = pd.concat([zahl(f"{a}_FLOW_MON{m}") for a in ("SALES", "REDEMPTION") for m in (1, 2, 3)], axis=1).notna().any(axis=1)
        tab = pd.DataFrame({
            "accession": f["ACCESSION_NUMBER"].str.strip(), "datei": datei,
            "serie": f["SERIES_ID"].str.strip().where(f["SERIES_ID"].str.strip() != "", "ohne:" + f["ACCESSION_NUMBER"].str.strip()),
            "berichtstag": _datum(f["REPORT_DATE"]), "eingereicht": _datum(f["FILING_DATE"]),
            "art": f["SUB_TYPE"].str.strip().str.upper(), "vermoegen": vermoegen,
            "nettofluss": netto.where(mit_fluss)})
        tab["fluss"] = (tab["nettofluss"] / tab["vermoegen"].where(tab["vermoegen"] > 0)).clip(-1, 1)
        tab = tab[tab["berichtstag"].notna() & tab["eingereicht"].notna()].drop_duplicates("accession").reset_index(drop=True)
        erst = set(tab.loc[tab["art"] == "NPORT-P", "accession"])
        spalten = _kopf(archiv, m_pos, SPALTEN_POSITION)
        teile, ohne, zeilen = [], [], 0
        with archiv.open(m_pos) as d:
            for block in pd.read_csv(d, sep="\t", dtype=str, usecols=list(spalten), quoting=csv.QUOTE_NONE, on_bad_lines="skip",
                                     chunksize=blockgroesse, keep_default_na=False, encoding="utf-8", encoding_errors="replace"):
                block = block.rename(columns=spalten)
                zeilen += len(block)
                block = block[(block["ASSET_CAT"].str.strip() == "EC") & (block["UNIT"].str.strip() == "NS")
                              & (block["PAYOFF_PROFILE"].str.strip() == "Long") & block["ACCESSION_NUMBER"].isin(erst)]
                block = pd.DataFrame({"accession": block["ACCESSION_NUMBER"].str.strip(), "kennung": block["HOLDING_ID"].str.strip(),
                                      "cusip": block["ISSUER_CUSIP"].str.strip().str.upper(),
                                      "stueck": pd.to_numeric(block["BALANCE"], errors="coerce"),
                                      "gewicht": pd.to_numeric(block["PERCENTAGE"], errors="coerce")})
                block = block[block["stueck"] > 0]
                gueltig = block["cusip"].str.fullmatch(CUSIP) & (block["cusip"] != "000000000")
                teile.append(block[gueltig].groupby(["accession", "cusip"], as_index=False)[["stueck", "gewicht"]].sum())
                ohne.append(block[~gueltig].drop(columns="cusip"))
        ohne = pd.concat(ohne, ignore_index=True) if ohne else pd.DataFrame(columns=["accession", "kennung", "stueck", "gewicht"])
        aus_isin = 0
        if len(ohne):
            gesucht, isin = set(ohne["kennung"]), []
            spalten = _kopf(archiv, m_kenn, SPALTEN_KENNUNG)
            with archiv.open(m_kenn) as d:
                for block in pd.read_csv(d, sep="\t", dtype=str, usecols=list(spalten), quoting=csv.QUOTE_NONE, on_bad_lines="skip",
                                         chunksize=blockgroesse, keep_default_na=False, encoding="utf-8", encoding_errors="replace"):
                    block = block.rename(columns=spalten)
                    block = block[block["HOLDING_ID"].str.strip().isin(gesucht)]
                    i = block["IDENTIFIER_ISIN"].str.strip().str.upper()
                    treffer = i.str.fullmatch(r"(US|CA)[0-9A-Z]{9}[0-9]")
                    isin.append(pd.DataFrame({"kennung": block.loc[treffer, "HOLDING_ID"].str.strip(), "cusip": i[treffer].str[2:11]}))
            isin = pd.concat(isin, ignore_index=True).drop_duplicates("kennung") if isin else pd.DataFrame(columns=["kennung", "cusip"])
            nach = ohne.merge(isin, on="kennung", how="inner")
            aus_isin = int(len(nach))
            teile.append(nach.groupby(["accession", "cusip"], as_index=False)[["stueck", "gewicht"]].sum())
    bestand = (pd.concat(teile, ignore_index=True).groupby(["accession", "cusip"], as_index=False)[["stueck", "gewicht"]].sum()
               if teile else pd.DataFrame(columns=["accession", "cusip", "stueck", "gewicht"]))
    bestand["stueck"] = bestand["stueck"].round().astype("int64")
    bestand["gewicht"] = bestand["gewicht"].astype("float32")
    info = {"datei": datei, "meldungen": int(len(sub)), "fonds": int(len(tab)), "positionszeilen": int(zeilen),
            "aktienpositionen": int(len(bestand)), "ohne_cusip": int(len(ohne)), "cusip_aus_isin": aus_isin}
    return tab[FONDS_SPALTEN], bestand, info


# --------------------------------------------------------------------------- Kennzahlen je Berichtsquartal
def waehle_fonds(fonds: pd.DataFrame, periode) -> pd.DataFrame:
    """Je Serie die jüngste fristgerechte Erstmeldung mit Berichtstag im Quartal."""
    f = fonds[(fonds["art"] == "NPORT-P") & (fonds["berichtstag"].map(quartalsende) == quartalsende(periode))]
    if f.empty:
        return f
    letzter = f["berichtstag"].map({t: pd.Timestamp(frist(t)) for t in f["berichtstag"].unique()})
    f = f[(f["eingereicht"] >= f["berichtstag"]) & (f["eingereicht"] <= letzter)]
    return f.sort_values(["berichtstag", "eingereicht", "accession"]).drop_duplicates("serie", keep="last")


def verdichte(fonds: pd.DataFrame, bestand: pd.DataFrame, zu_firma: pd.Series) -> pd.DataFrame:
    """Je Firma: haltende Fonds, Stück, mit dem Bestand gewichteter Fluss, Bestände bei starken Ab- und Zuflüssen."""
    b = bestand.merge(fonds[["accession", "serie", "fluss"]], on="accession", how="inner")
    cik = b["cusip"].map(zu_firma)
    b = b[cik.notna()].assign(cik=cik[cik.notna()].astype("int64"))
    if b.empty:
        return pd.DataFrame(columns=["cik", "fonds", "stueck", "fluss_gewichtet", "stueck_abfluss", "stueck_zufluss"])
    b = b.groupby(["cik", "serie"], as_index=False).agg(stueck=("stueck", "sum"), fluss=("fluss", "first"))
    mit = b[b["fluss"].notna()]
    je = b.groupby("cik").agg(fonds=("serie", "nunique"), stueck=("stueck", "sum"))
    gewichtet = (mit["stueck"] * mit["fluss"]).groupby(mit["cik"]).sum() / mit.groupby("cik")["stueck"].sum()
    je["fluss_gewichtet"] = gewichtet.reindex(je.index)
    je["stueck_abfluss"] = mit[mit["fluss"] <= -GRENZE_FLUSS].groupby("cik")["stueck"].sum().reindex(je.index, fill_value=0)
    je["stueck_zufluss"] = mit[mit["fluss"] >= GRENZE_FLUSS].groupby("cik")["stueck"].sum().reindex(je.index, fill_value=0)
    return je.reset_index().astype({"cik": "int64", "fonds": "int64", "stueck": "int64", "stueck_abfluss": "int64",
                                    "stueck_zufluss": "int64"})


def baue_parameter(firmen: pd.DataFrame) -> pd.DataFrame:
    if firmen.empty:
        return leer()
    q = firmen.assign(periode=pd.to_datetime(firmen["periode"]))
    zeit = {p: (pd.Timestamp(datetime.combine(p.date(), time(18, 0), tzinfo=ET)).tz_convert("UTC"), pd.Timestamp(verfuegbar_ab(p)),
                quartal_name(p)) for p in q["periode"].drop_duplicates()}
    teile = []
    for pid, t, spalte in (("KD3-01", q[q["fluss_gewichtet"].notna() & (q["fonds"] >= MIN_FONDS)], "fluss_gewichtet"),
                           ("IH5-06", q[q["fonds"] >= 1], "fonds")):
        if len(t):
            teile.append(pd.DataFrame({"cik": t["cik"].to_numpy(dtype="int64"), "parameter_id": pid,
                                       "ereignis_zeit": [zeit[p][0] for p in t["periode"]], "verfuegbar_ab": [zeit[p][1] for p in t["periode"]],
                                       "wert": t[spalte].to_numpy(dtype="float64"), "stand": [zeit[p][2] for p in t["periode"]]}))
    return als_parameter(pd.concat(teile, ignore_index=True)) if teile else leer()


# --------------------------------------------------------------------------- Lauf
def _lies_bestand(ablage: Ablage, arbeits: Path, datei: str, fern: bool, meldungen: set) -> pd.DataFrame | None:
    """Bestände der gewählten Meldungen eines Datensatzes: aus der Ablage, sonst aus dem Release (im Tagesbetrieb
    nicht mitgeführt)."""
    pfad = ablage.bereinigt / f"bereinigt__{TABELLE_BESTAND}__{datei}.parquet"
    zwischen = Path(arbeits) / "nport" / pfad.name
    if not pfad.exists() and zwischen.exists():
        pfad = zwischen
    if not pfad.exists():
        repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        if not fern or not repo:
            return None
        try:
            pfad = Abruf(anfragen_pro_sekunde=2, kontakt_noetig=False).hole_datei(
                RELEASE_URL.format(repo=repo, datei=pfad.name), zwischen, erlaube_404=True)
        except QuelleNichtErreichbar:
            return None
        if pfad is None:
            return None
    b = pd.read_parquet(pfad, columns=["accession", "cusip", "stueck"])
    b = b[b["accession"].isin(meldungen)]
    return b.astype({"accession": str, "cusip": str})


def lauf(ablage: Ablage, arbeits: Path, modus: str = "laufend", abruf=None, lokal: Path | None = None,
         budget: Zeitbudget | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    hinweise: list[str] = []
    arbeits = Path(arbeits)
    zuordnung = ablage.lies_bereinigt("ftd_wertpapiere", spalten=["cusip", "cik", "konfidenz", "stamm", "art"])
    if zuordnung.empty:
        raise RuntimeError("CUSIP-Zuordnung fehlt (Quelle sec_ftd zuerst ausführen)")
    gut = zuordnung[zuordnung["cik"].notna() & zuordnung["stamm"] & (zuordnung["konfidenz"] >= MINDEST_KONFIDENZ)]
    zu_firma = gut.drop_duplicates("cusip").set_index("cusip")["cik"].astype("int64")
    if lokal is not None:
        quellen = {k: str(Path(lokal) / Path(v).name) for k, v in
                   links_aus_seite(" ".join(f'href="/{p.name}"' for p in sorted(Path(lokal).glob("*_nport.zip")))).items()}
    else:
        abruf = abruf or Abruf()
        quellen = links_aus_seite(abruf.hole(SEITE).text)
    if not quellen:
        raise RuntimeError("Datenseite nennt keine Datensätze (Aufbau geändert?)")
    budget = budget or Zeitbudget()
    dateien = ablage.lies_bereinigt(TABELLE_DATEIEN)
    fonds = ablage.lies_bereinigt(TABELLE_FONDS)
    firmen = ablage.lies_bereinigt(TABELLE_FIRMEN)
    for t, spalten in ((fonds, ("berichtstag", "eingereicht")), (firmen, ("periode",))):
        for s in spalten:
            if len(t):
                t[s] = pd.to_datetime(t[s])
    gelesen = set(dateien["datei"]) if len(dateien) else set()
    offen = sorted(k for k in quellen if k not in gelesen)
    neu, abgebrochen = [], False
    for schluessel in offen:
        if budget.abgelaufen():
            abgebrochen = True
            break
        pfad = Path(quellen[schluessel]) if lokal is not None else abruf.hole_datei(quellen[schluessel], arbeits / "nport" / f"{schluessel}.zip")
        tab, bestand, info = lies_archiv(pfad, schluessel)
        if lokal is None:
            pfad.unlink(missing_ok=True)
        ablage.schreibe_bereinigt(TABELLE_BESTAND, schluessel, bestand.astype({"cusip": "category", "accession": "category"}))
        fonds = pd.concat([fonds[fonds["datei"] != schluessel], tab], ignore_index=True) if len(fonds) else tab
        neu.append(info)
        gelesen.add(schluessel)
    if neu:
        dateien = pd.concat([dateien, pd.DataFrame(neu)], ignore_index=True) if len(dateien) else pd.DataFrame(neu)
    if dateien.empty or fonds.empty:
        raise RuntimeError("kein Datensatz gelesen")
    ablage.schreibe_bereinigt(TABELLE_DATEIEN, "alle", dateien)
    fonds = fonds.sort_values(["berichtstag", "serie", "eingereicht"], kind="stable").reset_index(drop=True)
    ablage.schreibe_bereinigt(TABELLE_FONDS, "alle", fonds)

    # Berichtsquartale, deren Datensätze vollständig vorliegen und die neu sind oder einen neuen Datensatz berühren
    neu_dateien = {i["datei"] for i in neu}
    fertig = set(firmen["periode"]) if len(firmen) else set()
    perioden = sorted({quartalsende(t) for t in fonds.loc[fonds["art"] == "NPORT-P", "berichtstag"].unique()})
    unvollstaendig, gerechnet = [], []
    for p in perioden:
        noetig = noetige_dateien(p)
        if not set(noetig) <= gelesen:
            unvollstaendig.append(quartal_name(p))
            continue
        if p in fertig and not (set(noetig) & neu_dateien):
            continue
        gewaehlt = waehle_fonds(fonds, p)
        meldungen = set(gewaehlt["accession"])
        teile = [_lies_bestand(ablage, arbeits, d, fern=lokal is None, meldungen=meldungen) for d in noetig]
        if any(t is None for t in teile):
            hinweise.append(f"{quartal_name(p)}: Bestände eines Datensatzes fehlen; Quartal nicht gerechnet")
            continue
        bestand = pd.concat(teile, ignore_index=True)
        teil = verdichte(gewaehlt, bestand, zu_firma)
        teil = teil.assign(periode=p, fonds_quartal=int(len(gewaehlt)))
        firmen = pd.concat([firmen[firmen["periode"] != p], teil], ignore_index=True) if len(firmen) else teil
        gerechnet.append(quartal_name(p))
    if len(firmen):
        firmen = firmen.sort_values(["periode", "cik"], kind="stable").reset_index(drop=True)
        ablage.schreibe_bereinigt(TABELLE_FIRMEN, "alle", firmen)
    parameter = baue_parameter(firmen)
    ablage.schreibe_parameter("edgar_nport", parameter)

    if abgebrochen:
        if modus == "rueckwaerts":
            merke_fortsetzung(ablage.wurzel, "edgar_nport")
        hinweise.append(f"{len([k for k in quellen if k not in gelesen])} Datensätze noch nicht gelesen (Zeitbudget; der nächste Lauf setzt fort)")
    juengstes = firmen["periode"].max() if len(firmen) else None
    info = {"datensaetze_verzeichnis": len(quellen), "datensaetze_gelesen": len(gelesen), "datensaetze_neu": [i["datei"] for i in neu],
            "quartale": int(firmen["periode"].nunique()) if len(firmen) else 0, "gerechnet": gerechnet,
            "unvollstaendig": unvollstaendig, "juengstes_quartal": quartal_name(juengstes) if juengstes is not None else None,
            "fonds_juengstes": int(firmen.loc[firmen["periode"] == juengstes, "fonds_quartal"].max()) if juengstes is not None else 0,
            "firmen_juengstes": int((firmen["periode"] == juengstes).sum()) if juengstes is not None else 0,
            "anteil_mit_fluss": round(float(fonds["fluss"].notna().mean()), 4), "unvollstaendig_abgebrochen": abgebrochen}
    if neu:
        info["neu"] = neu
    return parameter, info, hinweise
