"""EDGAR-Meldungsverzeichnis aus der amtlichen Sammeldatei ``submissions.zip``.

Liefert je Meldung: Firma (CIK), Aktenzeichen, Formular, Einreichungsdatum, Annahmezeit
und daraus ``verfuegbar_ab``. Das Verzeichnis ist die Zeitbasis aller EDGAR-Parameter.

Die Annahmezeit steht in der Quelle ohne verlässliche Zeitzone; sie wird je Lauf gegen das
Einreichungsdatum geprüft (siehe :func:`erkenne_annahme_zeitzone`).
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.zeit import ET, handelbar_ab_serie

SAMMEL_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
DATEI_MUSTER = re.compile(r"^CIK(\d{10})(-submissions-\d+)?\.json$")
FELDER = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "items",
          "primaryDocument", "isXBRL"]
ROH_SCHEMA = pa.schema([
    ("cik", pa.int64()), ("accession", pa.string()), ("form", pa.string()),
    ("filing_date", pa.string()), ("report_date", pa.string()), ("annahme_roh", pa.string()),
    ("items", pa.string()), ("primary_document", pa.string()), ("is_xbrl", pa.bool_()),
])
PRUEF_FORMEN = {"8-K", "10-Q", "10-K"}  # Annahmeschluss 17:30 ET; Formulare 3/4/5 haben 22:00 ET


def _spalten(block: dict, cik: int, ab: str) -> dict | None:
    """Wandelt die Spaltenfelder einer Quelldatei in Listen; filtert auf Einreichungsdatum >= ab."""
    nummern = block.get("accessionNumber") or []
    n = len(nummern)
    if n == 0:
        return None
    roh = {f: (block.get(f) or [None] * n) for f in FELDER}
    if any(len(v) != n for v in roh.values()):
        raise ValueError(f"CIK {cik}: Spaltenlängen der Quelle stimmen nicht überein")
    behalte = [i for i, d in enumerate(roh["filingDate"]) if d and d >= ab]
    if not behalte:
        return None
    text = lambda f: [None if roh[f][i] in (None, "") else str(roh[f][i]) for i in behalte]
    return {
        "cik": [cik] * len(behalte), "accession": text("accessionNumber"), "form": text("form"),
        "filing_date": text("filingDate"), "report_date": text("reportDate"),
        "annahme_roh": text("acceptanceDateTime"), "items": text("items"),
        "primary_document": text("primaryDocument"),
        "is_xbrl": [bool(roh["isXBRL"][i]) for i in behalte],
    }


def _firma(d: dict, cik: int) -> dict:
    geschaeft = (d.get("addresses") or {}).get("business") or {}
    return {
        "cik": cik, "name": d.get("name"), "entity_type": d.get("entityType"),
        "sic": str(d.get("sic") or "") or None, "sic_beschreibung": d.get("sicDescription"),
        "tickers": ",".join(d.get("tickers") or []) or None,
        "boersen": ",".join(x or "" for x in (d.get("exchanges") or [])) or None,
        "kategorie": d.get("category"), "geschaeftsjahresende": d.get("fiscalYearEnd"),
        "gruendungsstaat": d.get("stateOfIncorporation"),
        "sitz_staat": geschaeft.get("stateOrCountry"), "sitz_plz": geschaeft.get("zipCode"),
        "fruehere_namen": json.dumps(d.get("formerNames") or [], ensure_ascii=False),
    }


def erkenne_annahme_zeitzone(df: pd.DataFrame) -> tuple[str, float, float]:
    """Entscheidet, ob die Annahmezeit der Quelle Ostküstenzeit (ET) oder UTC ist.

    Maßstab: Bis 17:30 ET angenommene Meldungen tragen das Datum des Annahmetags, spätere das
    des nächsten Werktags. Geprüft wird, welche Lesart das Einreichungsdatum häufiger trifft.
    Rückgabe: (gewählte Zone, Trefferquote ET, Trefferquote UTC).
    """
    teil = df[df["form"].isin(PRUEF_FORMEN) & df["annahme_naiv"].notna() & df["filing_date"].notna()]
    if len(teil) > 200_000:
        teil = teil.sample(200_000, random_state=0)
    if teil.empty:
        return "ET", float("nan"), float("nan")

    def quote(lokal: pd.Series) -> float:
        tag = lokal.dt.normalize()
        spaet = (lokal.dt.hour * 60 + lokal.dt.minute) > 17 * 60 + 30
        wt = tag.dt.weekday
        versatz = pd.Series(0, index=lokal.index)
        versatz[spaet & (wt < 4)] = 1
        versatz[spaet & (wt == 4)] = 3
        versatz[wt == 5] = 2
        versatz[wt == 6] = 1
        erwartet = tag + pd.to_timedelta(versatz, unit="D")
        return float((erwartet == teil["filing_date"]).mean())

    naiv = teil["annahme_naiv"]
    q_et = quote(naiv)
    q_utc = quote(naiv.dt.tz_localize("UTC").dt.tz_convert(ET).dt.tz_localize(None))
    return ("UTC" if q_utc > q_et else "ET"), q_et, q_utc


def _schliesse_jahr(roh_pfad: Path, zone: str) -> pd.DataFrame:
    df = pd.read_parquet(roh_pfad)
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    naiv = pd.to_datetime(df["annahme_roh"].str.replace("Z", "", regex=False), format="ISO8601", errors="coerce")
    if zone == "UTC":
        annahme = naiv.dt.tz_localize("UTC")
    else:
        annahme = naiv.dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    # Ersatz ohne Annahmezeit: Einreichungstag 17:30 ET (vorsichtig, also erst am nächsten Handelstag nutzbar)
    ersatz = (df["filing_date"] + pd.Timedelta(hours=17, minutes=30)).dt.tz_localize(
        ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    df["annahme_geschaetzt"] = annahme.isna()
    df["annahme_utc"] = annahme.fillna(ersatz).astype("datetime64[us, UTC]")
    df["verfuegbar_ab"] = handelbar_ab_serie(df["annahme_utc"]).astype("datetime64[us, UTC]")
    df = df.drop(columns=["annahme_roh"]).drop_duplicates(["cik", "accession"])
    return df.sort_values(["annahme_utc", "cik", "accession"], kind="stable").reset_index(drop=True)


def baue_index(zip_pfad: Path, ablage: Ablage, arbeits: Path, ab_jahr: int = 2006) -> dict:
    """Liest die Sammeldatei und schreibt ``edgar_meldungen`` (je Jahr) und ``edgar_firmen``."""
    arbeits = Path(arbeits)
    roh_ordner = arbeits / "index_roh"
    roh_ordner.mkdir(parents=True, exist_ok=True)
    for alt in roh_ordner.glob("*.parquet"):
        alt.unlink()
    ab = f"{ab_jahr}-01-01"
    schreiber: dict[int, pq.ParquetWriter] = {}
    puffer: dict[str, list] = {f.name: [] for f in ROH_SCHEMA}
    firmen: list[dict] = []
    dateien = 0

    def leere_puffer() -> None:
        if not puffer["cik"]:
            return
        df = pd.DataFrame(puffer)
        for jahr, teil in df.groupby(df["filing_date"].str.slice(0, 4).astype(int)):
            if jahr not in schreiber:
                schreiber[jahr] = pq.ParquetWriter(roh_ordner / f"{jahr}.parquet", ROH_SCHEMA, compression="zstd")
            schreiber[jahr].write_table(pa.Table.from_pandas(teil, schema=ROH_SCHEMA, preserve_index=False))
        for liste in puffer.values():
            liste.clear()

    with zipfile.ZipFile(zip_pfad) as archiv:
        for name in archiv.namelist():
            treffer = DATEI_MUSTER.match(Path(name).name)
            if not treffer:
                continue
            cik = int(treffer.group(1))
            with archiv.open(name) as f:
                d = json.load(f)
            dateien += 1
            if treffer.group(2) is None:
                firmen.append(_firma(d, cik))
                block = (d.get("filings") or {}).get("recent") or {}
            else:
                block = d
            spalten = _spalten(block, cik, ab)
            if spalten:
                for k, v in spalten.items():
                    puffer[k].extend(v)
            if len(puffer["cik"]) >= 500_000:
                leere_puffer()
    leere_puffer()
    for s in schreiber.values():
        s.close()
    if not schreiber:
        raise RuntimeError("Sammeldatei enthält keine Meldungen im gewünschten Zeitraum")

    # Zeitzone der Annahmezeit am jüngsten vollständigen Jahr prüfen
    jahre = sorted(schreiber)
    pruefjahr = jahre[-2] if len(jahre) > 1 else jahre[-1]
    probe = pd.read_parquet(roh_ordner / f"{pruefjahr}.parquet", columns=["form", "filing_date", "annahme_roh"])
    probe["filing_date"] = pd.to_datetime(probe["filing_date"], errors="coerce")
    probe["annahme_naiv"] = pd.to_datetime(probe["annahme_roh"].str.replace("Z", "", regex=False), format="ISO8601", errors="coerce")
    zone, q_et, q_utc = erkenne_annahme_zeitzone(probe)

    zeilen = 0
    geschaetzt = 0
    for jahr in jahre:
        df = _schliesse_jahr(roh_ordner / f"{jahr}.parquet", zone)
        zeilen += len(df)
        geschaetzt += int(df["annahme_geschaetzt"].sum())
        ablage.schreibe_bereinigt("edgar_meldungen", str(jahr), df)
    ablage.schreibe_bereinigt("edgar_firmen", "alle", pd.DataFrame(firmen))
    return {"quelldateien": dateien, "firmen": len(firmen), "meldungen": zeilen, "jahre": [jahre[0], jahre[-1]],
            "annahme_zeitzone": zone, "trefferquote_et": q_et, "trefferquote_utc": q_utc,
            "annahme_geschaetzt": geschaetzt}


def lauf(ablage: Ablage, arbeits: Path, ab_jahr: int = 2006, zip_pfad: Path | None = None,
         abruf: Abruf | None = None) -> tuple[dict, list[str], list[str]]:
    """Vollständiger Neuaufbau (die Sammeldatei wird von der SEC jede Nacht neu erzeugt)."""
    arbeits = Path(arbeits)
    if zip_pfad is None:
        abruf = abruf or Abruf()
        zip_pfad = abruf.hole_datei(SAMMEL_URL, arbeits / "submissions.zip")
    info = baue_index(Path(zip_pfad), ablage, arbeits, ab_jahr)
    schwer, hinweise = [], []
    beste = max(q for q in (info["trefferquote_et"], info["trefferquote_utc"]) if q == q) \
        if (info["trefferquote_et"] == info["trefferquote_et"]) else float("nan")
    hinweise.append(f"Annahmezeit gelesen als {info['annahme_zeitzone']} "
                    f"(Trefferquote ET {info['trefferquote_et']:.3f}, UTC {info['trefferquote_utc']:.3f})")
    if not beste == beste or beste < 0.9:
        schwer.append("Zeitzone der Annahmezeit nicht sicher bestimmbar (Trefferquote unter 0,9)")
    anteil = info["annahme_geschaetzt"] / max(info["meldungen"], 1)
    hinweise.append(f"Annahmezeit geschätzt bei {info['annahme_geschaetzt']} Meldungen ({anteil:.2%})")
    if anteil > 0.05:
        schwer.append("Mehr als 5 % der Meldungen ohne Annahmezeit")
    return info, schwer, hinweise
