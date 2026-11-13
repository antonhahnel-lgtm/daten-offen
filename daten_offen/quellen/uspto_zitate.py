"""Zitationen der Patente je Firma aus den Sammeldateien von PatentsView (USPTO).

Die Zitatdatei (``g_us_patent_citation``, entpackt rund 11 GB) nennt zu jedem erteilten Patent die zitierten
US-Patente. Sie liegt wie alle Sammeldateien hinter einer Anmeldung, wird von Hand geladen und nur lokal gelesen
(``--patente-ordner``); im Tageslauf kommt die Quelle nicht vor. Das Amtsblatt nennt keine Zitate, die Reihe endet
deshalb mit dem Stand der Datei.

Voraussetzung: ``uspto_patente`` ist mit demselben Ordner gelaufen (Tabellen ``patente_erteilt`` und
``patente_zuordnung``). Eine bereinigte Tabelle entsteht nicht: Sie wäre ohne die Zitatdatei nicht fortzuschreiben.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from ..kern.ablage import Ablage
from ..kern.schema import Parameter, als_parameter, leer, registriere
from .uspto_patente import (DATEI_PATENT, PARAMETER_AB, SEITE_HISTORIE, TABELLE_ERTEILT, TABELLE_ZUORDNUNG, _lies_jahr,
                            als_tage, als_werte, finde_datei, leseoptionen, lies_tsv, oeffne)

DATEI_ZITATE = "g_us_patent_citation"
FENSTER_TAGE = 5 * 365 + 1         # fünf Jahre zwischen der Erteilung des zitierten und des zitierenden Patents
BLOCK = 64 << 20                   # Bytes je Leseblock
EPOCHE = pd.Timestamp("1970-01-01")

registriere(Parameter(
    id="GA1-09", name="Zitationen der Patente",
    definition="Zahl der Zitationen, die die an einem Ausgabetag neu erteilten Erfindungspatente auf Erfindungspatente "
               "der Firma enthalten, die höchstens fünf Jahre zuvor erteilt wurden (Selbstzitate eingeschlossen). Das "
               "zitierte Patent zählt bei der Firma, die es bei der Erteilung erhielt (Zuordnung wie GA1-01). Wochen "
               "ohne Zeile zählen null; das Verhältnis zum F&E-Aufwand (Katalog: Innovationseffizienz) bildet der Nutzer",
    einheit="Anzahl", frequenz="wöchentlich (Dienstag)",
    offenlegung="amtlich offen: Die Patentschrift nennt die zitierten Schriften und erscheint am Tag der Erteilung",
    quelle=SEITE_HISTORIE, lizenz="PatentsView (USPTO), CC BY 4.0", historie_ab="01/2001",
    verzoegerung="Eröffnung des ersten Handelstags nach dem Ausgabetag des zitierenden Patents",
    schwaechen="Nur aus von Hand geladenen Sammeldateien: Die Reihe endet mit deren Stand und wächst erst mit einer "
               "neu geladenen Datei (das Amtsblatt nennt keine Zitate). Rohe Zahl ohne Bereinigung um Technikfeld und "
               "Jahrgang; Zuordnung und ihre Lücken wie GA1-01"))


def _zahl(spalte) -> np.ndarray:
    """Patentnummern als Zahl; Nummern mit Vorsatz (D, PP, RE …) und unlesbare werden -1."""
    werte = pd.to_numeric(pd.Series(spalte, dtype=pd.ArrowDtype(spalte.type)), errors="coerce")
    werte = werte.to_numpy(dtype="float64", na_value=np.nan)
    return np.where(np.isnan(werte), -1, werte).astype(np.int64)


def erteilungstage(ordner: Path) -> np.ndarray:
    """Erteilungstag je Erfindungspatent in Tagen seit 1970; Index ist die Patentnummer, -1 heißt unbekannt."""
    pfad = finde_datei(ordner, DATEI_PATENT)
    if pfad is None:
        raise RuntimeError(f"{DATEI_PATENT}.tsv fehlt in {ordner}")
    p = lies_tsv(pfad, ["patent_id", "patent_type", "patent_date", "withdrawn"])
    p = p.filter(pc.and_(pc.equal(p["patent_type"], "utility"), pc.not_equal(p["withdrawn"], "1")))
    nummer = _zahl(p["patent_id"].combine_chunks())
    tag = als_tage(p["patent_date"]).to_numpy(zero_copy_only=False).astype("datetime64[D]")
    gut = (nummer >= 0) & ~np.isnat(tag)
    feld = np.full(int(nummer[gut].max()) + 1 if gut.any() else 1, -1, dtype=np.int32)
    feld[nummer[gut]] = tag[gut].astype(np.int64)
    return feld


def besitz(ablage: Ablage) -> pd.DataFrame:
    """Erfindungspatente mit der Firma, die sie bei der Erteilung erhielt (Spalten nummer, cik)."""
    zuordnung = ablage.lies_bereinigt(TABELLE_ZUORDNUNG)
    jahre = sorted(int(p.stem.rsplit("__", 1)[1]) for p in ablage.bereinigt.glob(f"bereinigt__{TABELLE_ERTEILT}__*.parquet"))
    if zuordnung.empty or not jahre:
        raise RuntimeError("Tabellen der Patente fehlen (Quelle uspto_patente zuerst mit --patente-ordner ausführen)")
    treffer = zuordnung[zuordnung["cik"].notna()][["inhaber", "cik", "gilt_ab", "gilt_bis"]]
    teile = []
    for jahr in jahre:
        t = _lies_jahr(ablage, jahr)
        t = t[t["art"] == "utility"].merge(treffer, on="inhaber", how="inner")
        t = t[(t["gilt_ab"].isna() | (t["tag"] >= t["gilt_ab"])) & (t["gilt_bis"].isna() | (t["tag"] < t["gilt_bis"]))]
        nummer = pd.to_numeric(t["nummer"], errors="coerce")
        teile.append(pd.DataFrame({"nummer": nummer[nummer.notna()].astype("int64"),
                                   "cik": t.loc[nummer.notna(), "cik"].astype("int64")}).drop_duplicates())
    return pd.concat(teile, ignore_index=True)


def zaehle(pfad: Path, tage: np.ndarray, eigner: pd.DataFrame, block: int = BLOCK) -> tuple[pd.DataFrame, dict]:
    """Liest die Zitatdatei in Blöcken: Zitate je Firma des zitierten Patents und Ausgabetag des zitierenden."""
    info = {"zitate": 0, "zwischen_erfindungspatenten": 0, "im_fenster": 0, "zugeordnet": 0}
    ab = int((PARAMETER_AB - EPOCHE).days)
    eigner = eigner[eigner["nummer"] < len(tage)]
    doppelt = eigner.duplicated("nummer")
    erste = np.zeros(len(tage), dtype=np.int64)                      # Firma je Patent; weitere Mitinhaber in ``weitere``
    erste[eigner.loc[~doppelt, "nummer"].to_numpy()] = eigner.loc[~doppelt, "cik"].to_numpy()
    weitere = eigner[doppelt]
    summen, gemeldet = [], 0
    letztes, gesehen = -1, set()         # Zitate des letzten Patents im vorigen Block (doppelte Meldungen über die Blockgrenze)
    with oeffne(pfad) as datei:
        for stapel in pacsv.open_csv(datei, **leseoptionen(["patent_id", "citation_patent_id"], block)):
            info["zitate"] += stapel.num_rows
            von, auf = _zahl(stapel.column(0)), _zahl(stapel.column(1))
            gut = (von >= 0) & (auf >= 0) & (von < len(tage)) & (auf < len(tage))
            von, auf = von[gut], auf[gut]
            tag_von, tag_auf = tage[von], tage[auf]
            gut = (tag_von >= 0) & (tag_auf >= 0)
            info["zwischen_erfindungspatenten"] += int(gut.sum())
            gut &= (tag_von >= ab) & (tag_von > tag_auf) & (tag_von - tag_auf <= FENSTER_TAGE)
            z = pd.DataFrame({"von": von[gut], "nummer": auf[gut], "tag": tag_von[gut]}).drop_duplicates(["von", "nummer"])
            if len(z) and gesehen:
                z = z[~((z["von"] == letztes) & z["nummer"].isin(gesehen))]
            if len(von):
                letztes = int(von[-1])
                gesehen = set(auf[von == letztes].tolist())
            info["im_fenster"] += len(z)
            z["cik"] = erste[z["nummer"].to_numpy()]
            zusatz = z[["von", "nummer", "tag"]].merge(weitere, on="nummer", how="inner") if len(weitere) else z.iloc[:0]
            z = z[z["cik"] > 0]
            info["zugeordnet"] += len(z)
            summen.append(pd.concat([z[["cik", "tag"]], zusatz[["cik", "tag"]]]).groupby(["cik", "tag"], as_index=False).size())
            if info["zitate"] - gemeldet >= 10_000_000:
                gemeldet = info["zitate"]
                print(f"Zitate: {info['zitate'] // 1_000_000} Mio. gelesen, {info['im_fenster'] // 1_000_000} Mio. im Fenster", flush=True)
    if not summen:
        return pd.DataFrame(columns=["cik", "tag", "wert"]), info
    werte = pd.concat(summen, ignore_index=True).groupby(["cik", "tag"], as_index=False)["size"].sum()
    werte["tag"] = EPOCHE + pd.to_timedelta(werte["tag"], unit="D")
    return werte.rename(columns={"size": "wert"}), info


def lauf(ablage: Ablage, ordner: Path | None, block: int = BLOCK) -> tuple[pd.DataFrame, dict, list[str]]:
    if ordner is None:
        raise RuntimeError("Die Zitate werden nur lokal gelesen: --patente-ordner mit den Sammeldateien angeben")
    pfad = finde_datei(Path(ordner), DATEI_ZITATE)
    if pfad is None:
        raise RuntimeError(f"{DATEI_ZITATE}.tsv fehlt in {ordner}")
    eigner = besitz(ablage)
    tage = erteilungstage(Path(ordner))
    werte, info = zaehle(pfad, tage, eigner, block)
    parameter = als_werte(werte, "GA1-09") if len(werte) else leer()
    ablage.schreibe_parameter("uspto_zitate", als_parameter(parameter))
    info.update(patente_mit_firma=int(eigner["nummer"].nunique()), firmen=int(parameter["cik"].nunique()) if len(parameter) else 0,
                anteil_zugeordnet=round(info["zugeordnet"] / max(info["im_fenster"], 1), 4))
    if len(werte):
        info.update(von=werte["tag"].min().date().isoformat(), bis=werte["tag"].max().date().isoformat())
    hinweise = [f"Zitate im Fünfjahresfenster: {info['im_fenster']}, davon {info['anteil_zugeordnet']:.1%} auf Patente "
                "zugeordneter Firmen"]
    return parameter, info, hinweise
