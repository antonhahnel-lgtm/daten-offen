"""Bestände institutioneller Anleger aus den Form-13F-Datensätzen der SEC (ab Berichtsquartal 2013 Q1).

Je Berichtsquartal zählen nur fristgerechte Erstmeldungen (13F-HR, eingereicht bis 47 Tage nach
Quartalsende), ohne Optionen und ohne Nennbeträge. Je Manager zählt die jüngste solche Meldung.
Gespeichert werden Stückzahl und Portfoliogewicht je Position, nicht der gemeldete Kurswert
(keine Kurse im öffentlichen Repo). Die Zuordnung CUSIP -> CIK kommt aus ``ftd_wertpapiere``
(Quelle sec_ftd).

Kennzahlen je Wertpapier und Quartal:
  halter             Zahl der Manager mit Bestand
  breite_aenderung   (Halter heute − Halter im Vorquartal) / Manager, jeweils nur unter Managern, die
                     in beiden Quartalen gemeldet haben (Chen, Hong & Stein 2002)
  beste_idee         Zahl konzentrierter Manager (10–200 Positionen), deren größtes Übergewicht gegenüber
                     dem Gesamtbestand aller Manager dieses Wertpapier ist
"""
from __future__ import annotations

import csv
import re
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.namen import trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab
from ..kern.zustand import Zeitbudget, merke_fortsetzung

SEITE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
LINK_MUSTER = re.compile(r'href="([^"]*?/(\d{4}q[1-4]|\d{2}[a-z]{3}\d{4}-\d{2}[a-z]{3}\d{4})_form13f\.zip)"', re.I)
FRIST_TAGE = 47            # gesetzliche Frist 45 Tage; fällt sie auf ein Wochenende, gilt der nächste Werktag
MIN_POSITIONEN, MAX_POSITIONEN = 10, 200
MINDEST_KONFIDENZ = 0.90
MONATE = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
TABELLE_DATEIEN, TABELLE_BESTAND, TABELLE_QUARTAL = "edgar_13f_dateien", "edgar_13f_bestaende", "edgar_13f_quartal"
SPALTEN_MELDUNG = ["ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"]
SPALTEN_POSITION = ["ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"]

_OFFEN = "amtlich offen: Form 13F (§ 13(f) Exchange Act), Frist 45 Tage nach Quartalsende"
_SCHWAECHEN = ("Nur Manager über 100 Mio. $ und nur gemeldete Long-Bestände; Nachträge und verspätete Meldungen "
               "bleiben außen vor; Zuordnung über die CUSIP-Tabelle der Lieferausfälle (Trefferquote im Prüfbericht); "
               "der Datensatz der SEC erscheint erst Wochen nach der Frist, die Einzelmeldungen des laufenden "
               "Quartals fehlen bis dahin")


def _p(id_, name, definition, einheit, schwaechen=""):
    return Parameter(id=id_, name=name, definition=definition, einheit=einheit, frequenz="je Berichtsquartal",
                     offenlegung=_OFFEN, quelle=SEITE, lizenz="gemeinfrei (US-Behörde)", historie_ab="2013",
                     verzoegerung=f"erster Handelstag nach Quartalsende + {FRIST_TAGE} Tage",
                     schwaechen=(schwaechen + " " + _SCHWAECHEN).strip())


registriere(
    _p("IH5-04", "Eigentümerbreite (Änderung)",
       "Halter im Quartal minus Halter im Vorquartal, geteilt durch die Zahl der Manager; gezählt werden nur "
       "Manager, die in beiden Quartalen gemeldet haben (Chen, Hong & Stein 2002). Die Zahl der Halter selbst "
       "steht in der bereinigten Tabelle edgar_13f_quartal", "Anteil der Manager",
       "Hält ein Manager zwei Gattungen einer Firma, zählt die Gattung mit den meisten Haltern."),
    _p("IH5-03", "Beste Ideen der Manager",
       f"Zahl der Manager mit {MIN_POSITIONEN} bis {MAX_POSITIONEN} Positionen, deren größtes Übergewicht "
       "(Portfoliogewicht minus Gewicht im Gesamtbestand aller Manager) diese Firma ist; nur Werte ab 1", "Anzahl",
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


def verfuegbar_ab(periode) -> datetime:
    """Eröffnung des ersten Handelstags nach Ablauf der Frist: dann sind alle gezählten Meldungen öffentlich."""
    tag = pd.Timestamp(periode).date() + timedelta(days=FRIST_TAGE)
    return handelbar_ab(datetime.combine(tag, time(18, 0), tzinfo=ET))


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
        tage = (sub["eingereicht"] - sub["periode"]).dt.days
        quartalsende = sub["periode"].dt.is_quarter_end
        erst = int(len(sub))
        sub = sub[(tage > 0) & (tage <= FRIST_TAGE) & quartalsende]
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
def verdichte(pos: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aus den Positionen eines Quartals: (Bestandstabelle mit Portfoliogewicht, Kennzahlen je CUSIP)."""
    summe = pos.groupby("filer_cik")["wert"].transform("sum")
    gewicht = (pos["wert"] / summe.where(summe > 0)).astype("float64")
    je_cusip = pos.groupby("cusip").agg(halter=("filer_cik", "nunique"), stueck=("stueck", "sum"))
    # Gewicht im Gesamtbestand: Stückzahl mal mittlerem gemeldetem Wert je Stück (Median über die Manager);
    # der Median fängt Manager ab, die in der falschen Einheit melden (Tausend statt Dollar)
    je_stueck = (pos["wert"] / pos["stueck"]).where(pos["wert"] > 0)
    mitte = je_stueck.groupby(pos["cusip"]).median()
    gesamt = (je_cusip["stueck"] * mitte.reindex(je_cusip.index)).fillna(0.0)
    vergleich = gesamt / gesamt.sum() if gesamt.sum() > 0 else gesamt
    zahl = pos.groupby("filer_cik")["cusip"].transform("size")
    aktiv = (zahl >= MIN_POSITIONEN) & (zahl <= MAX_POSITIONEN) & gewicht.notna()
    ueber = (gewicht - pos["cusip"].map(vergleich))[aktiv]
    je_cusip["beste_idee"] = 0
    if len(ueber):
        beste = pos.loc[ueber.groupby(pos.loc[aktiv, "filer_cik"]).idxmax(), "cusip"].value_counts()
        je_cusip["beste_idee"] = beste.reindex(je_cusip.index).fillna(0).astype("int64")
    je_cusip["manager"] = int(pos["filer_cik"].nunique())
    bestand = pd.DataFrame({"filer_cik": pos["filer_cik"].to_numpy(), "cusip": pos["cusip"].to_numpy(),
                            "stueck": pos["stueck"].round().astype("int64").to_numpy(),
                            "gewicht": gewicht.astype("float32").to_numpy()})
    return bestand.sort_values(["filer_cik", "cusip"], kind="stable").reset_index(drop=True), je_cusip.reset_index()


def breite_aenderung(heute: pd.DataFrame, vor: pd.DataFrame) -> pd.DataFrame:
    """Änderung der Eigentümerbreite je CUSIP unter Managern, die in beiden Quartalen gemeldet haben."""
    beide = np.intersect1d(heute["filer_cik"].unique(), vor["filer_cik"].unique())
    if not len(beide):
        return pd.DataFrame(columns=["cusip", "breite_aenderung", "manager_beide"])
    h1 = heute[heute["filer_cik"].isin(beide)].groupby("cusip")["filer_cik"].nunique()
    h0 = vor[vor["filer_cik"].isin(beide)].groupby("cusip")["filer_cik"].nunique()
    alle = h1.index.union(h0.index)
    d = (h1.reindex(alle, fill_value=0) - h0.reindex(alle, fill_value=0)) / len(beide)
    return pd.DataFrame({"cusip": alle.astype(str), "breite_aenderung": d.to_numpy(dtype="float64"), "manager_beide": len(beide)})


def baue_parameter(quartal: pd.DataFrame, zuordnung: pd.DataFrame) -> pd.DataFrame:
    if quartal.empty or zuordnung.empty:
        return leer()
    z = zuordnung[zuordnung["cik"].notna() & zuordnung["stamm"] & (zuordnung["konfidenz"] >= MINDEST_KONFIDENZ)]
    q = quartal.merge(z[["cusip", "cik"]].astype({"cik": "int64"}), on="cusip", how="inner")
    if q.empty:
        return leer()
    q["periode"] = pd.to_datetime(q["periode"])
    zeit = {p: (pd.Timestamp(datetime.combine(p.date(), time(18, 0), tzinfo=ET)).tz_convert("UTC"),
                pd.Timestamp(verfuegbar_ab(p)), quartal_name(p)) for p in q["periode"].drop_duplicates()}
    teile = []
    breite = q[q["breite_aenderung"].notna()].sort_values("halter", kind="stable").drop_duplicates(["cik", "periode"], keep="last")
    ideen = q.groupby(["cik", "periode"], as_index=False)["beste_idee"].sum()
    for pid, tabelle, spalte in (("IH5-04", breite, "breite_aenderung"), ("IH5-03", ideen[ideen["beste_idee"] >= 1], "beste_idee")):
        if tabelle.empty:
            continue
        teile.append(pd.DataFrame({
            "cik": tabelle["cik"].to_numpy(), "parameter_id": pid,
            "ereignis_zeit": [zeit[p][0] for p in tabelle["periode"]],
            "verfuegbar_ab": [zeit[p][1] for p in tabelle["periode"]],
            "wert": tabelle[spalte].to_numpy(dtype="float64"), "stand": [zeit[p][2] for p in tabelle["periode"]]}))
    return als_parameter(pd.concat(teile, ignore_index=True)) if teile else leer()


# --------------------------------------------------------------------------- Lauf
def _bestand_pfad(ablage: Ablage, periode) -> Path:
    return ablage.bereinigt / f"bereinigt__{TABELLE_BESTAND}__{quartal_name(periode)}.parquet"


def lauf(ablage: Ablage, arbeits: Path, modus: str = "laufend", abruf: Abruf | None = None, lokal: Path | None = None,
         budget: Zeitbudget | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    hinweise: list[str] = []
    zuordnung = ablage.lies_bereinigt("ftd_wertpapiere", spalten=["cusip", "cik", "konfidenz", "stamm", "art"])
    if zuordnung.empty:
        raise RuntimeError("CUSIP-Zuordnung fehlt (Quelle sec_ftd zuerst ausführen)")
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
    gelesen = set(dateien["datei"]) if len(dateien) else set()
    offen = [k for k in sorted(quellen, key=fensterende, reverse=True) if k not in gelesen]      # neueste zuerst
    neu, geaendert, abgebrochen = [], set(), False
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
        teile = []
        for periode, teil in pos.groupby("periode"):
            if _bestand_pfad(ablage, periode).exists():      # ein Quartal wird nur einmal geschrieben
                continue
            bestand, je_cusip = verdichte(teil)
            ablage.schreibe_bereinigt(TABELLE_BESTAND, quartal_name(periode), bestand.astype({"cusip": "category"}))
            teile.append(je_cusip.assign(periode=pd.Timestamp(periode)))
            geaendert.add(pd.Timestamp(periode))
        if teile:
            zusatz = pd.concat(teile, ignore_index=True).assign(breite_aenderung=np.nan, manager_beide=0)
            quartal = pd.concat([quartal, zusatz], ignore_index=True) if len(quartal) else zusatz
        neu.append({"datei": schluessel, **info, "quartale": ",".join(sorted(quartal_name(p) for p in pos["periode"].unique()))})
    if neu:
        dateien = pd.concat([dateien, pd.DataFrame(neu)], ignore_index=True) if len(dateien) else pd.DataFrame(neu)
    if dateien.empty or quartal.empty:
        raise RuntimeError("kein Datensatz gelesen")
    ablage.schreibe_bereinigt(TABELLE_DATEIEN, "alle", dateien)

    # Breite: für jedes neue Quartal und für das Quartal nach einem neuen, sofern beide Bestände vorliegen
    quartal["periode"] = pd.to_datetime(quartal["periode"])
    perioden = sorted(quartal["periode"].unique())
    ohne_vorquartal = 0
    for p in perioden:
        vor = (pd.Timestamp(p) - pd.offsets.QuarterEnd(1)).normalize()
        if pd.Timestamp(p) not in geaendert and vor not in geaendert:
            continue
        if not (_bestand_pfad(ablage, p).exists() and _bestand_pfad(ablage, vor).exists()):
            ohne_vorquartal += pd.Timestamp(p) in geaendert
            continue
        heute = pd.read_parquet(_bestand_pfad(ablage, p), columns=["filer_cik", "cusip"]).astype({"cusip": str})
        davor = pd.read_parquet(_bestand_pfad(ablage, vor), columns=["filer_cik", "cusip"]).astype({"cusip": str})
        d = breite_aenderung(heute, davor).assign(periode=pd.Timestamp(p))
        rest = quartal[quartal["periode"] != pd.Timestamp(p)]
        teil = quartal[quartal["periode"] == pd.Timestamp(p)].drop(columns=["breite_aenderung", "manager_beide"])
        teil = teil.merge(d, on=["cusip", "periode"], how="outer")
        for s in ("halter", "stueck", "beste_idee"):
            teil[s] = teil[s].fillna(0).astype("int64")
        teil["manager"] = teil["manager"].ffill().bfill().astype("int64")
        teil["manager_beide"] = teil["manager_beide"].ffill().bfill().fillna(0).astype("int64")
        teil["breite_aenderung"] = teil["breite_aenderung"].fillna(0.0)      # nur von neuen Managern gehalten
        quartal = pd.concat([rest, teil], ignore_index=True)
    quartal = quartal.sort_values(["periode", "cusip"], kind="stable").reset_index(drop=True)
    ablage.schreibe_bereinigt(TABELLE_QUARTAL, "alle", quartal)

    parameter = baue_parameter(quartal, zuordnung)
    ablage.schreibe_parameter("edgar_13f", parameter)
    rest = len([k for k in quellen if k not in set(dateien["datei"])])
    if abgebrochen and modus == "rueckwaerts":
        merke_fortsetzung(ablage.wurzel, "edgar_13f")
    if rest:
        hinweise.append(f"{rest} Datensätze noch nicht gelesen (Zeitbudget; der nächste Lauf setzt fort)")
    if ohne_vorquartal:
        hinweise.append(f"{ohne_vorquartal} Quartale ohne Vorquartal: Änderung der Breite folgt mit dem nächsten Datensatz")
    juengstes = quartal[(quartal["periode"] == quartal["periode"].max()) & (quartal["halter"] >= 10)]
    z = juengstes[["cusip"]].merge(zuordnung[zuordnung["stamm"] & (zuordnung["konfidenz"] >= MINDEST_KONFIDENZ)],
                                   on="cusip", how="left")
    z["art"] = z["art"].fillna("keiner")
    quote = trefferquote(z, gewicht=juengstes["halter"].astype("float64").reset_index(drop=True)) if len(z) else \
        {"zeilen": 0, "quote": 0.0, "arten": {}}
    hinweise.append(f"Zuordnung: {quote.get('quote', 0):.1%} der Wertpapiere mit mindestens 10 Haltern im jüngsten Quartal "
                    f"({quote.get('quote_gewichtet', 0):.1%} nach Haltern gewichtet); darunter auch Fonds und Vorzüge")
    info = {"datensaetze_verzeichnis": len(quellen), "datensaetze_gelesen": int(len(dateien)), "datensaetze_neu": len(neu),
            "quartale": int(quartal["periode"].nunique()), "juengstes_quartal": quartal_name(quartal["periode"].max()),
            "manager_juengstes": int(quartal.loc[quartal["periode"] == quartal["periode"].max(), "manager"].max()),
            "trefferquote": quote}
    return parameter, info, hinweise
