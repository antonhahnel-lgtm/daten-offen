"""Lieferausfälle (Fails-to-Deliver) aus den Dateien der SEC.

Die SEC veröffentlicht je Monatshälfte den Bestand nicht gelieferter Stücke je Wertpapier und
Abwicklungstag (bis Mitte 2009 je Quartal; bis 15.09.2008 nur Bestände ab 10.000 Stück).
Die Dateien nennen CUSIP, Börsenkürzel und eine gekürzte Bezeichnung, aber keine CIK. Zuordnung je CUSIP:
  0,98  das jüngste Kürzel gehört heute genau einer Firma und die Bezeichnung beginnt wie deren Name
  0,93  das Kürzel passt und die CUSIP war im letzten Jahr aktiv
  sonst Namensabgleich über die Bezeichnung (Firmen ohne heutiges Kürzel, z. B. nach Delisting)
Die Preisspalte der Quelle wird nicht übernommen (keine Kurse im öffentlichen Repo).
Die Tabelle ``ftd_wertpapiere`` (CUSIP -> CIK) dient auch anderen Quellen, die nur die CUSIP nennen.
"""
from __future__ import annotations

import csv
import json
import re
import zipfile
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.namen import RECHTSFORM, Namensabgleich, bereinige, trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import EROEFFNUNG, ET, UTC, handelbar_ab_serie
from ..kern.zustand import Zeitbudget, merke_fortsetzung

SEITE = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
LINK_MUSTER = re.compile(r'href="([^"]*?/(?:cnsfails(\d{6}[ab])(?:_\d+)?|cnsp_sec_fails_(\d{4}q\d))\.zip)"', re.I)
SPALTEN = {"SETTLEMENT DATE": "tag", "CUSIP": "cusip", "SYMBOL": "symbol", "QUANTITY (FAILS)": "stueck",
           "DESCRIPTION": "beschreibung"}
SCHWELLE = 10_000          # erste Bedingung der Threshold-Liste (Reg SHO Rule 203(c)(6))
VERZUG_HALBMONAT = 30      # Tage nach Periodenende, wenn der wahre Veröffentlichungstag unbekannt ist (üblich: 14–19)
VERZUG_QUARTAL = 60
FENSTER_TAGE = 90          # so lange nach Periodenende gilt der Änderungszeitpunkt der Datei als Erstveröffentlichung
AKTIV_TAGE = 400
NEU_LADEN = 4              # die jüngsten Dateien werden bei jedem Lauf neu gelesen (Korrekturen der SEC)
MINDEST_KONFIDENZ = 0.90
FONDS_SIC = {"6726", "6221"}   # Investmentgesellschaften und Rohstofffonds: keine Unternehmen im Sinn des Katalogs
TABELLE_TAGE, TABELLE_DATEIEN, TABELLE_WERTPAPIERE = "ftd_tage", "ftd_dateien", "ftd_wertpapiere"

# Wörter, mit denen in der Bezeichnung die Angabe der Gattung beginnt
GATTUNG = {"COM", "COMMON", "SHS", "SH", "SHARES", "ORD", "ORDINARY", "CL", "CLASS", "ADR", "ADS", "SPONSORED", "SPON",
           "SPONS", "UNIT", "UNITS", "WT", "WTS", "PFD", "PREF", "STK", "STOCK", "NT", "NTS", "DEB", "RT", "RTS", "ETN",
           "ETF"}
# nur zusammen mit dem Folgewort eine Gattungsangabe: CAP STK, DEP SHS
GATTUNG_PAAR = {"CAP": {"STK", "STOCK"}, "DEP": {"SHS", "SH", "RCPT", "RCPTS"}}
# übliche Kürzungen der Quelle (Bezeichnung höchstens 30 Zeichen) -> Schreibweise der EDGAR-Namen
KURZFORM = {"HLDGS": "HOLDINGS", "HLDG": "HOLDING", "INTL": "INTERNATIONAL", "FINL": "FINANCIAL", "GRP": "GROUP",
            "PPTYS": "PROPERTIES", "SVCS": "SERVICES", "SYS": "SYSTEMS", "LABS": "LABORATORIES", "RES": "RESOURCES",
            "ENTMT": "ENTERTAINMENT", "MGMT": "MANAGEMENT", "INDS": "INDUSTRIES", "PRODS": "PRODUCTS",
            "NATL": "NATIONAL", "AMER": "AMERICAN", "BK": "BANK", "MACHS": "MACHINES", "TECHS": "TECHNOLOGIES",
            "COS": "COMPANIES", "MATLS": "MATERIALS", "ELEC": "ELECTRIC", "RLTY": "REALTY", "INVT": "INVESTMENT",
            "INVTS": "INVESTMENTS", "MTG": "MORTGAGE", "CTLS": "CONTROLS", "PETE": "PETROLEUM", "MLS": "MILLS",
            "INS": "INSURANCE", "RY": "RAILWAY", "TR": "TRUST", "FD": "FUND", "WTR": "WATER", "PWR": "POWER"}
# Gattungen, die keine Stammaktie (oder ihr Hinterlegungsschein) sind
KEIN_STAMM = {"PFD", "PREF", "PREFERRED", "WT", "WTS", "WS", "W", "WARRANT", "WARRANTS", "UNIT", "UNITS", "UT", "RT",
              "RTS", "RIGHT", "RIGHTS", "NT", "NTS", "NOTE", "NOTES", "DEB", "DEBS", "BD", "BDS", "ETN", "ETF", "FDG",
              "TR", "TRUST", "FD", "FUND", "PERP", "CONV", "CV", "LKD", "IDX", "INDEX"}
WORT = re.compile(r"[^A-Z0-9& ]+")

registriere(Parameter(
    id="IH3-06", name="Lieferausfälle (Reg SHO)",
    definition="Bestand nicht gelieferter Stücke der Firma am Abwicklungstag (Fails-to-Deliver im Clearing der NSCC), "
               f"summiert über ihre Stammaktiengattungen mit jeweils mindestens {SCHWELLE:,} Stück".replace(",", "."),
    einheit="Stück", frequenz="je Abwicklungstag mit Bestand ab Schwelle; Veröffentlichung je Monatshälfte",
    offenlegung="amtlich offen: SEC Fails-to-Deliver Data (Regulation SHO)",
    quelle=SEITE, lizenz="gemeinfrei (US-Behörde)", historie_ab="03/2004",
    verzoegerung="Veröffentlichungstag der Datei, üblich 14–19 Tage nach Ende der Monatshälfte; ist er unbekannt, "
                 f"{VERZUG_HALBMONAT} Tage (Quartalsdateien bis 2009: {VERZUG_QUARTAL} Tage) nach Periodenende",
    schwaechen="Die Threshold-Liste verlangt zusätzlich 0,5 % der ausstehenden Aktien an fünf Abwicklungstagen in Folge; "
               "das Verhältnis (mit UA3-01) und die Dauer entstehen privat. Zuordnung über Kürzel, CUSIP und "
               "Bezeichnung (Trefferquote im Prüfbericht); die heutige Zuordnung gilt rückwirkend. Der Bestand ist "
               "kumuliert, kein Tageszugang. Als Signal ungeprüft"))


# --------------------------------------------------------------------------- Dateien und Zeitbezug
def links_aus_seite(html: str) -> dict[str, str]:
    """Schlüssel der Datei (``202610a`` oder ``2006q4``) -> Adresse; je Schlüssel der erste Link."""
    aus: dict[str, str] = {}
    for href, halbmonat, quartal in LINK_MUSTER.findall(html):
        schluessel = (halbmonat or quartal).lower()
        aus.setdefault(schluessel, href if href.startswith("http") else "https://www.sec.gov" + href)
    return aus


def periode(schluessel: str) -> tuple[date, bool]:
    """(Periodenende, Quartalsdatei?) zu einem Dateischlüssel."""
    m = re.fullmatch(r"(\d{4})(\d{2})([ab])", schluessel)
    if m:
        jahr, monat = int(m.group(1)), int(m.group(2))
        if m.group(3) == "a":
            return date(jahr, monat, 15), False
        return date(jahr + (monat == 12), monat % 12 + 1, 1) - timedelta(days=1), False
    m = re.fullmatch(r"(\d{4})q([1-4])", schluessel)
    if not m:
        raise ValueError(f"unbekannter Dateischlüssel: {schluessel}")
    jahr, monat = int(m.group(1)), int(m.group(2)) * 3
    return date(jahr + (monat == 12), monat % 12 + 1, 1) - timedelta(days=1), True


def veroeffentlicht_am(schluessel: str, geaendert: datetime | None) -> datetime:
    """Zeitpunkt (UTC), ab dem die Datei als öffentlich gilt.

    Der Änderungszeitpunkt der Datei zählt, wenn er bis zu ``FENSTER_TAGE`` nach dem Periodenende liegt
    (dann ist er die Erstveröffentlichung oder später, nie früher). Sonst gilt die feste Frist.
    """
    ende, quartal = periode(schluessel)
    if geaendert is not None and ende < geaendert.astimezone(ET).date() <= ende + timedelta(days=FENSTER_TAGE):
        return geaendert.astimezone(UTC)
    regel = ende + timedelta(days=VERZUG_QUARTAL if quartal else VERZUG_HALBMONAT)
    return datetime.combine(regel, EROEFFNUNG, tzinfo=ET).astimezone(UTC)


def lies_archiv(zip_pfad: Path) -> tuple[pd.DataFrame, int]:
    """Zeilen eines Archivs (tag, cusip, symbol, stueck, beschreibung) und die Abweichung zur Satzzahl im Nachsatz."""
    teile, abweichung = [], 0
    with zipfile.ZipFile(zip_pfad) as archiv:
        namen = [n for n in archiv.namelist() if n.lower().endswith(".txt")]
        if not namen:
            raise KeyError(f"keine Textdatei im Archiv {Path(zip_pfad).name} (enthalten: {archiv.namelist()})")
        for name in namen:
            with archiv.open(name) as f:
                roh = pd.read_csv(f, sep="|", dtype=str, encoding="latin-1", quoting=csv.QUOTE_NONE,
                                  on_bad_lines="skip", keep_default_na=False)
            roh.columns = [str(c).strip().upper() for c in roh.columns]
            fehlend = [s for s in SPALTEN if s not in roh.columns]
            if fehlend:
                raise KeyError(f"Pflichtspalten fehlen {fehlend} (vorhanden: {list(roh.columns)})")
            nachsatz = roh["SETTLEMENT DATE"].str.extract(r"Trailer record count\s+(\d+)", expand=False).dropna()
            df = roh[list(SPALTEN)].rename(columns=SPALTEN)
            df["tag"] = pd.to_datetime(df["tag"].str.strip(), format="%Y%m%d", errors="coerce")
            df = df[df["tag"].notna()]
            if len(nachsatz):
                abweichung += abs(len(df) - int(nachsatz.iloc[-1]))
            df["stueck"] = pd.to_numeric(df["stueck"], errors="coerce")
            df["cusip"] = df["cusip"].astype(str).str.strip().str.upper()
            df = df[df["stueck"].notna() & (df["stueck"] > 0) & (df["cusip"].str.len() >= 8)]
            for s in ("symbol", "beschreibung"):
                df[s] = df[s].astype(str).str.strip().str.upper()
            teile.append(df)
    aus = pd.concat(teile, ignore_index=True) if teile else pd.DataFrame(columns=list(SPALTEN.values()))
    return aus, abweichung


def _verdichte(df: pd.DataFrame, schluessel: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tageswerte je CUSIP und die Stammzeile je CUSIP (jüngstes Kürzel, jüngste Bezeichnung)."""
    tage = df.groupby(["tag", "cusip"], as_index=False)["stueck"].sum()
    tage["stueck"] = tage["stueck"].round().astype("int64")
    tage["datei"] = schluessel
    d = df.sort_values("tag", kind="stable").assign(symbol=lambda x: x["symbol"].where(x["symbol"] != ""),
                                                    beschreibung=lambda x: x["beschreibung"].where(x["beschreibung"] != ""))
    wp = d.groupby("cusip").agg(symbol=("symbol", "last"), beschreibung=("beschreibung", "last"),
                                erster_tag=("tag", "min"), letzter_tag=("tag", "max")).reset_index()
    return tage, wp


def vereinige_wertpapiere(teile: list[pd.DataFrame]) -> pd.DataFrame:
    teile = [t[["cusip", "symbol", "beschreibung", "erster_tag", "letzter_tag"]] for t in teile if len(t)]
    if not teile:
        return pd.DataFrame(columns=["cusip", "symbol", "beschreibung", "erster_tag", "letzter_tag"])
    z = pd.concat(teile, ignore_index=True).sort_values("letzter_tag", kind="stable")
    return z.groupby("cusip").agg(symbol=("symbol", "last"), beschreibung=("beschreibung", "last"),
                                  erster_tag=("erster_tag", "min"), letzter_tag=("letzter_tag", "max")).reset_index()


# --------------------------------------------------------------------------- Zuordnung CUSIP -> CIK
def teile_bezeichnung(text: str | None) -> tuple[str, str]:
    """Trennt die Bezeichnung in Firmenname und Gattung: ``APPLE INC COM`` -> (``APPLE INC``, ``COM``)."""
    if not isinstance(text, str):
        return "", ""
    w = WORT.sub(" ", text.upper()).split()
    schnitt = len(w)
    for i in range(1, len(w)):
        letztes = i == len(w) - 1
        if (w[i] in GATTUNG or (w[i] == "DEL" and w[i - 1] in RECHTSFORM) or (letztes and w[i] in ("NEW", "W"))
                or (not letztes and w[i + 1] in GATTUNG_PAAR.get(w[i], ()))):
            schnitt = i
            break
    return " ".join(KURZFORM.get(x, x) for x in w[:schnitt]), " ".join(w[schnitt:])


def _kuerzel(text) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper()) if isinstance(text, str) else ""


def ordne_zu(wertpapiere: pd.DataFrame, firmen: pd.DataFrame) -> pd.DataFrame:
    """Ergänzt je CUSIP: cik, konfidenz, art (kuerzel_name, kuerzel, exakt, frueher, kern, ...) und stamm."""
    firmen = firmen[firmen["sic"].notna() & ~firmen["sic"].astype(str).isin(FONDS_SIC)]
    abgleich = Namensabgleich(firmen)
    nach_kuerzel: dict[str, set[int]] = {}
    anfang: dict[int, set[str]] = {}
    for z in firmen.itertuples(index=False):
        cik = int(z.cik)
        for t in (z.tickers.split(",") if isinstance(z.tickers, str) else ()):
            if _kuerzel(t):
                nach_kuerzel.setdefault(_kuerzel(t), set()).add(cik)
        namen = [z.name]
        if isinstance(z.fruehere_namen, str) and z.fruehere_namen not in ("", "[]"):
            try:
                namen += [a.get("name") if isinstance(a, dict) else a for a in json.loads(z.fruehere_namen)]
            except ValueError:
                pass
        anfang[cik] = {bereinige(n).split()[0] for n in namen if bereinige(n)}
    grenze = wertpapiere["letzter_tag"].max() - pd.Timedelta(days=AKTIV_TAGE) if len(wertpapiere) else None
    namens_treffer: dict[str, tuple] = {}
    zeilen = []
    for z in wertpapiere.itertuples(index=False):
        name, gattung = teile_bezeichnung(z.beschreibung)
        stamm = not (set(gattung.split()) & KEIN_STAMM)
        cik, konfidenz, art = None, 0.0, "keiner"
        kandidaten = nach_kuerzel.get(_kuerzel(z.symbol), ())
        if len(kandidaten) == 1:
            c = next(iter(kandidaten))
            erstes = bereinige(name).split()[:1]
            if erstes and erstes[0] in anfang.get(c, ()):
                cik, konfidenz, art = c, 0.98, "kuerzel_name"
            elif z.letzter_tag >= grenze:
                cik, konfidenz, art = c, 0.93, "kuerzel"
        if cik is None and name and stamm:
            if name not in namens_treffer:
                namens_treffer[name] = abgleich.finde(name)
            cik, konfidenz, art = namens_treffer[name]
            if konfidenz < MINDEST_KONFIDENZ:
                cik = None
        zeilen.append((cik, konfidenz, art, stamm))
    aus = wertpapiere.reset_index(drop=True).copy()
    z = pd.DataFrame(zeilen, columns=["cik", "konfidenz", "art", "stamm"])
    aus["cik"] = z["cik"].astype("Int64") if len(z) else pd.Series(dtype="Int64")
    aus["konfidenz"], aus["art"], aus["stamm"] = z["konfidenz"].astype("float64"), z["art"], z["stamm"].astype(bool)
    return aus


# --------------------------------------------------------------------------- Parameter
def baue_parameter(ablage: Ablage, zuordnung: pd.DataFrame, dateien: pd.DataFrame) -> pd.DataFrame:
    z = zuordnung[zuordnung["cik"].notna() & zuordnung["stamm"] & (zuordnung["konfidenz"] >= MINDEST_KONFIDENZ)]
    z = z[["cusip", "cik"]].astype({"cik": "int64"})
    teile = []
    for pfad in sorted(ablage.bereinigt.glob(f"bereinigt__{TABELLE_TAGE}__*.parquet")):
        t = pq.read_table(pfad, columns=["tag", "cusip", "stueck", "datei"], filters=[("stueck", ">=", SCHWELLE)]).to_pandas()
        if t.empty or z.empty:
            continue
        t["cusip"], t["datei"] = t["cusip"].astype(str), t["datei"].astype(str)
        t = t.merge(z, on="cusip", how="inner")
        teile.append(t.groupby(["cik", "tag", "datei"], as_index=False)["stueck"].sum())
    if not teile:
        return leer()
    g = pd.concat(teile, ignore_index=True)
    d = dateien[["datei", "veroeffentlicht"]].copy()
    d["verfuegbar_ab"] = handelbar_ab_serie(d["veroeffentlicht"])
    g = g.merge(d[["datei", "verfuegbar_ab"]], on="datei", how="inner")
    if g.empty:
        return leer()
    ereignis = (pd.to_datetime(g["tag"]) + pd.Timedelta(hours=18)).dt.tz_localize(ET).dt.tz_convert("UTC")
    return als_parameter(pd.DataFrame({
        "cik": g["cik"].to_numpy(), "parameter_id": "IH3-06", "ereignis_zeit": ereignis.values,
        "verfuegbar_ab": g["verfuegbar_ab"].values, "wert": g["stueck"].to_numpy(dtype="float64"),
        "stand": g["datei"].to_numpy()}))


# --------------------------------------------------------------------------- Lauf
def _lade(abruf: Abruf, url: str, ziel: Path) -> datetime | None:
    """Lädt ein Archiv und gibt seinen Änderungszeitpunkt zurück (Kopfzeile Last-Modified)."""
    antwort = abruf.hole(url, stream=True)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with open(ziel, "wb") as f:
        for block in antwort.iter_content(chunk_size=1 << 20):
            if block:
                f.write(block)
    kopf = antwort.headers.get("Last-Modified", "")
    antwort.close()
    try:
        zeit = parsedate_to_datetime(kopf) if kopf else None
    except (TypeError, ValueError):
        zeit = None
    return zeit.astimezone(UTC) if zeit is not None and zeit.tzinfo is not None else None


def _schreibe_jahr(ablage: Ablage, jahr: int, neu: list[pd.DataFrame], ersetzt: set[str]) -> None:
    pfad = ablage.bereinigt / f"bereinigt__{TABELLE_TAGE}__{jahr}.parquet"
    if pfad.exists():
        alt = pd.read_parquet(pfad)
        alt["cusip"], alt["datei"] = alt["cusip"].astype(str), alt["datei"].astype(str)
        neu = neu + [alt[~alt["datei"].isin(ersetzt)]]
    alle = pd.concat(neu, ignore_index=True).sort_values(["tag", "cusip"], kind="stable").reset_index(drop=True)
    alle["cusip"], alle["datei"] = alle["cusip"].astype("category"), alle["datei"].astype("category")
    ablage.schreibe_bereinigt(TABELLE_TAGE, str(jahr), alle)


def lauf(ablage: Ablage, arbeits: Path, modus: str = "laufend", abruf: Abruf | None = None, lokal: Path | None = None,
         budget: Zeitbudget | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    """``lokal``: Ordner mit Archiven (``cnsfails202401a.zip``) statt Abruf; dann gilt immer die feste Frist."""
    hinweise: list[str] = []
    firmen = ablage.lies_bereinigt("edgar_firmen")
    if firmen.empty:
        raise RuntimeError("Firmentabelle fehlt (Quelle edgar_index zuerst ausführen)")
    if lokal is not None:
        quellen = links_aus_seite(" ".join(f'href="/{p.name}"' for p in sorted(Path(lokal).glob("*.zip"))))
        quellen = {k: str(Path(lokal) / Path(v).name) for k, v in quellen.items()}
    else:
        abruf = abruf or Abruf()
        quellen = links_aus_seite(abruf.hole(SEITE).text)
    if not quellen:
        raise RuntimeError("Datenseite nennt keine Dateien (Aufbau geändert?)")
    budget = budget or Zeitbudget()
    dateien = ablage.lies_bereinigt(TABELLE_DATEIEN)
    if dateien.empty:
        dateien = pd.DataFrame({"datei": pd.Series(dtype=str), "veroeffentlicht": pd.Series(dtype="datetime64[us, UTC]")})
    bestand = ablage.lies_bereinigt(TABELLE_WERTPAPIERE)
    reihenfolge = sorted(quellen, key=lambda k: periode(k)[0], reverse=True)       # neueste zuerst
    offen = [k for i, k in enumerate(reihenfolge) if i < NEU_LADEN or k not in set(dateien["datei"])]
    erst = dateien.set_index("datei")["veroeffentlicht"].to_dict()
    neue_zeilen, je_jahr, stamm_neu, abweichung, zeilen_neu, abgebrochen = [], {}, [], 0, 0, False

    def schliesse(jahr: int) -> None:
        teile = je_jahr.pop(jahr)
        _schreibe_jahr(ablage, jahr, [t for _, t in teile], {k for k, _ in teile})

    for schluessel in offen:
        if budget.abgelaufen():
            abgebrochen = True
            break
        if lokal is not None:
            pfad, geaendert = Path(quellen[schluessel]), None
        else:
            pfad = Path(arbeits) / "ftd" / f"{schluessel}.zip"
            geaendert = _lade(abruf, quellen[schluessel], pfad)
        df, abw = lies_archiv(pfad)
        if lokal is None:
            pfad.unlink(missing_ok=True)
        tage, wp = _verdichte(df, schluessel)
        jahr = int(schluessel[:4])
        for offenes_jahr in [j for j in je_jahr if j != jahr]:
            schliesse(offenes_jahr)
        je_jahr.setdefault(jahr, []).append((schluessel, tage))
        stamm_neu.append(wp)
        abweichung += abw
        zeilen_neu += len(tage)
        # der zuerst festgestellte Veröffentlichungszeitpunkt bleibt (stabile Stichtage)
        veroeffentlicht = erst.get(schluessel)
        if veroeffentlicht is None or pd.isna(veroeffentlicht):
            veroeffentlicht = veroeffentlicht_am(schluessel, geaendert)
        neue_zeilen.append({"datei": schluessel, "periodenende": pd.Timestamp(periode(schluessel)[0]),
                            "geaendert": geaendert, "veroeffentlicht": veroeffentlicht, "zeilen": len(tage)})
    for offenes_jahr in list(je_jahr):
        schliesse(offenes_jahr)

    if neue_zeilen:
        neu = pd.DataFrame(neue_zeilen)
        alt = dateien[~dateien["datei"].isin(set(neu["datei"]))]
        dateien = pd.concat([alt, neu], ignore_index=True) if len(alt) else neu
    if dateien.empty:
        raise RuntimeError("keine Datei gelesen")
    for s in ("geaendert", "veroeffentlicht"):
        dateien[s] = pd.to_datetime(dateien[s], utc=True).astype("datetime64[us, UTC]")
    dateien["periodenende"] = pd.to_datetime(dateien["periodenende"])
    dateien["zeilen"] = dateien["zeilen"].astype("int64")
    dateien = dateien.sort_values("periodenende", kind="stable").reset_index(drop=True)
    ablage.schreibe_bereinigt(TABELLE_DATEIEN, "alle", dateien)

    wertpapiere = vereinige_wertpapiere(([bestand] if len(bestand) else []) + stamm_neu)
    zuordnung = ordne_zu(wertpapiere, firmen)
    ablage.schreibe_bereinigt(TABELLE_WERTPAPIERE, "alle", zuordnung)
    parameter = baue_parameter(ablage, zuordnung, dateien)
    ablage.schreibe_parameter("sec_ftd", parameter)

    rest = len([k for k in quellen if k not in set(dateien["datei"])])
    if abgebrochen and modus == "rueckwaerts":
        merke_fortsetzung(ablage.wurzel, "sec_ftd")
    if rest:
        hinweise.append(f"{rest} Dateien noch nicht gelesen (Zeitbudget; der nächste Lauf setzt fort)")
    aktiv = zuordnung[zuordnung["stamm"] & (zuordnung["letzter_tag"] >= zuordnung["letzter_tag"].max()
                                            - pd.Timedelta(days=AKTIV_TAGE))] if len(zuordnung) else zuordnung
    quote = trefferquote(aktiv) if len(aktiv) else {"zeilen": 0, "quote": 0.0, "arten": {}}
    frist = pd.to_datetime([veroeffentlicht_am(k, None) for k in dateien["datei"]], utc=True)
    geschaetzt = int((dateien["veroeffentlicht"].dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[us]").to_numpy()
                      == frist.tz_localize(None).astype("datetime64[us]").to_numpy()).sum())
    hinweise.append(f"Zuordnung: {quote['quote']:.1%} der im letzten Jahr aktiven Stammaktien-CUSIP einer Firma zugeordnet")
    hinweise.append(f"Veröffentlichungstag aus der Datei bei {len(dateien) - geschaetzt} Dateien, feste Frist bei {geschaetzt}")
    info = {"dateien_verzeichnis": len(quellen), "dateien_gelesen": int(len(dateien)), "dateien_neu": len(neue_zeilen),
            "zeilen_neu": int(zeilen_neu), "nachsatz_abweichung": int(abweichung), "wertpapiere": int(len(zuordnung)),
            "zugeordnet": int(zuordnung["cik"].notna().sum()) if len(zuordnung) else 0,
            "juengste_datei": reihenfolge[0], "trefferquote": quote}
    return parameter, info, hinweise
