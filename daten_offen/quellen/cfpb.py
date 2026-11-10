"""Verbraucherbeschwerden über Finanzfirmen aus der amtlichen Beschwerdedatenbank des CFPB.

Die Datenbank nennt Firmennamen, keine Firmenschlüssel; die Zuordnung zur CIK läuft über den
Namensabgleich. Übernommen werden nur Zuordnungen mit Konfidenz ab 0,90; die Trefferquote steht
im Prüfbericht. Als Signal ist die Größe ungeprüft (Katalog: „übernehmen, messen“).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.namen import Namensabgleich, trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab_serie

DATEN_URL = "https://files.consumerfinance.gov/ccdb/complaints.csv.zip"
SPALTE_DATUM, SPALTE_FIRMA = "Date received", "Company"
MINDEST_KONFIDENZ = 0.90
VERZUG_TAGE = 30   # Beschwerden erscheinen nach der Antwort der Firma, spätestens nach 15 Tagen; großzügig gerechnet

registriere(Parameter(
    id="GA3-01", name="Verbraucherbeschwerden",
    definition="Zahl der beim CFPB eingegangenen Beschwerden über die Firma je Kalendermonat",
    einheit="Anzahl", frequenz="monatlich",
    offenlegung="amtlich offen: CFPB Consumer Complaint Database (Dodd-Frank Act)",
    quelle="https://www.consumerfinance.gov/data-research/consumer-complaints/", lizenz="gemeinfrei (US-Behörde)",
    historie_ab="12/2011", verzoegerung=f"{VERZUG_TAGE} Tage nach Monatsende",
    schwaechen="Nur Finanzfirmen; Zuordnung über Firmennamen (Trefferquote im Prüfbericht); Tochterfirmen mit "
               "eigenem Namen werden der Mutter nicht zugerechnet; als Signal ungeprüft"))


def zaehle_je_monat(zip_pfad: Path, blockgroesse: int = 500_000) -> pd.DataFrame:
    """Beschwerden je Firmenname und Eingangsmonat; der letzte, unvollständige Monat entfällt."""
    teile = []
    with zipfile.ZipFile(zip_pfad) as archiv:
        namen = [n for n in archiv.namelist() if n.lower().endswith(".csv")]
        if not namen:
            raise KeyError(f"keine CSV-Datei im Archiv (enthalten: {archiv.namelist()})")
        with archiv.open(namen[0]) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
            kopf = pd.read_csv(text, nrows=0).columns.tolist()
        fehlend = [s for s in (SPALTE_DATUM, SPALTE_FIRMA) if s not in kopf]
        if fehlend:
            raise KeyError(f"Pflichtspalten fehlen {fehlend} (vorhanden: {kopf})")
        with archiv.open(namen[0]) as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
            for block in pd.read_csv(text, usecols=[SPALTE_DATUM, SPALTE_FIRMA], dtype=str, chunksize=blockgroesse):
                tag = pd.to_datetime(block[SPALTE_DATUM], format="%Y-%m-%d", errors="coerce")
                tag = tag.fillna(pd.to_datetime(block[SPALTE_DATUM].where(tag.isna()), format="%m/%d/%Y", errors="coerce"))
                block = block.assign(monat=tag.dt.to_period("M"))
                block = block[block["monat"].notna() & block[SPALTE_FIRMA].notna()]
                teile.append(block.groupby([SPALTE_FIRMA, "monat"]).size())
    if not teile:
        return pd.DataFrame(columns=["firma", "monat", "anzahl"])
    z = pd.concat(teile).groupby(level=[0, 1]).sum().rename("anzahl").reset_index()
    z.columns = ["firma", "monat", "anzahl"]
    return z[z["monat"] < z["monat"].max()].reset_index(drop=True)


def baue_parameter(zaehlung: pd.DataFrame, firmen: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Parameter, Trefferquote und die Zuordnungstabelle (Firmenname -> CIK)."""
    if zaehlung.empty:
        return leer(), {"zeilen": 0, "quote": 0.0}, pd.DataFrame()
    je_name = zaehlung.groupby("firma")["anzahl"].sum().reset_index()
    zuordnung = Namensabgleich(firmen).ordne_zu(je_name["firma"])
    zuordnung.loc[zuordnung["konfidenz"] < MINDEST_KONFIDENZ, "cik"] = pd.NA
    quote = trefferquote(zuordnung, gewicht=je_name["anzahl"].astype("float64"))
    tabelle = pd.concat([je_name, zuordnung], axis=1)
    z = zaehlung.merge(tabelle[["firma", "cik"]], on="firma", how="inner")
    z = z[z["cik"].notna()]
    if z.empty:
        return leer(), quote, tabelle
    z = z.groupby(["cik", "monat"], as_index=False)["anzahl"].sum()
    ende = z["monat"].dt.end_time.dt.floor("s").dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    bekannt = handelbar_ab_serie(ende + pd.Timedelta(days=VERZUG_TAGE))
    parameter = als_parameter(pd.DataFrame({
        "cik": z["cik"].astype("int64").to_numpy(), "parameter_id": "GA3-01", "ereignis_zeit": ende.values,
        "verfuegbar_ab": bekannt.values, "wert": z["anzahl"].to_numpy(dtype="float64"), "stand": z["monat"].astype(str).to_numpy()}))
    return parameter, quote, tabelle


def lauf(ablage: Ablage, arbeits: Path, zip_pfad: Path | None = None,
         abruf: Abruf | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    firmen = ablage.lies_bereinigt("edgar_firmen")
    if firmen.empty:
        raise RuntimeError("Firmentabelle fehlt (Quelle edgar_index zuerst ausführen)")
    # nur Unternehmen: Einträge mit Branchenschlüssel oder Ticker (keine Privatpersonen)
    firmen = firmen[firmen["sic"].notna() | firmen["tickers"].notna()]
    if zip_pfad is None:
        abruf = abruf or Abruf(anfragen_pro_sekunde=2)
        zip_pfad = abruf.hole_datei(DATEN_URL, Path(arbeits) / "complaints.csv.zip")
    zaehlung = zaehle_je_monat(Path(zip_pfad))
    parameter, quote, tabelle = baue_parameter(zaehlung, firmen)
    if len(tabelle):
        ablage.schreibe_bereinigt("cfpb_zuordnung", "alle", tabelle.assign(cik=tabelle["cik"].astype("Int64")))
    ablage.schreibe_parameter("cfpb", parameter)
    hinweise = [f"Namensabgleich: {quote.get('quote', 0):.1%} der Firmennamen, "
                f"{quote.get('quote_gewichtet', 0):.1%} der Beschwerden zugeordnet"]
    info = {"firmennamen": int(zaehlung["firma"].nunique()) if len(zaehlung) else 0, "beschwerden": int(zaehlung["anzahl"].sum()) if len(zaehlung) else 0,
            "trefferquote": quote}
    return parameter, info, hinweise
