"""Bundesaufträge je Firma aus dem Award Data Archive von USAspending (Vertragsdaten aus FPDS, ab Haushaltsjahr 2008).

Je Haushaltsjahr (Oktober bis September) gibt es eine Sammeldatei aller Vertragstransaktionen; USAspending erneuert
sie monatlich. Gelesen werden nur wenige der rund 300 Spalten. Verdichtet wird je Konzernfamilie (UEI der obersten
Mutter, wie zur Transaktion gemeldet), gemeldetem Mutternamen und Monat des Bekanntwerdens:

  usaspending_monat__fy<jahr>     familie, mutter, roh, monat, betrag, zeilen   (eine Datei je Haushaltsjahr)
  usaspending_zuordnung__alle     familie, mutter, roh -> cik, konfidenz, art
  usaspending_dateien__alle       gelesene Sammeldateien mit Stand

Bekannt ist eine Transaktion zwei Tage nach dem ersten Meldetag in FPDS, frühestens zwei Tage nach dem Auftragsdatum.
Aufträge des Verteidigungsministeriums gibt FPDS erst 90 Tage nach dem Auftragsdatum frei.

Die Zuordnung zur CIK läuft über Namen. Die Mutter-UEI bündelt die Familie verlässlich, ihr heutiger Name in der
Quelle ist aber vereinzelt falsch (eine Familie trägt dann den Namen einer zugekauften Firma). Er gilt deshalb nur,
wenn ein zur Transaktion gemeldeter Name der Familie ihn stützt; sonst zählt der gemeldete Name der Zeile.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.namen import Namensabgleich, bereinige, kern, trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab
from ..kern.zustand import Zeitbudget, merke_fortsetzung

SEITE = "https://www.usaspending.gov/download_center/award_data_archive"
VERZEICHNIS_URL = "https://api.usaspending.gov/api/v2/bulk_download/list_monthly_files/"
DATEI_MUSTER = re.compile(r"FY(\d{4})_All_Contracts_Full_(\d{8})\.zip$", re.I)
AB_HAUSHALTSJAHR = 2008
NEU_LADEN = 2                  # die jüngsten Haushaltsjahre werden bei neuem Stand neu gelesen (späte Meldungen, Sperre)
DOD = "097"                    # Behördenschlüssel des Verteidigungsministeriums (mit dem Pionierkorps der Armee)
SPERRE_DOD_TAGE = 90
VERZUG_TAGE = 2                # FPDS -> USAspending: nächtliche Übernahme
OHNE_MELDETAG_TAGE = 30        # ältere Jahre nennen den ersten Meldetag nicht immer
VERZUG_MONAT_TAGE = 15         # die Sammeldatei mit dem abgeschlossenen Monat erscheint am 6. bis 9. des Folgemonats
MINDEST_KONFIDENZ = 0.90
MINDEST_STUETZE = 0.5          # Anteil der Monate oder des Volumens einer Familie, den gemeldete Namen stützen müssen
MINDEST_STUETZE_MUTTER = 0.25  # dasselbe für die Firma, die der heutige Name der Mutter-UEI nennt
TABELLE_MONAT, TABELLE_ZUORDNUNG, TABELLE_DATEIEN = "usaspending_monat", "usaspending_zuordnung", "usaspending_dateien"
SPALTEN = ["federal_action_obligation", "action_date", "awarding_agency_code", "recipient_uei", "recipient_name",
           "recipient_name_raw", "recipient_parent_uei", "recipient_parent_name", "recipient_parent_name_raw",
           "initial_report_date"]
SCHLUESSEL = ["familie", "mutter", "roh"]
# Töchter, die den Namen einer börsennotierten Mutter tragen, deren Familie in der Quelle aber nicht zu ihr führt.
# Bewusst kurz und von Hand geprüft: Ein freier Abgleich über den Namensanfang ordnete im Versuch zu viel falsch zu.
MARKEN = {("HUMANA",): 49071, ("TEXTRON",): 217346, ("STONEX",): 913760, ("CGI", "FEDERAL"): 1061574}
# Bereinigte Namen, die bei EDGAR zwei Firmen ohne Börsenkürzel tragen: von Hand entschieden.
# RAYTHEON CO/ (1047122) war bis 04/2020 die börsennotierte Raytheon, RAYTHEON CO (82267) ihr Vorgänger bis 1997.
GLEICHNAMIG = {"RAYTHEON": 1047122}
LEERRAUM = re.compile(r"\s+")

registriere(Parameter(
    id="PR2-01", name="Vergabevolumen je Firma",
    definition="Summe der im Monat bekannt gewordenen Verpflichtungen des Bundes aus Verträgen mit der Firma und ihren "
               "Töchtern (federal_action_obligation aller Vertragstransaktionen, Rücknahmen negativ). Monate ohne Zeile "
               "zählen null; das Verhältnis zum Umsatz (Katalog: 12 Monate / Umsatz) bildet der Nutzer",
    einheit="US-Dollar", frequenz="monatlich",
    offenlegung="gesetzlich: FFATA 2006 und DATA Act 2014; Vertragsmeldung an FPDS binnen 3 Werktagen (FAR 4.604)",
    quelle=SEITE, lizenz="gemeinfrei (US-Behörde)", historie_ab="10/2007",
    verzoegerung=f"{VERZUG_MONAT_TAGE} Tage nach Monatsende; Verteidigungsaufträge zählen erst {SPERRE_DOD_TAGE} Tage "
                 "nach dem Auftragsdatum",
    schwaechen="Zuordnung über Firmennamen und die gemeldete Konzernfamilie (Trefferquote im Prüfbericht); Töchter mit "
               "eigenem Namen außerhalb der gemeldeten Familie fehlen; die Quelle zeigt den heutigen Stand jeder "
               "Transaktion (spätere Korrekturen fließen in alte Monate ein); nur Hauptauftragnehmer, keine "
               "Unteraufträge; Rahmenverträge zählen erst mit den Abrufen; als Signal ungeprüft"))


# --------------------------------------------------------------------------- Dateien und Zeitbezug
def haushaltsjahr(tag: date) -> int:
    """Haushaltsjahr des Bundes: Oktober bis September, benannt nach dem Jahr, in dem es endet."""
    return tag.year + (tag.month >= 10)


def datei_schluessel(name: str) -> tuple[int, date] | None:
    """(Haushaltsjahr, Stand) aus einem Dateinamen wie ``FY2026_All_Contracts_Full_20261106.zip``."""
    m = DATEI_MUSTER.search(str(name))
    if not m:
        return None
    return int(m.group(1)), datetime.strptime(m.group(2), "%Y%m%d").date()


def verzeichnis(abruf: Abruf, bis_jahr: int, ab_jahr: int = AB_HAUSHALTSJAHR) -> dict[int, tuple[str, date]]:
    """Adresse und Stand der Sammeldatei je Haushaltsjahr (eine Abfrage je Jahr)."""
    aus: dict[int, tuple[str, date]] = {}
    for jahr in range(ab_jahr, bis_jahr + 1):
        antwort = abruf.sende_json(VERZEICHNIS_URL, {"agency": "all", "fiscal_year": jahr, "type": "contracts"})
        for eintrag in antwort.get("monthly_files", []):
            schluessel = datei_schluessel(eintrag.get("file_name", ""))
            if schluessel and schluessel[0] == jahr and eintrag.get("url"):
                aus[jahr] = (eintrag["url"], schluessel[1])
    return aus


def bekannt_am(aktion: pd.Series, meldung: pd.Series, dod: pd.Series) -> pd.Series:
    """Tag, an dem eine Transaktion öffentlich bekannt war (siehe Modulbeschreibung)."""
    basis = meldung.where(meldung >= aktion, aktion)
    basis = basis.where(meldung.notna(), aktion + pd.Timedelta(days=OHNE_MELDETAG_TAGE))
    sperre = aktion + pd.Timedelta(days=SPERRE_DOD_TAGE)
    basis = basis.where(~(dod & (sperre > basis)), sperre)
    return basis + pd.Timedelta(days=VERZUG_TAGE)


def _name(s: pd.Series) -> pd.Series:
    return s.fillna("").str.upper().str.replace(LEERRAUM, " ", regex=True).str.strip()


def _verdichte(block: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    aktion = pd.to_datetime(block["action_date"].str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
    meldung = pd.to_datetime(block["initial_report_date"].str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
    dod = (block["awarding_agency_code"].str.strip() == DOD).fillna(False)
    gueltig = aktion.notna()
    info = {"zeilen": int(len(block)), "ohne_datum": int((~gueltig).sum()), "ohne_meldetag": int((gueltig & meldung.isna()).sum()),
            "zeilen_dod": int((gueltig & dod).sum()),
            "juengste_aktion_zivil": aktion[gueltig & ~dod].max(), "juengste_aktion_dod": aktion[gueltig & dod].max()}
    # erst über die Rohtexte verdichten, dann die Namen vereinheitlichen: spart den Großteil der Textarbeit
    texte = ["recipient_parent_uei", "recipient_uei", "recipient_parent_name", "recipient_parent_name_raw",
             "recipient_name", "recipient_name_raw"]
    t = block[texte].fillna("").assign(
        monat=bekannt_am(aktion, meldung, dod).dt.to_period("M").dt.to_timestamp(),
        betrag=pd.to_numeric(block["federal_action_obligation"], errors="coerce").fillna(0.0))[gueltig]
    t = t.groupby(texte + ["monat"], as_index=False).agg(betrag=("betrag", "sum"), zeilen=("betrag", "size"))
    mutter_uei = t["recipient_parent_uei"].str.strip().replace("", pd.NA)
    eigene_uei = t["recipient_uei"].str.strip().replace("", pd.NA)
    empfaenger, empfaenger_roh = _name(t["recipient_name"]), _name(t["recipient_name_raw"])
    mutter, roh = _name(t["recipient_parent_name"]), _name(t["recipient_parent_name_raw"])
    ohne_mutter = mutter_uei.isna()
    mutter = mutter.where(~(ohne_mutter | (mutter == "")), empfaenger)
    roh = roh.where(~(ohne_mutter | (roh == "")), empfaenger_roh.where(empfaenger_roh != "", empfaenger))
    t = t.assign(familie=mutter_uei.fillna(eigene_uei).fillna("NAME:" + roh), mutter=mutter, roh=roh)
    return t.groupby(SCHLUESSEL + ["monat"], as_index=False)[["betrag", "zeilen"]].sum(), info


def lies_archiv(zip_pfad: Path, blockgroesse: int = 200_000) -> tuple[pd.DataFrame, dict]:
    """Verdichtet eine Sammeldatei: je Familie, Mutternamen und Monat des Bekanntwerdens Betrag und Zeilenzahl."""
    teile: list[pd.DataFrame] = []
    info = {"zeilen": 0, "ohne_datum": 0, "ohne_meldetag": 0, "zeilen_dod": 0,
            "juengste_aktion_zivil": pd.NaT, "juengste_aktion_dod": pd.NaT}
    with zipfile.ZipFile(zip_pfad) as archiv:
        mitglieder = sorted(n for n in archiv.namelist() if n.lower().endswith(".csv"))
        if not mitglieder:
            raise KeyError(f"keine CSV-Datei im Archiv (enthalten: {archiv.namelist()})")
        for mitglied in mitglieder:
            with archiv.open(mitglied) as f:
                kopf = pd.read_csv(io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline=""), nrows=0).columns.tolist()
            fehlend = [s for s in SPALTEN if s not in kopf]
            if fehlend:
                raise KeyError(f"Pflichtspalten fehlen {fehlend} in {mitglied} ({len(kopf)} Spalten vorhanden)")
            with archiv.open(mitglied) as f:
                text = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
                for block in pd.read_csv(text, usecols=SPALTEN, dtype=str, chunksize=blockgroesse, on_bad_lines="skip"):
                    teil, i = _verdichte(block)
                    teile.append(teil)
                    for k in ("zeilen", "ohne_datum", "ohne_meldetag", "zeilen_dod"):
                        info[k] += i[k]
                    for k in ("juengste_aktion_zivil", "juengste_aktion_dod"):
                        if pd.notna(i[k]) and (pd.isna(info[k]) or i[k] > info[k]):
                            info[k] = i[k]
            if len(teile) > 20:                                # Zwischenverdichtung hält den Speicher klein
                teile = [pd.concat(teile, ignore_index=True).groupby(SCHLUESSEL + ["monat"], as_index=False)[["betrag", "zeilen"]].sum()]
    if not teile:
        return pd.DataFrame(columns=SCHLUESSEL + ["monat", "betrag", "zeilen"]), info
    gesamt = pd.concat(teile, ignore_index=True).groupby(SCHLUESSEL + ["monat"], as_index=False)[["betrag", "zeilen"]].sum()
    info["betrag"] = float(gesamt["betrag"].sum())
    for k in ("juengste_aktion_zivil", "juengste_aktion_dod"):
        info[k] = None if pd.isna(info[k]) else info[k].strftime("%Y-%m-%d")
    return gesamt.astype({"zeilen": "int64"}), info


# --------------------------------------------------------------------------- Zuordnung
def _anfang(name: str, woerter: int = 2) -> str:
    """Die ersten Wörter des Kernnamens (zum Vergleich von Mutter- und gemeldetem Namen)."""
    n = bereinige(name)
    return " ".join((kern(n) or n).split()[:woerter])


def _marke(name: str) -> int | None:
    w = bereinige(name).split()
    for n in (2, 1):
        if len(w) > n and tuple(w[:n]) in MARKEN:              # nur mit Zusatz: der bloße Name träfe schon exakt
            return MARKEN[tuple(w[:n])]
    return None


def finde_namen(gruppen: pd.DataFrame, firmen: pd.DataFrame) -> tuple[pd.DataFrame, set[int]]:
    """Namensabgleich je Kombination aus Familie, heutigem Mutternamen (m) und gemeldetem Namen (r).
    Rückgabe: Tabelle (ihr Index ist die Kennung der Kombination) und die CIK mit Börsenkürzel."""
    g = gruppen.assign(umfang=gruppen["umfang"] if "umfang" in gruppen.columns else gruppen["betrag"].abs())
    g = g.groupby(SCHLUESSEL, as_index=False)["umfang"].sum()
    abgleich = Namensabgleich(firmen)
    namen = pd.unique(pd.concat([g["mutter"], g["roh"]], ignore_index=True))
    treffer = {n: abgleich.finde(n, aehnlich=False) for n in namen}
    for n in namen:                                            # gleichnamige Firmen ohne Börsenkürzel, von Hand entschieden
        if treffer[n][2] == "mehrdeutig" and bereinige(n) in GLEICHNAMIG:
            treffer[n] = (GLEICHNAMIG[bereinige(n)], 0.95, "exakt")
    wort = {n: _anfang(n, 1) for n in namen}
    for spalte, kurz in (("mutter", "m"), ("roh", "r")):
        t = pd.DataFrame([treffer[n] for n in g[spalte]], columns=[f"cik_{kurz}", f"k_{kurz}", f"art_{kurz}"], index=g.index)
        t[f"cik_{kurz}"] = t[f"cik_{kurz}"].astype("Int64")
        t.loc[t[f"k_{kurz}"] < MINDEST_KONFIDENZ, f"cik_{kurz}"] = pd.NA
        g = pd.concat([g, t], axis=1)
        g[f"wort_{kurz}"] = g[spalte].map(wort)
    return g, abgleich.mit_ticker


def waehle(g: pd.DataFrame, belegung: pd.DataFrame, boerse: set[int]) -> pd.DataFrame:
    """CIK je Kombination. ``belegung``: Kennung der Kombination (``gid``) und Monat mit Transaktionen.

    1. Je Familie stehen die Firmen zur Wahl, die der heutige Muttername oder ein gemeldeter Name im Abgleich trifft.
       Eine Firma gilt für die ganze Familie, wenn gemeldete Namen sie stützen (gleiche Firma im Abgleich oder
       gleiches erstes Wort): in mindestens der Hälfte der Monate oder des Volumens der Familie, beim heutigen
       Mutternamen genügt ein Viertel. Unter mehreren gewinnt die mit Börsenkürzel, dann die besser gestützte.
       Art ``familie``, wenn der gemeldete Name der Zeile selbst abweicht.
    2. Ohne Familienfirma zählt der gemeldete Name der Zeile, danach die Namensanfänge aus ``MARKEN``.
    """
    spalten = ["familie", "cik", "wort", "k"]
    kand = pd.concat([
        g.loc[g["cik_m"].notna(), ["familie", "cik_m", "wort_m", "k_m"]].set_axis(spalten, axis=1).assign(aus_mutter=True),
        g.loc[g["cik_r"].notna(), ["familie", "cik_r", "wort_r", "k_r"]].set_axis(spalten, axis=1).assign(aus_mutter=False)],
        ignore_index=True)
    f_cik = pd.Series(pd.NA, index=g.index, dtype="Int64")
    f_k = pd.Series(0.0, index=g.index)
    if len(kand):
        zeilen = g[["familie", "cik_r", "wort_r"]].rename_axis("gid").reset_index()
        paare = kand[["familie", "cik", "wort"]].drop_duplicates().merge(zeilen, on="familie")
        paare = paare[(paare["cik_r"] == paare["cik"]).fillna(False) | ((paare["wort"] != "") & (paare["wort"] == paare["wort_r"]))]
        paare = paare[["familie", "cik", "gid"]].drop_duplicates()
        stuetze = paare.merge(belegung[["gid", "monat"]], on="gid")
        gestuetzt = stuetze.drop_duplicates(["familie", "cik", "monat"]).groupby(["familie", "cik"]).size().rename("gestuetzt")
        monate = belegung.merge(g[["familie"]].rename_axis("gid").reset_index(), on="gid").drop_duplicates(
            ["familie", "monat"]).groupby("familie").size().rename("monate")
        volumen = paare.assign(umfang=paare["gid"].map(g["umfang"])).groupby(["familie", "cik"])["umfang"].sum().rename("volumen")
        gesamt = g.groupby("familie")["umfang"].sum().rename("gesamt")
        k = kand.groupby(["familie", "cik"], as_index=False).agg(k=("k", "max"), aus_mutter=("aus_mutter", "any"))
        k = k.join(gestuetzt, on=["familie", "cik"]).join(monate, on="familie").join(volumen, on=["familie", "cik"]).join(gesamt, on="familie")
        nach_monaten = (k["gestuetzt"].fillna(0) / k["monate"]).fillna(0.0)
        nach_volumen = (k["volumen"].fillna(0) / k["gesamt"].where(k["gesamt"] > 0)).fillna(0.0)
        k["anteil"] = nach_monaten.where(nach_monaten >= nach_volumen, nach_volumen)
        k = k[k["anteil"] >= k["aus_mutter"].map({True: MINDEST_STUETZE_MUTTER, False: MINDEST_STUETZE})]
        k = k.assign(boerse=k["cik"].isin(boerse))
        k = k.sort_values(["familie", "boerse", "anteil", "aus_mutter"], ascending=[True, False, False, False]).drop_duplicates("familie")
        fam = k.set_index("familie")
        f_cik = g["familie"].map(fam["cik"]).astype("Int64")
        f_k = g["familie"].map(fam["k"]).fillna(0.0)
    r_boerse, f_boerse = g["cik_r"].isin(boerse), f_cik.isin(boerse)
    nimm_familie = f_cik.notna() & ~(r_boerse & ~f_boerse)
    aus = g[SCHLUESSEL].copy()
    aus["cik"] = f_cik.where(nimm_familie, g["cik_r"])
    aus["konfidenz"] = f_k.where(nimm_familie, g["k_r"]).where(aus["cik"].notna(), 0.0)
    eigen = (g["cik_r"] == f_cik).fillna(False)
    aus["art"] = g["art_r"].where(~nimm_familie | eigen, "familie")
    aus.loc[aus["cik"].isna() & ~aus["art"].isin(["mehrdeutig"]), "art"] = "keiner"
    # Muttername im Abgleich gefunden, aber von den gemeldeten Namen der Familie nicht gestützt
    aus.loc[aus["cik"].isna() & g["cik_m"].notna(), "art"] = "ungestuetzt"
    marke = g["roh"].map({n: _marke(n) for n in pd.unique(g["roh"])}).astype("Int64")
    nimm_marke = aus["cik"].isna() & marke.notna()
    aus.loc[nimm_marke, "cik"] = marke[nimm_marke]
    aus.loc[nimm_marke, "konfidenz"] = 0.90
    aus.loc[nimm_marke, "art"] = "marke"
    return aus


def ordne_zu(monate: pd.DataFrame, firmen: pd.DataFrame) -> pd.DataFrame:
    """Zuordnung aus einer Monatstabelle im Ganzen (kleine Mengen und Tests; der Lauf geht je Haushaltsjahr vor)."""
    g, boerse = finde_namen(monate, firmen)
    belegung = monate[SCHLUESSEL + ["monat"]].merge(g[SCHLUESSEL].rename_axis("gid").reset_index(), on=SCHLUESSEL)
    return waehle(g, belegung[["gid", "monat"]].drop_duplicates(), boerse)


def baue_parameter(je_firma: pd.DataFrame, vor_monat: pd.Timestamp) -> pd.DataFrame:
    """Je Firma und abgeschlossenem Monat des Bekanntwerdens die Summe der Verpflichtungen.
    ``je_firma``: cik, monat, betrag (auch mehrfach je Firma und Monat, aus mehreren Haushaltsjahren)."""
    z = je_firma[je_firma["monat"] < vor_monat] if len(je_firma) else je_firma
    if z.empty:
        return leer()
    z = z.groupby(["cik", "monat"], as_index=False)["betrag"].sum()
    zeit = {}
    for m in z["monat"].drop_duplicates():
        ende = (pd.Timestamp(m) + pd.offsets.MonthEnd(0)).date()
        zeit[m] = (pd.Timestamp(datetime.combine(ende, time(23, 59, 59), tzinfo=ET)).tz_convert("UTC"),
                   pd.Timestamp(handelbar_ab(datetime.combine(ende + timedelta(days=VERZUG_MONAT_TAGE), time(23, 59, 59), tzinfo=ET))),
                   pd.Timestamp(m).strftime("%Y-%m"))
    return als_parameter(pd.DataFrame({
        "cik": z["cik"].astype("int64").to_numpy(), "parameter_id": "PR2-01",
        "ereignis_zeit": [zeit[m][0] for m in z["monat"]], "verfuegbar_ab": [zeit[m][1] for m in z["monat"]],
        "wert": z["betrag"].to_numpy(dtype="float64"), "stand": [zeit[m][2] for m in z["monat"]]}))


# --------------------------------------------------------------------------- Lauf
def lauf(ablage: Ablage, arbeits: Path, modus: str = "laufend", abruf: Abruf | None = None, lokal: Path | None = None,
         budget: Zeitbudget | None = None, heute: date | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    hinweise: list[str] = []
    firmen = ablage.lies_bereinigt("edgar_firmen")
    if firmen.empty:
        raise RuntimeError("Firmentabelle fehlt (Quelle edgar_index zuerst ausführen)")
    firmen = firmen[firmen["sic"].notna() | firmen["tickers"].notna()]     # nur Unternehmen, keine Privatpersonen
    heute = heute or datetime.now(ET).date()
    if lokal is not None:
        quellen = {}
        for pfad in sorted(Path(lokal).glob("*.zip")):
            schluessel = datei_schluessel(pfad.name)
            if schluessel:
                quellen[schluessel[0]] = (str(pfad), schluessel[1])
    else:
        abruf = abruf or Abruf(anfragen_pro_sekunde=2, versuche=8)        # der Dateiserver weist zeitweise ab
        quellen = verzeichnis(abruf, haushaltsjahr(heute))
    if not quellen:
        raise RuntimeError("Verzeichnis nennt keine Sammeldateien (Schnittstelle geändert?)")
    budget = budget or Zeitbudget()
    dateien = ablage.lies_bereinigt(TABELLE_DATEIEN)
    stand_gelesen = dict(zip(dateien["haushaltsjahr"].astype(int), pd.to_datetime(dateien["stand"]).dt.date)) if len(dateien) else {}
    juengste = sorted(quellen, reverse=True)[:NEU_LADEN]
    offen = [j for j in sorted(quellen, reverse=True)                        # neueste zuerst
             if j not in stand_gelesen or (j in juengste and quellen[j][1] > stand_gelesen[j])]
    neu, abgebrochen = {}, False
    for jahr in offen:
        if budget.abgelaufen():
            abgebrochen = True
            break
        adresse, stand = quellen[jahr]
        ziel = Path(arbeits) / "usaspending" / f"fy{jahr}.zip"
        try:
            pfad = Path(adresse) if lokal is not None else abruf.hole_datei(adresse, ziel)
            tabelle, info = lies_archiv(pfad)
        except (QuelleNichtErreichbar, OSError, zipfile.BadZipFile, EOFError) as fehler:
            # Abruf gestört oder Datei unvollständig: das Gelesene bleibt, der nächste Lauf setzt hier fort
            if lokal is not None:
                raise
            hinweise.append(f"Haushaltsjahr {jahr} nicht gelesen ({type(fehler).__name__}: {str(fehler)[:120]}); "
                            "der nächste Lauf versucht es erneut")
            abgebrochen = True
            break
        finally:
            if lokal is None:
                ziel.unlink(missing_ok=True)
                ziel.with_suffix(".zip.teil").unlink(missing_ok=True)
        ablage.schreibe_bereinigt(TABELLE_MONAT, f"fy{jahr}", tabelle.astype({s: "category" for s in SCHLUESSEL}))
        neu[jahr] = {"haushaltsjahr": jahr, "datei": Path(adresse).name, "stand": pd.Timestamp(stand), **info}
        print(f"USAspending: Haushaltsjahr {jahr} gelesen ({info['zeilen']} Zeilen)", flush=True)
    if neu:
        alt = dateien[~dateien["haushaltsjahr"].isin(list(neu))] if len(dateien) else dateien
        dateien = pd.concat([alt, pd.DataFrame(list(neu.values()))], ignore_index=True) if len(alt) else pd.DataFrame(list(neu.values()))
    if dateien.empty:
        raise RuntimeError("keine Sammeldatei gelesen")
    dateien = dateien.sort_values("haushaltsjahr").reset_index(drop=True)
    ablage.schreibe_bereinigt(TABELLE_DATEIEN, "alle", dateien)

    # je Haushaltsjahr einzeln lesen: zusammen wären es mehrere Millionen Zeilen mit drei Textspalten
    pfade = [ablage.bereinigt / f"bereinigt__{TABELLE_MONAT}__fy{int(j)}.parquet" for j in dateien["haushaltsjahr"]]
    pfade = [p for p in pfade if p.exists()]
    if len(pfade) < len(dateien):
        raise RuntimeError("Monatstabellen fehlen zu gelesenen Haushaltsjahren (Bestand unvollständig geladen?)")
    if not pfade:
        raise RuntimeError("keine Monatstabellen vorhanden")
    teile = []
    for pfad in pfade:
        t = pd.read_parquet(pfad)
        teile.append(t.assign(umfang=t["betrag"].abs()).groupby(SCHLUESSEL, as_index=False, observed=True).agg(
            betrag=("betrag", "sum"), umfang=("umfang", "sum"), zeilen=("zeilen", "sum")).astype({s: str for s in SCHLUESSEL}))
    gruppen = pd.concat(teile, ignore_index=True).groupby(SCHLUESSEL, as_index=False)[["betrag", "umfang", "zeilen"]].sum()
    g, boerse = finde_namen(gruppen, firmen)
    # Monate mit Transaktionen je Kombination, nur für Familien mit einem Treffer im Abgleich
    familien = set(g.loc[g["cik_m"].notna() | g["cik_r"].notna(), "familie"])
    kennung = g.loc[g["familie"].isin(familien), SCHLUESSEL].rename_axis("gid").reset_index()
    teile = []
    for pfad in pfade:
        t = pd.read_parquet(pfad, columns=SCHLUESSEL + ["monat"])
        t = t[t["familie"].isin(familien)].astype({s: str for s in SCHLUESSEL})
        teile.append(t.merge(kennung, on=SCHLUESSEL)[["gid", "monat"]].drop_duplicates())
    belegung = pd.concat(teile, ignore_index=True).drop_duplicates()
    zuordnung = waehle(g, belegung, boerse).merge(gruppen, on=SCHLUESSEL, how="left")
    ablage.schreibe_bereinigt(TABELLE_ZUORDNUNG, "alle", zuordnung.astype({"cik": "Int64"}))
    # abgeschlossen ist ein Monat, wenn die jüngste gelesene Sammeldatei nach seinem Ende erzeugt wurde
    stand = pd.to_datetime(dateien["stand"]).max()
    vor_monat = stand.to_period("M").to_timestamp()
    treffer = zuordnung[zuordnung["cik"].notna()][SCHLUESSEL + ["cik"]]
    teile = []
    for pfad in pfade:
        t = pd.read_parquet(pfad).astype({s: str for s in SCHLUESSEL}).merge(treffer, on=SCHLUESSEL, how="inner")
        teile.append(t.groupby(["cik", "monat"], as_index=False)["betrag"].sum())
    parameter = baue_parameter(pd.concat(teile, ignore_index=True), vor_monat)
    ablage.schreibe_parameter("usaspending", parameter)

    rest = len([j for j in quellen if j not in set(dateien["haushaltsjahr"].astype(int))])
    if abgebrochen and modus == "rueckwaerts":
        merke_fortsetzung(ablage.wurzel, "usaspending")
    if rest:
        hinweise.append(f"{rest} Haushaltsjahre noch nicht gelesen (Zeitbudget; der nächste Lauf setzt fort)")
    quote = trefferquote(zuordnung, gewicht=zuordnung["umfang"].astype("float64"))
    mit_kuerzel = zuordnung["cik"].isin(set(firmen.loc[firmen["tickers"].notna(), "cik"].astype(int)))
    anteil_boerse = float(zuordnung.loc[mit_kuerzel, "umfang"].sum() / max(zuordnung["umfang"].sum(), 1.0))
    hinweise.append(f"Zuordnung: {quote.get('quote', 0):.1%} der Namen, {quote.get('quote_gewichtet', 0):.1%} des "
                    f"Auftragsvolumens; {anteil_boerse:.1%} des Volumens bei Firmen mit Börsenkürzel")
    letzte = dateien.iloc[-1]
    hinweise.append(f"jüngste Sammeldatei: Stand {pd.Timestamp(letzte['stand']).date()}, jüngster Auftrag zivil "
                    f"{letzte['juengste_aktion_zivil']}, Verteidigung {letzte['juengste_aktion_dod']} "
                    f"({int(letzte['zeilen_dod'])} von {int(letzte['zeilen'])} Zeilen; Sperre {SPERRE_DOD_TAGE} Tage)")
    info = {"haushaltsjahre_verzeichnis": len(quellen), "haushaltsjahre_gelesen": int(len(dateien)), "neu_gelesen": sorted(neu),
            "zeilen_quelle": int(dateien["zeilen"].sum()), "ohne_datum": int(dateien["ohne_datum"].sum()),
            "ohne_meldetag": int(dateien["ohne_meldetag"].sum()), "familien": int(gruppen["familie"].nunique()),
            "firmen": int(parameter["cik"].nunique()) if len(parameter) else 0,
            "letzter_monat": (vor_monat - pd.offsets.MonthBegin(1)).strftime("%Y-%m"), "anteil_boerse": round(anteil_boerse, 4),
            "trefferquote": quote}
    return parameter, info, hinweise
