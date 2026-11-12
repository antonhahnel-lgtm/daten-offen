"""Erteilte US-Patente je Firma aus dem Amtsblatt des USPTO (Official Gazette for Patents).

Das Amtsblatt erscheint jeden Dienstag, dem Tag der Erteilung, und führt ein Verzeichnis der Patentinhaber. Es ist
ohne Anmeldung abrufbar, hält aber nur die letzten 52 Ausgaben vor (der Ordner einer Kalenderwoche wird im Folgejahr
überschrieben). Die Sammeldaten des USPTO mit der Historie (PatentsView, wöchentliche Erteilungsdateien) liegen seit
06/2026 hinter einer Anmeldung mit Schnittstellenschlüssel und sind hier nicht angebunden.

Im Verzeichnis steht jedes Patent beim ersten Erfinder („Erfinder, to Inhaber Titel Nummer“) und unter jedem
weiteren Erfinder und jedem Inhaber als Verweis („Name: See--“). Inhaber ist ein Verweisname, der im Eintrag des
ersten Erfinders hinter „to“ steht.

  patente_erteilt__<jahr>    tag, nummer, art (utility, design, plant, reissue), inhaber
  patente_ausgaben__alle     gelesene Ausgaben mit Zahl der Patente
  patente_zuordnung__alle    inhaber -> cik, konfidenz, art
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.namen import Namensabgleich, bereinige, trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab
from ..kern.zustand import Zeitbudget, merke_fortsetzung

SEITE = "https://www.uspto.gov/learning-and-resources/official-gazette/official-gazette-patents"
ADRESSE = "https://patentsgazette.uspto.gov/week{woche:02d}/OG/{seite}"
SEITENLISTE = "patenteeByNameLeft.html"
SEITEN_ERSATZ = [f"patentee/alpha{b}.html" for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + ["patentee/alphaOthers.html"]
WOCHEN = 52
MIN_PATENTE = 2000             # eine Ausgabe mit weniger Patenten gilt als falsch gelesen (üblich sind 6.000 bis 9.000)
MINDEST_KONFIDENZ = 0.90
TABELLE_ERTEILT, TABELLE_AUSGABEN, TABELLE_ZUORDNUNG = "patente_erteilt", "patente_ausgaben", "patente_zuordnung"
EINTRAG = re.compile(r'<div class="list_item([12])">(.*?)</div>', re.S)
VERWEIS = re.compile(r'<a href="[^"]*?/US([A-Z]*\d+)-(\d{8})\.html">')
SEITENVERWEIS = re.compile(r'href="(patentee/alpha\w+\.html)"')
AUSGABETAG = re.compile(r"ISSUED ON THE (\d{1,2})\w* DAY OF ([A-Za-z]+), (\d{4})")
MARKE = re.compile(r"<[^>]+>")
LEERRAUM = re.compile(r"\s+")
ZU = re.compile(r"[;,] to ")
OHNE_ZEICHEN = re.compile(r"[^A-Z0-9]+")
SIEHE = ": See--"
ARTEN = {"": "utility", "D": "design", "PP": "plant", "RE": "reissue"}
MONATE = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november "
                                         "december".split())}
# Patente hält oft eine Tochter mit eigenem Namen. Inhaber (wie gedruckt) -> Name der börsennotierten Mutter bei EDGAR.
# Von Hand geprüft, Stand 11/2026; vor einer Erweiterung in die Vergangenheit braucht die Liste Gültigkeitszeiträume
# (z. B. Raytheon Company: erst seit 04/2020 RTX).
TOCHTER_NAMEN = {
    "Dell Products L.P.": "Dell Technologies Inc.", "Microsoft Technology Licensing, LLC": "MICROSOFT CORP",
    "Cisco Technology, Inc.": "CISCO SYSTEMS, INC.", "Amazon Technologies, Inc.": "AMAZON COM INC",
    "Zoox, Inc.": "AMAZON COM INC", "Google LLC": "Alphabet Inc.", "Waymo LLC": "Alphabet Inc.",
    "Hewlett Packard Enterprise Development LP": "Hewlett Packard Enterprise Co",
    "Hewlett-Packard Development Company, L.P.": "HP INC", "Capital One Services, LLC": "CAPITAL ONE FINANCIAL CORP",
    "GM Global Technology Operations LLC": "General Motors Co", "Ford Global Technologies, LLC": "FORD MOTOR CO",
    "GE Precision Healthcare LLC": "GE HealthCare Technologies Inc.", "Intel Products IP LLC": "INTEL CORP",
    "Verizon Patent and Licensing Inc.": "VERIZON COMMUNICATIONS INC", "T-Mobile Innovations LLC": "T-Mobile US, Inc.",
    "T-Mobile USA, Inc.": "T-Mobile US, Inc.", "Boston Scientific Scimed, Inc.": "BOSTON SCIENTIFIC CORP",
    "Cardiac Pacemakers, Inc.": "BOSTON SCIENTIFIC CORP", "Covidien LP": "Medtronic plc",
    "Medtronic MiniMed, Inc.": "Medtronic plc", "Warsaw Orthopedic, Inc.": "Medtronic plc",
    "Pratt & Whitney Canada Corp.": "RTX Corp", "Hamilton Sundstrand Corporation": "RTX Corp",
    "Raytheon Company": "RTX Corp", "Goodrich Corporation": "RTX Corp", "Rosemount Aerospace Inc.": "RTX Corp",
    "Rockwell Collins, Inc.": "RTX Corp", "Halliburton Energy Services, Inc.": "HALLIBURTON CO",
    "Truist Bank": "TRUIST FINANCIAL CORP", "AT&T Intellectual Property I, L.P.": "AT&T INC.",
    "Wells Fargo Bank, N.A.": "WELLS FARGO & COMPANY/MN", "3M Innovative Properties Company": "3M CO",
    "Eaton Intelligent Power Limited": "Eaton Corp plc", "Aptiv Technologies AG": "Aptiv PLC",
    "InterDigital Patent Holdings, Inc.": "InterDigital, Inc.",
    "Rockwell Automation Technologies, Inc.": "ROCKWELL AUTOMATION, INC", "II-VI Delaware, Inc.": "COHERENT CORP.",
    "Aurora Operations, Inc.": "Aurora Innovation, Inc.", "Cilag GmbH International": "JOHNSON & JOHNSON",
    "Ethicon LLC": "JOHNSON & JOHNSON", "Avago Technologies International Sales Pte. Limited": "Broadcom Inc.",
    "VMware LLC": "Broadcom Inc.", "Schlumberger Technology Corporation": "SCHLUMBERGER LIMITED/NV",
    "Intuitive Surgical Operations, Inc.": "INTUITIVE SURGICAL INC", "Pacesetter, Inc.": "ABBOTT LABORATORIES",
    "Abbott Diabetes Care Inc.": "ABBOTT LABORATORIES", "Abbott Cardiovascular Systems Inc.": "ABBOTT LABORATORIES",
    "ResMed Pty Ltd": "RESMED INC", "Meta Platforms Technologies, LLC": "Meta Platforms, Inc.",
    "Western Digital Technologies, Inc.": "WESTERN DIGITAL CORP", "Sandisk Technologies, Inc.": "Sandisk Corp",
    "JPMorgan Chase Bank, N.A.": "JPMORGAN CHASE & CO", "Visa International Service Association": "VISA INC.",
    "Dolby Laboratories Licensing Corporation": "Dolby Laboratories, Inc.",
    "Rivian IP Holdings, LLC": "Rivian Automotive, Inc. / DE", "GlobalFoundries U.S. Inc.": "GLOBALFOUNDRIES Inc.",
    "Chevron U.S.A. Inc.": "CHEVRON CORP", "ExxonMobil Technology and Engineering Company": "EXXON MOBIL CORP",
    "Baker Hughes Oilfield Operations LLC": "Baker Hughes Co", "Disney Enterprises, Inc.": "Walt Disney Co",
    "Marvell Asia Pte Ltd": "Marvell Technology, Inc.", "Merck Sharp & Dohme LLC": "Merck & Co., Inc.",
    "Zimmer, Inc.": "ZIMMER BIOMET HOLDINGS, INC.", "Biomet Manufacturing, LLC": "ZIMMER BIOMET HOLDINGS, INC.",
    "Otis Elevator Company": "Otis Worldwide Corp", "Rosemount Inc.": "EMERSON ELECTRIC CO",
    "Fisher-Rosemount Systems, Inc.": "EMERSON ELECTRIC CO", "Dow Global Technologies LLC": "DOW INC.",
    "Lumentum Operations LLC": "Lumentum Holdings Inc.", "Walmart Apollo, LLC": "Walmart Inc.",
    "Target Brands, Inc.": "TARGET CORP", "Textron Innovations Inc.": "TEXTRON INC", "Bell Textron Inc.": "TEXTRON INC",
    "Garmin Switzerland GmbH": "GARMIN LTD", "Trane International Inc.": "Trane Technologies plc",
    "Johnson Controls Tyco IP Holdings LLP": "Johnson Controls International plc",
    "TE Connectivity Solutions GmbH": "TE Connectivity plc",
    "Semiconductor Components Industries, LLC": "ON SEMICONDUCTOR CORP", "NXP USA, Inc.": "NXP Semiconductors N.V.",
    "NXP B.V.": "NXP Semiconductors N.V.", "Qorvo US, Inc.": "Qorvo, Inc.",
    "QuantumScape Battery, Inc.": "QuantumScape Corp", "Harley-Davidson Motor Company, Inc.": "HARLEY-DAVIDSON, INC.",
    "Life Technologies Corporation": "THERMO FISHER SCIENTIFIC INC.", "ModernaTX, Inc.": "Moderna, Inc.",
    "Biogen MA Inc.": "BIOGEN INC.", "Northrop Grumman Systems Corporation": "NORTHROP GRUMMAN CORP /DE/",
    "Analog Devices International Unlimited Company": "ANALOG DEVICES INC", "Adeia Guides Inc.": "Adeia Inc.",
    "Activision Publishing, Inc.": "MICROSOFT CORP", "Nuance Communications, Inc.": "MICROSOFT CORP",
    "Toyota Jidosha Kabushiki Kaisha": "TOYOTA MOTOR CORP/",
    "Telefonaktiebolaget LM Ericsson (publ)": "ERICSSON LM TELEPHONE CO", "Nokia Technologies Oy": "NOKIA CORP",
    "ASML Netherlands B.V.": "ASML HOLDING NV", "Stryker European Operations Limited": "STRYKER CORP",
    "CNH Industrial America LLC": "CNH Industrial N.V.", "Universal City Studios LLC": "COMCAST CORP",
    "Comcast Cable Communications, LLC": "COMCAST CORP",
    "Charter Communications Operating, LLC": "CHARTER COMMUNICATIONS, INC. /MO/", "DISH Network L.L.C.": "EchoStar CORP",
    "DISH Network Technologies India Private Limited": "EchoStar CORP",
    "Home Depot Product Authority, LLC": "HOME DEPOT, INC.",
    # ergänzt nach dem ersten echten Lauf (größte nicht zugeordnete Inhaber aus 52 Ausgaben)
    "SharkNinja Operating LLC": "SharkNinja, Inc.", "Philip Morris Products S.A.": "Philip Morris International Inc.",
    "Nicoventures Trading Limited": "British American Tobacco p.l.c.",
    "Tyco Fire & Security GmbH": "Johnson Controls International plc",
    "Biosense Webster (Israel) Ltd.": "JOHNSON & JOHNSON", "DePuy Synthes Products, Inc.": "JOHNSON & JOHNSON",
    "Auris Health, Inc.": "JOHNSON & JOHNSON", "GM Cruise Holdings LLC": "General Motors Co",
    "Altria Client Services LLC": "ALTRIA GROUP, INC.", "GE Vernova Infrastructure Technology LLC": "GE Vernova Inc.",
    "Wolverine Outdoors, Inc.": "WOLVERINE WORLD WIDE INC /DE/", "LNW Gaming, Inc.": "Light & Wonder, Inc.",
    "Accenture Global Solutions Limited": "Accenture plc", "Universal Display Corporation": "UNIVERSAL DISPLAY CORP \\PA\\",
    "Solventum Intellectual Properties Company": "Solventum Corp",
    "BAE Systems Information and Electronic Systems Integration Inc.": "BAE SYSTEMS PLC /FI/",
    "Transportation IP Holdings, LLC": "WESTINGHOUSE AIR BRAKE TECHNOLOGIES CORP", "Conopco, Inc.": "UNILEVER PLC",
    "ATI Technologies ULC": "ADVANCED MICRO DEVICES INC", "Peridot Print LLC": "HP INC",
    "CareFusion 303, Inc.": "BECTON DICKINSON & CO", "Bard Access Systems, Inc.": "BECTON DICKINSON & CO",
    "Magna Electronics Inc.": "MAGNA INTERNATIONAL INC", "YETI Coolers, LLC": "YETI Holdings, Inc.",
    "DISH Wireless L.L.C.": "EchoStar CORP", "Boost SubscriberCo L.L.C.": "EchoStar CORP",
    "Morgan Stanley Services Group Inc.": "MORGAN STANLEY", "ExxonMobil Chemical Patents Inc.": "EXXON MOBIL CORP",
    "Corning Research & Development Corporation": "CORNING INC /NY", "InterDigital VC Holdings, Inc.": "InterDigital, Inc.",
    "St. Jude Medical, Cardiology Division, Inc.": "ABBOTT LABORATORIES", "Howmedica Osteonics Corp.": "STRYKER CORP",
    "Graphic Packaging International, LLC": "GRAPHIC PACKAGING HOLDING CO",
    "Logitech Europe S.A.": "LOGITECH INTERNATIONAL S.A.", "QUALCOMM Incorproated": "QUALCOMM INC/DE",
    "Sony Interactive Entertainment Inc.": "Sony Group Corp", "Sony Semiconductor Solutions Corporation": "Sony Group Corp",
    "Nokia Solutions and Networks Oy": "NOKIA CORP", "STMicroelectronics S.r.l.": "STMicroelectronics N.V.",
}
TOCHTER = {bereinige(tochter): mutter for tochter, mutter in TOCHTER_NAMEN.items()}

_OFFEN = "amtlich offen: 35 U.S.C. 153; das Amtsblatt erscheint am Tag der Erteilung (jeder Dienstag)"
registriere(Parameter(
    id="GA1-01", name="Erteilte Patente",
    definition="Zahl der an einem Ausgabetag an die Firma und ihre bekannten Patent-Töchter erteilten Erfindungspatente "
               "(utility). Ein Patent mit mehreren Inhabern zählt bei jedem. Wochen ohne Zeile zählen null; das "
               "Verhältnis zum F&E-Aufwand (Katalog: Innovationseffizienz) bildet der Nutzer",
    einheit="Anzahl", frequenz="wöchentlich (Dienstag)", offenlegung=_OFFEN, quelle=SEITE,
    lizenz="gemeinfrei (US-Behörde)", historie_ab="11/2025",
    verzoegerung="Eröffnung des ersten Handelstags nach dem Ausgabetag",
    schwaechen="Nur die letzten 52 Wochen rückwirkend (die Historie des USPTO liegt hinter einer Anmeldung); Zuordnung "
               "über Firmennamen und eine von Hand geprüfte Liste von Patent-Töchtern (Trefferquote im Prüfbericht), "
               "weitere Töchter mit eigenem Namen fehlen; Zitationen sind nicht enthalten; spätere Übertragungen "
               "eines Patents bleiben unberücksichtigt"))


# --------------------------------------------------------------------------- Ausgaben und Seiten
def wochennummer(tag: date) -> int:
    """Nummer der Ausgabe im Jahr: der wievielte Dienstag (der Ordner ``week45`` gehört zum 45. Dienstag)."""
    return (tag.timetuple().tm_yday - 1) // 7 + 1


def ausgabetage(heute: date, wochen: int = WOCHEN) -> list[date]:
    """Die letzten Dienstage bis ``heute``, jüngster zuerst."""
    letzter = heute - timedelta(days=(heute.weekday() - 1) % 7)
    return [letzter - timedelta(weeks=i) for i in range(wochen)]


def _text(s: str) -> str:
    return LEERRAUM.sub(" ", html.unescape(MARKE.sub("", s)).replace("\xa0", " ")).strip()


def _gleich(s: str) -> str:
    """Vergleichsform eines Namens: Großbuchstaben, ohne Satzzeichen und ohne den Artikel."""
    return " " + " ".join(w for w in OHNE_ZEICHEN.sub(" ", s.upper()).split() if w != "THE") + " "


def lies_seite(seite: str) -> tuple[date | None, list[tuple[str, str]], dict[str, str]]:
    """Eine Seite des Verzeichnisses: Ausgabetag, Verweise (Name, Patentnummer) und je Patentnummer der Text
    im Eintrag des ersten Erfinders vor der Nummer."""
    m = AUSGABETAG.search(_text(seite[:4000]))
    tag = None
    if m and m.group(2).lower() in MONATE:
        tag = date(int(m.group(3)), MONATE[m.group(2).lower()], int(m.group(1)))
    verweise: list[tuple[str, str]] = []
    erst: dict[str, str] = {}
    name = None
    for stufe, inhalt in EINTRAG.findall(seite):
        treffer = VERWEIS.search(inhalt)
        if stufe == "1":
            t = _text(inhalt)
            if t.endswith(SIEHE):
                name = t[:-len(SIEHE)].strip()
            else:
                name = None
                if treffer:
                    erst[treffer.group(1)] = _text(inhalt[:treffer.start()])
        elif name and treffer:
            verweise.append((name, treffer.group(1)))
    return tag, verweise, erst


def werte_aus(verweise: list[tuple[str, str]], erst: dict[str, str]) -> tuple[pd.DataFrame, dict]:
    """Inhaber je Patent aus den Verweisen aller Seiten einer Ausgabe."""
    nach_zu = {n: (_gleich(ZU.split(t, maxsplit=1)[1]) if ZU.search(t) else "") for n, t in erst.items()}
    paare = {(name, n) for name, n in verweise if nach_zu.get(n) and _gleich(name) in nach_zu[n]}
    t = pd.DataFrame(sorted(paare), columns=["inhaber", "nummer"])
    vorsatz = t["nummer"].str.extract(r"^([A-Z]*)", expand=False)
    t["art"] = vorsatz.map(ARTEN).fillna("sonstige")
    mit_inhaber = sum(1 for v in nach_zu.values() if v)
    info = {"patente": len(erst), "mit_inhaber": mit_inhaber, "inhaber_erkannt": int(t["nummer"].nunique()),
            "erfindungspatente": sum(1 for n in erst if n.isdigit())}
    return t[["nummer", "art", "inhaber"]], info


def _inhalt(antwort) -> str:
    return antwort.content.decode("utf-8", errors="replace")


def hole_ausgabe(abruf, tag: date) -> tuple[pd.DataFrame | None, dict]:
    """Liest die Ausgabe eines Dienstags; ``None``, wenn der Ordner (noch) eine andere Ausgabe enthält."""
    woche = wochennummer(tag)
    liste = abruf.hole(ADRESSE.format(woche=woche, seite=SEITENLISTE), erlaube_404=True)
    seiten = sorted(set(SEITENVERWEIS.findall(_inhalt(liste)))) if liste is not None else []
    seiten = seiten or SEITEN_ERSATZ
    verweise: list[tuple[str, str]] = []
    erst: dict[str, str] = {}
    for seite in seiten:
        antwort = abruf.hole(ADRESSE.format(woche=woche, seite=seite), erlaube_404=True)
        if antwort is None:
            if seite == seiten[0]:
                return None, {"grund": "nicht vorhanden"}
            continue
        seitentag, v, e = lies_seite(_inhalt(antwort))
        if seitentag != tag:
            return None, {"grund": f"Ordner week{woche:02d} enthält die Ausgabe vom {seitentag}"}
        verweise += v
        erst.update(e)
    tabelle, info = werte_aus(verweise, erst)
    info.update(woche=woche, seiten=len(seiten))
    if info["patente"] < MIN_PATENTE:
        return None, {"grund": f"nur {info['patente']} Patente gelesen (Aufbau geändert?)"}
    return tabelle.assign(tag=pd.Timestamp(tag))[["tag", "nummer", "art", "inhaber"]], info


# --------------------------------------------------------------------------- Zuordnung und Parameter
def ordne_zu(inhaber: pd.DataFrame, firmen: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """CIK je Inhabername: Liste der Patent-Töchter, sonst Namensabgleich (exakt, früherer Name, Kernname).
    Rückgabe: Zuordnung und die Mütter der Liste, die der Abgleich nicht eindeutig findet."""
    abgleich = Namensabgleich(firmen)
    mutter = {schluessel: abgleich.finde(name, aehnlich=False) for schluessel, name in TOCHTER.items()}
    unbekannt = sorted({TOCHTER[s] for s, (cik, _, _) in mutter.items() if cik is None})
    zeilen = []
    for name in inhaber["inhaber"]:
        schluessel = bereinige(name)
        if schluessel in mutter and mutter[schluessel][0] is not None:
            zeilen.append((mutter[schluessel][0], 0.95, "tochter"))
        else:
            cik, konfidenz, art = abgleich.finde(name, aehnlich=False)
            zeilen.append((cik, konfidenz, art) if cik is not None and konfidenz >= MINDEST_KONFIDENZ else (None, 0.0, art if cik is None else "keiner"))
    z = pd.DataFrame(zeilen, columns=["cik", "konfidenz", "art"], index=inhaber.index)
    z["cik"] = z["cik"].astype("Int64")
    return pd.concat([inhaber, z], axis=1), unbekannt


def baue_parameter(erteilt: pd.DataFrame, zuordnung: pd.DataFrame) -> pd.DataFrame:
    """Je Firma und Ausgabetag die Zahl der Erfindungspatente."""
    treffer = zuordnung[zuordnung["cik"].notna()][["inhaber", "cik"]]
    z = erteilt[erteilt["art"] == "utility"].merge(treffer, on="inhaber", how="inner")
    if z.empty:
        return leer()
    z = z.drop_duplicates(["cik", "tag", "nummer"]).groupby(["cik", "tag"], as_index=False).size()
    zeit = {}
    for tag in z["tag"].drop_duplicates():
        d = pd.Timestamp(tag).date()
        zeit[tag] = (pd.Timestamp(datetime.combine(d, time(0, 0), tzinfo=ET)).tz_convert("UTC"),
                     pd.Timestamp(handelbar_ab(datetime.combine(d, time(18, 0), tzinfo=ET))), d.isoformat())
    return als_parameter(pd.DataFrame({
        "cik": z["cik"].astype("int64").to_numpy(), "parameter_id": "GA1-01",
        "ereignis_zeit": [zeit[t][0] for t in z["tag"]], "verfuegbar_ab": [zeit[t][1] for t in z["tag"]],
        "wert": z["size"].to_numpy(dtype="float64"), "stand": [zeit[t][2] for t in z["tag"]]}))


# --------------------------------------------------------------------------- Lauf
def lauf(ablage: Ablage, arbeits: Path | None = None, modus: str = "laufend", abruf=None,
         budget: Zeitbudget | None = None, heute: date | None = None, max_fehler: int = 3) -> tuple[pd.DataFrame, dict, list[str]]:
    hinweise: list[str] = []
    firmen = ablage.lies_bereinigt("edgar_firmen")
    if firmen.empty:
        raise RuntimeError("Firmentabelle fehlt (Quelle edgar_index zuerst ausführen)")
    firmen = firmen[firmen["sic"].notna() | firmen["tickers"].notna()]     # nur Unternehmen, keine Privatpersonen
    heute = heute or datetime.now(ET).date()
    budget = budget or Zeitbudget()
    ausgaben = ablage.lies_bereinigt(TABELLE_AUSGABEN)
    erteilt = ablage.lies_bereinigt(TABELLE_ERTEILT)
    bekannt = set(pd.to_datetime(ausgaben["tag"]).dt.date) if len(ausgaben) else set()
    if len(erteilt):
        erteilt["tag"] = pd.to_datetime(erteilt["tag"])
    neu, neue_zeilen, fehlend, fehler, abgebrochen = [], [], [], 0, False
    for tag in ausgabetage(heute):                             # jüngste zuerst
        if tag in bekannt:
            continue
        if budget.abgelaufen():
            abgebrochen = True
            break
        abruf = abruf or Abruf(anfragen_pro_sekunde=2)
        try:
            tabelle, info = hole_ausgabe(abruf, tag)
        except QuelleNichtErreichbar as stoerung:
            fehler += 1
            hinweise.append(f"Ausgabe {tag} nicht gelesen ({str(stoerung)[:100]})")
            if fehler >= max_fehler:
                abgebrochen = True
                break
            continue
        if tabelle is None:
            fehlend.append((tag, info["grund"]))
            continue
        neue_zeilen.append(tabelle)
        neu.append({"tag": pd.Timestamp(tag), **info})
        print(f"Patente: Ausgabe {tag} gelesen ({info['patente']} Patente)", flush=True)
    if neu:
        zusatz = pd.DataFrame(neu)
        ausgaben = pd.concat([ausgaben, zusatz], ignore_index=True) if len(ausgaben) else zusatz
        erteilt = pd.concat([erteilt] + neue_zeilen, ignore_index=True) if len(erteilt) else pd.concat(neue_zeilen, ignore_index=True)
    if ausgaben.empty or erteilt.empty:
        raise RuntimeError("keine Ausgabe des Amtsblatts gelesen: " + "; ".join([f"{t} ({g})" for t, g in fehlend[:3]] + hinweise[:3]))
    ausgaben["tag"] = pd.to_datetime(ausgaben["tag"])
    ausgaben = ausgaben.sort_values("tag").reset_index(drop=True)
    ablage.schreibe_bereinigt(TABELLE_AUSGABEN, "alle", ausgaben)
    erteilt = erteilt.sort_values(["tag", "nummer", "inhaber"], kind="stable").reset_index(drop=True)
    geaendert = {pd.Timestamp(z["tag"]).year for z in neu}
    for jahr, teil in erteilt.groupby(erteilt["tag"].dt.year):
        if int(jahr) in geaendert or not (ablage.bereinigt / f"bereinigt__{TABELLE_ERTEILT}__{int(jahr)}.parquet").exists():
            ablage.schreibe_bereinigt(TABELLE_ERTEILT, str(int(jahr)), teil)

    je_inhaber = erteilt.groupby("inhaber", as_index=False).agg(patente=("nummer", "nunique"))
    zuordnung, unbekannt = ordne_zu(je_inhaber, firmen)
    ablage.schreibe_bereinigt(TABELLE_ZUORDNUNG, "alle", zuordnung)
    parameter = baue_parameter(erteilt, zuordnung)
    ablage.schreibe_parameter("uspto_patente", parameter)

    if abgebrochen and modus == "rueckwaerts":
        merke_fortsetzung(ablage.wurzel, "uspto_patente")
    juengste = ausgaben["tag"].max().date()
    offen = [t for t in ausgabetage(heute) if t not in set(ausgaben["tag"].dt.date)]
    # die Ausgabe eines Dienstags erscheint im Lauf des Tages; ältere fehlende Ausgaben sind ein Befund
    spaet = [f"{t} ({g})" for t, g in fehlend if (heute - t).days >= 2]
    if spaet:
        hinweise.append("nicht gelesen: " + "; ".join(spaet[:5]) + (" …" if len(spaet) > 5 else ""))
    if unbekannt:
        hinweise.append("Mütter der Töchterliste ohne eindeutigen Treffer bei EDGAR: " + ", ".join(unbekannt))
    quote = trefferquote(zuordnung, gewicht=zuordnung["patente"].astype("float64"))
    mit_kuerzel = zuordnung["cik"].isin(set(firmen.loc[firmen["tickers"].notna(), "cik"].astype(int)))
    anteil_boerse = float(zuordnung.loc[mit_kuerzel, "patente"].sum() / max(zuordnung["patente"].sum(), 1))
    hinweise.append(f"Zuordnung: {quote.get('quote', 0):.1%} der Inhabernamen, {quote.get('quote_gewichtet', 0):.1%} der "
                    f"Patente; {anteil_boerse:.1%} der Patente bei Firmen mit Börsenkürzel")
    info = {"ausgaben_gelesen": int(len(ausgaben)), "ausgaben_neu": [z["tag"].date().isoformat() for z in neu],
            "ausgaben_offen": len(offen), "juengste_ausgabe": juengste.isoformat(), "tage_seit_ausgabe": (heute - juengste).days,
            "patente": int(ausgaben["patente"].sum()), "erfindungspatente": int(ausgaben["erfindungspatente"].sum()),
            "inhaber": int(len(zuordnung)), "firmen": int(parameter["cik"].nunique()) if len(parameter) else 0,
            "anteil_boerse": round(anteil_boerse, 4), "trefferquote": quote}
    return parameter, info, hinweise
