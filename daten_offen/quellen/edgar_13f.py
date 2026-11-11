"""Bestände institutioneller Anleger aus den Form-13F-Datensätzen der SEC (ab Berichtsquartal 2013 Q2).

Je Berichtsquartal zählen nur fristgerechte Erstmeldungen (13F-HR, eingereicht bis zur Frist von 45 Tagen
nach Quartalsende, an Wochenenden und Feiertagen bis zum nächsten Handelstag), ohne Optionen und ohne
Nennbeträge. Je Manager zählt die jüngste solche Meldung. Gespeichert werden Stückzahl und
Portfoliogewicht je Position, nicht der gemeldete Kurswert (keine Kurse im öffentlichen Repo).

Die Zuordnung CUSIP -> CIK kommt aus ``ftd_wertpapiere`` (Quelle sec_ftd). Die Kennzahlen entstehen auf
Firmenebene: Alle Stammaktien-CUSIP einer Firma zählen zusammen, damit ein CUSIP-Wechsel (Aktiensplit,
Umfirmierung, Sitzwechsel) nicht wie ein Aus- und Einstieg aller Halter aussieht.

  edgar_13f_quartal   je CUSIP: halter, stueck
  edgar_13f_firmen    je Firma: halter, beste_idee, breite_aenderung, manager, manager_beide
"""
from __future__ import annotations

import csv
import os
import re
import zipfile
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

_OFFEN = "amtlich offen: Form 13F (§ 13(f) Exchange Act), Frist 45 Tage nach Quartalsende"
_SCHWAECHEN = ("Nur Manager über 100 Mio. $ und nur gemeldete Long-Bestände; Nachträge und verspätete Meldungen "
               "bleiben außen vor; Zuordnung über die CUSIP-Tabelle der Lieferausfälle zum Zeitpunkt der Berechnung "
               "(Trefferquote im Prüfbericht); der Datensatz der SEC erscheint erst Wochen nach der Frist, die "
               "Einzelmeldungen des laufenden Quartals fehlen bis dahin")


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
    zeit = {p: (pd.Timestamp(datetime.combine(p.date(), time(18, 0), tzinfo=ET)).tz_convert("UTC"),
                pd.Timestamp(verfuegbar_ab(p)), quartal_name(p)) for p in q["periode"].drop_duplicates()}
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
         budget: Zeitbudget | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
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
    gelesen = set(dateien["datei"]) if len(dateien) else set()
    offen = [k for k in sorted(quellen, key=fensterende, reverse=True) if k not in gelesen]      # neueste zuerst
    neu, geaendert, abgebrochen = [], set(), False
    vorhanden = set(pd.to_datetime(quartal["periode"])) if len(quartal) else set()
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
            if periode in vorhanden:                         # ein Quartal wird nur einmal geschrieben
                continue
            vorhanden.add(periode)
            geaendert.add(periode)
            bestand, je_cusip, je_firma = verdichte(teil, zu_firma)
            ablage.schreibe_bereinigt(TABELLE_BESTAND, quartal_name(periode), bestand.astype({"cusip": "category"}))
            je_cusip = je_cusip.assign(periode=periode)
            je_firma = je_firma.assign(periode=periode, breite_aenderung=np.nan, manager_beide=0)
            quartal = pd.concat([quartal, je_cusip], ignore_index=True) if len(quartal) else je_cusip
            firmen = pd.concat([firmen, je_firma], ignore_index=True) if len(firmen) else je_firma
        neu.append({"datei": schluessel, **info, "quartale": ",".join(sorted(quartal_name(p) for p in pos["periode"].unique()))})
    if neu:
        dateien = pd.concat([dateien, pd.DataFrame(neu)], ignore_index=True) if len(dateien) else pd.DataFrame(neu)
    if dateien.empty or quartal.empty:
        raise RuntimeError("kein Datensatz gelesen")
    ablage.schreibe_bereinigt(TABELLE_DATEIEN, "alle", dateien)
    quartal["periode"] = pd.to_datetime(quartal["periode"])
    quartal = quartal.sort_values(["periode", "cusip"], kind="stable").reset_index(drop=True)
    ablage.schreibe_bereinigt(TABELLE_QUARTAL, "alle", quartal)

    # Breite: für jedes neue Quartal und für das Quartal nach einem neuen, sofern beide Bestände vorliegen
    if len(firmen):
        firmen["periode"] = pd.to_datetime(firmen["periode"])
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
        ablage.schreibe_bereinigt(TABELLE_FIRMEN, "alle", firmen)

    parameter = baue_parameter(firmen)
    ablage.schreibe_parameter("edgar_13f", parameter)
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
    info = {"datensaetze_verzeichnis": len(quellen), "datensaetze_gelesen": int(len(dateien)), "datensaetze_neu": len(neu),
            "quartale": int(quartal["periode"].nunique()), "juengstes_quartal": quartal_name(quartal["periode"].max()),
            "manager_juengstes": int(firmen.loc[firmen["periode"] == firmen["periode"].max(), "manager"].max()) if len(firmen) else 0,
            "firmen_juengstes": int((firmen["periode"] == firmen["periode"].max()).sum()) if len(firmen) else 0,
            "trefferquote": quote}
    return parameter, info, hinweise
