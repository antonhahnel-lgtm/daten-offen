"""Klinische Studien (ClinicalTrials.gov) und Arzneimittelzulassungen (openFDA) mit Zuordnung zur CIK.

Die Abrufe folgen den im Insider-Monitor erprobten Feldern (catalysts.py), hier aber für alle
Industrie-Sponsoren statt je Firma. Das Register zeigt nur den heutigen Stand; stichtagsecht sind
deshalb nur Ereignisse mit eigenem Veröffentlichungsdatum (Ergebnis im Register, Zulassung).
Damit Terminverschiebungen und Statuswechsel künftig datierbar werden, schreibt jeder Lauf die
Änderungen gegenüber dem Vorlauf in ein Änderungsprotokoll.
"""
from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.namen import Namensabgleich, trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab_serie

CT_URL = "https://clinicaltrials.gov/api/v2/studies"
CT_PHASEN = "PHASE2 OR PHASE3"
CT_FELDER = ",".join([
    "protocolSection.identificationModule.nctId",
    "protocolSection.statusModule.overallStatus",
    "protocolSection.statusModule.primaryCompletionDateStruct",
    "protocolSection.statusModule.resultsFirstPostDateStruct",
    "protocolSection.statusModule.lastUpdatePostDateStruct",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor",
    "protocolSection.designModule.phases",
    "hasResults",
])
FDA_VERZEICHNIS = "https://api.fda.gov/download.json"
STUDIEN, AENDERUNGEN, ZULASSUNGEN = "klinik_studien", "klinik_aenderungen", "klinik_zulassungen"
BEOBACHTET = ["status", "pcd", "pcd_typ", "ergebnisse"]
MINDEST_KONFIDENZ = 0.90

registriere(
    Parameter(id="GA1-04", name="Studienergebnis im Register veröffentlicht",
              definition="Ergebnisse einer Phase-2- oder Phase-3-Studie mit Industrie-Sponsor erstmals in ClinicalTrials.gov "
                         "eingestellt; wert = 3 bei Phase 3, sonst 2",
              einheit="Phase (2, 3)", frequenz="je Studie",
              offenlegung="gesetzlich: FDAAA 801, Ergebnisse spätestens 12 Monate nach primärem Abschluss",
              quelle="https://clinicaltrials.gov/api/v2/studies", lizenz="gemeinfrei (US-Behörde)", historie_ab="2008",
              verzoegerung="nächster Handelstag nach dem Einstelldatum",
              schwaechen="Der Registereintrag folgt der Pressemitteilung meist mit Monaten Abstand; Zuordnung über "
                         "Sponsornamen; Termine und Statuswechsel erst ab dem ersten Lauf über das Änderungsprotokoll"),
    Parameter(id="GA1-08", name="Arzneimittelzulassung",
              definition="Erstzulassung eines Antrags (Einreichung ORIG mit Status AP) laut Drugs@FDA; "
                         "wert = 2 bei vorrangiger Prüfung, sonst 1",
              einheit="Art (1, 2)", frequenz="je Zulassung",
              offenlegung="amtlich offen: FDA, Drugs@FDA", quelle="https://api.fda.gov/download.json (drug/drugsfda)",
              lizenz="gemeinfrei (US-Behörde)", historie_ab="1939",
              verzoegerung="nächster Handelstag nach dem Zulassungsdatum",
              schwaechen="Künftige Zieltermine (PDUFA) stehen nicht in den Daten der FDA; Zuordnung über den "
                         "Antragsteller, der vom heutigen Rechteinhaber abweichen kann"),
)


def _feld(d: dict, pfad: str, vorgabe=None):
    for teil in pfad.split("."):
        if not isinstance(d, dict) or teil not in d:
            return vorgabe
        d = d[teil]
    return d


def _datum(struktur) -> tuple[pd.Timestamp, str]:
    if not isinstance(struktur, dict) or not struktur.get("date"):
        return pd.NaT, ""
    return pd.to_datetime(str(struktur["date"]), errors="coerce"), str(struktur.get("type", ""))


def lade_studien(abruf: Abruf, max_seiten: int = 400) -> pd.DataFrame:
    """Alle Phase-2/3-Studien; je Studie eine Zeile."""
    zeilen, marke = [], None
    for _ in range(max_seiten):
        params = {"filter.advanced": f"AREA[Phase]({CT_PHASEN})", "fields": CT_FELDER, "pageSize": 1000, "format": "json"}
        if marke:
            params["pageToken"] = marke
        antwort = abruf.hole_json(CT_URL, params=params)
        for s in antwort.get("studies", []):
            sponsor = _feld(s, "protocolSection.sponsorCollaboratorsModule.leadSponsor", {}) or {}
            phasen = _feld(s, "protocolSection.designModule.phases", []) or []
            pcd, pcd_typ = _datum(_feld(s, "protocolSection.statusModule.primaryCompletionDateStruct"))
            ergebnis, _ = _datum(_feld(s, "protocolSection.statusModule.resultsFirstPostDateStruct"))
            zeilen.append({
                "nct": _feld(s, "protocolSection.identificationModule.nctId", ""),
                "sponsor": str(sponsor.get("name", "")), "sponsor_typ": str(sponsor.get("class", "")),
                "status": _feld(s, "protocolSection.statusModule.overallStatus", ""),
                "phase": "|".join(phasen), "ph3": "PHASE3" in phasen,
                "pcd": pcd, "pcd_typ": pcd_typ, "ergebnisse": bool(s.get("hasResults")), "ergebnis_datum": ergebnis,
            })
        marke = antwort.get("nextPageToken")
        if not marke:
            break
    df = pd.DataFrame(zeilen)
    return df[df["nct"] != ""].drop_duplicates("nct").reset_index(drop=True) if len(df) else df


def lade_zulassungen(abruf: Abruf, arbeits: Path) -> pd.DataFrame:
    """Zugelassene Einreichungen aus dem Sammelabzug von Drugs@FDA."""
    verzeichnis = abruf.hole_json(FDA_VERZEICHNIS)
    teile = _feld(verzeichnis, "results.drug.drugsfda.partitions", [])
    if not teile:
        raise KeyError("openFDA-Verzeichnis ohne results.drug.drugsfda.partitions")
    zeilen = []
    for i, teil in enumerate(teile):
        pfad = abruf.hole_datei(teil["file"], Path(arbeits) / f"drugsfda_{i}.zip")
        with zipfile.ZipFile(pfad) as archiv:
            for name in archiv.namelist():
                if not name.lower().endswith(".json"):
                    continue
                with archiv.open(name) as f:
                    daten = json.load(f)
                for antrag in daten.get("results", []):
                    for e in antrag.get("submissions", []) or []:
                        if str(e.get("submission_status", "")).upper() != "AP":
                            continue
                        zeilen.append({
                            "antrag": antrag.get("application_number", ""), "sponsor": antrag.get("sponsor_name", ""),
                            "typ": str(e.get("submission_type", "")).upper(),
                            "datum": pd.to_datetime(e.get("submission_status_date"), format="%Y%m%d", errors="coerce"),
                            "vorrang": str(e.get("review_priority", "")).upper().startswith("PRIOR"),
                        })
        pfad.unlink(missing_ok=True)
    df = pd.DataFrame(zeilen, columns=["antrag", "sponsor", "typ", "datum", "vorrang"])
    return df[df["datum"].notna() & (df["antrag"] != "")].reset_index(drop=True)


def aenderungen(alt: pd.DataFrame, neu: pd.DataFrame, heute: date) -> pd.DataFrame:
    """Änderungen der beobachteten Felder gegenüber dem Vorlauf (je Studie und Feld eine Zeile)."""
    spalten = ["nct", "feld", "alt", "neu", "abruf_datum"]
    if alt.empty or neu.empty:
        return pd.DataFrame(columns=spalten)
    paar = alt[["nct"] + BEOBACHTET].merge(neu[["nct"] + BEOBACHTET], on="nct", suffixes=("_alt", "_neu"))
    zeilen = []
    for feld in BEOBACHTET:
        a, n = paar[f"{feld}_alt"].astype("string").fillna(""), paar[f"{feld}_neu"].astype("string").fillna("")
        anders = a != n
        zeilen.append(pd.DataFrame({"nct": paar.loc[anders, "nct"], "feld": feld, "alt": a[anders], "neu": n[anders],
                                    "abruf_datum": pd.Timestamp(heute)}))
    return pd.concat(zeilen, ignore_index=True)[spalten]


def _tagesende(tage: pd.Series) -> pd.Series:
    return (pd.to_datetime(tage) + pd.Timedelta(hours=18)).dt.tz_localize(
        ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")


def baue_parameter(studien: pd.DataFrame, zulassungen: pd.DataFrame, firmen: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    abgleich = Namensabgleich(firmen)
    teile, quoten = [], {}

    def zuordnen(df: pd.DataFrame, name: str) -> pd.DataFrame:
        z = abgleich.ordne_zu(df["sponsor"])
        z.loc[z["konfidenz"] < MINDEST_KONFIDENZ, "cik"] = pd.NA
        quoten[name] = trefferquote(z)
        return df.assign(cik=z["cik"])

    if len(studien):
        s = studien[(studien["sponsor_typ"] == "INDUSTRY") & studien["ergebnis_datum"].notna()]
        if len(s):
            s = zuordnen(s, "studien")
            s = s[s["cik"].notna()]
            ereignis = _tagesende(s["ergebnis_datum"])
            teile.append(pd.DataFrame({"cik": s["cik"].astype("int64").to_numpy(), "parameter_id": "GA1-04",
                                       "ereignis_zeit": ereignis.values, "verfuegbar_ab": handelbar_ab_serie(ereignis).values,
                                       "wert": s["ph3"].map({True: 3.0, False: 2.0}).to_numpy(), "stand": s["nct"].to_numpy()}))
    if len(zulassungen):
        z = zulassungen[zulassungen["typ"] == "ORIG"].sort_values("datum").drop_duplicates("antrag")
        if len(z):
            z = zuordnen(z, "zulassungen")
            z = z[z["cik"].notna()]
            ereignis = _tagesende(z["datum"])
            teile.append(pd.DataFrame({"cik": z["cik"].astype("int64").to_numpy(), "parameter_id": "GA1-08",
                                       "ereignis_zeit": ereignis.values, "verfuegbar_ab": handelbar_ab_serie(ereignis).values,
                                       "wert": z["vorrang"].map({True: 2.0, False: 1.0}).to_numpy(), "stand": z["antrag"].to_numpy()}))
    teile = [t for t in teile if len(t)]
    return (als_parameter(pd.concat(teile, ignore_index=True)) if teile else leer()), quoten


def lauf(ablage: Ablage, arbeits: Path, abruf_ct: Abruf | None = None, abruf_fda: Abruf | None = None,
         heute: date | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    heute = heute or date.today()
    firmen = ablage.lies_bereinigt("edgar_firmen")
    if firmen.empty:
        raise RuntimeError("Firmentabelle fehlt (Quelle edgar_index zuerst ausführen)")
    firmen = firmen[firmen["sic"].notna() | firmen["tickers"].notna()]
    hinweise: list[str] = []
    vorlauf = ablage.lies_bereinigt(STUDIEN)
    studien = lade_studien(abruf_ct or Abruf(anfragen_pro_sekunde=0.7))
    if studien.empty:
        raise RuntimeError("ClinicalTrials.gov lieferte keine Studien")
    neu = aenderungen(vorlauf, studien, heute)
    if len(neu):
        bisher = ablage.lies_bereinigt(AENDERUNGEN)
        alle = pd.concat([bisher, neu], ignore_index=True) if len(bisher) else neu
        for alt in ablage.bereinigt.glob(f"bereinigt__{AENDERUNGEN}__*.parquet"):
            alt.unlink()
        for jahr, teil in alle.groupby(pd.to_datetime(alle["abruf_datum"]).dt.year):
            ablage.schreibe_bereinigt(AENDERUNGEN, str(int(jahr)), teil)
    ablage.schreibe_bereinigt(STUDIEN, "alle", studien)
    zulassungen = lade_zulassungen(abruf_fda or Abruf(anfragen_pro_sekunde=2), arbeits)
    ablage.schreibe_bereinigt(ZULASSUNGEN, "alle", zulassungen)
    parameter, quoten = baue_parameter(studien, zulassungen, firmen)
    ablage.schreibe_parameter("klinik", parameter)
    for name, q in quoten.items():
        hinweise.append(f"Namensabgleich {name}: {q['quote']:.1%} der Zeilen zugeordnet")
    if vorlauf.empty:
        hinweise.append("Erster Lauf: Änderungsprotokoll beginnt mit dem nächsten Lauf")
    info = {"studien": int(len(studien)), "zulassungen": int(len(zulassungen)), "aenderungen": int(len(neu)),
            "trefferquote": quoten}
    return parameter, info, hinweise
