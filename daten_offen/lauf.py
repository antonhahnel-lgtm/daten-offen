"""Einstieg je Quelle: ``python -m daten_offen.lauf --quelle <name> --modus laufend|rueckwaerts``.

Schreibt Ergebnisse, Manifest und Prüfbericht nach ``--ausgabe``. Bei schweren Fehlern werden die
Parameter-Dateien der Quelle entfernt (der letzte gute Stand im Release bleibt bestehen) und der
Lauf endet mit Code 1; andere Quellen sind davon nicht betroffen.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

import pandas as pd

from .kern.ablage import Ablage
from .kern.pruefung import lies_vorlauf, pruefe_parameter, schreibe_bericht
from .quellen import (cfpb, edgar_13f, edgar_ereignisse, edgar_index, edgar_insider, edgar_rollen, edgar_xbrl, fred,
                      klinik, sec_ftd, usaspending, wikipedia)

QUELLEN = ("edgar_index", "edgar_insider", "edgar_ereignisse", "edgar_xbrl", "edgar_rollen", "cfpb", "klinik", "fred",
           "wikipedia", "sec_ftd", "edgar_13f", "usaspending")
# Bereinigte Tabellen, die bei einem schweren Fehler der Quelle nicht veröffentlicht werden dürfen
VERWIRF_BEI_FEHLER = {"edgar_index": ("edgar_meldungen", "edgar_firmen")}


def _fuehre_aus(args, ablage: Ablage) -> tuple[pd.DataFrame | None, dict, list[str], list[str]]:
    arbeits = Path(args.arbeits)
    if args.quelle == "edgar_index":
        info, schwer, hinweise = edgar_index.lauf(ablage, arbeits, args.ab_jahr, zip_pfad=args.submissions_zip)
        return None, info, schwer, hinweise
    if args.quelle == "edgar_insider":
        parameter, info, hinweise = edgar_insider.lauf(ablage, arbeits, args.ab_jahr, lokal=args.insider_ordner)
        schwer = []
        if not info.get("unvollstaendig"):
            if info["zeilen"] == 0:
                schwer.append("keine Geschäfte nach Bereinigung")
            if info["fehlende_quartale"] and not args.insider_ordner:
                schwer.append(f"Quartale fehlen: {', '.join(info['fehlende_quartale'])}")
            if info["unplausible_daten"] > 0.02 * max(info["zeilen_roh"], 1):
                schwer.append(f"{info['unplausible_daten']} Geschäfte mit unplausiblem Datum (über 2 %)")
            hinweise.append(f"Nachtrags-Dubletten entfernt: {info['nachtrags_dubletten']}; "
                            f"unplausible Daten verworfen: {info['unplausible_daten']}; "
                            f"ohne Annahmezeit: {info['ohne_annahmezeit']}")
            return parameter, info, schwer, hinweise
        return None, info, schwer, hinweise
    if args.quelle == "edgar_ereignisse":
        return edgar_ereignisse.lauf(ablage), {}, [], []
    if args.quelle == "edgar_xbrl":
        parameter, info, hinweise = edgar_xbrl.lauf(ablage, arbeits, zip_pfad=args.companyfacts_zip)
        schwer = []
        verzeichnis_da = not any("Meldungsverzeichnis fehlt" in h for h in hinweise)
        if verzeichnis_da and info["ohne_annahmezeit"] > 0.05 * max(info["berichte"], 1):
            schwer.append(f"{info['ohne_annahmezeit']} von {info['berichte']} Berichten ohne Annahmezeit im "
                          "Meldungsverzeichnis (über 5 %)")
        hinweise.append(f"Aktienzahl-Sprünge mit Split-Verdacht verworfen: {info['split_verdacht']}")
        return parameter, info, schwer, hinweise
    if args.quelle == "edgar_rollen":
        parameter, info, hinweise = edgar_rollen.lauf(ablage, modus=args.modus)
        schwer = []
        gelesen, ohne = info.get("gelesen", 0), info.get("ohne_rolle", 0)
        if gelesen + ohne >= 50 and ohne > 0.2 * (gelesen + ohne):
            schwer.append(f"{ohne} von {gelesen + ohne} Meldungsköpfen ohne erkennbare Rolle (über 20 %)")
        return parameter, info, schwer, hinweise
    if args.quelle == "cfpb":
        parameter, info, hinweise = cfpb.lauf(ablage, arbeits, zip_pfad=args.cfpb_zip)
        schwer = []
        if info["trefferquote"].get("quote_gewichtet", 0) < 0.2:
            schwer.append("Namensabgleich ordnet weniger als 20 % der Beschwerden zu")
        return parameter, info, schwer, hinweise
    if args.quelle == "klinik":
        parameter, info, hinweise = klinik.lauf(ablage, arbeits)
        schwer = []
        for name, q in info["trefferquote"].items():
            if q["zeilen"] >= 100 and q["quote"] < 0.1:
                schwer.append(f"Namensabgleich {name} ordnet weniger als 10 % zu")
        return parameter, info, schwer, hinweise
    if args.quelle == "sec_ftd":
        parameter, info, hinweise = sec_ftd.lauf(ablage, arbeits, modus=args.modus, lokal=args.ftd_ordner)
        schwer = []
        if not args.ftd_ordner and info["dateien_verzeichnis"] < 300:
            schwer.append(f"Datenseite nennt nur {info['dateien_verzeichnis']} Dateien (erwartet über 400)")
        if info["nachsatz_abweichung"] > 0.02 * max(info["zeilen_neu"], 1):
            schwer.append(f"{info['nachsatz_abweichung']} Zeilen weichen von der Satzzahl der Dateien ab (über 2 %)")
        if info["trefferquote"]["zeilen"] >= 100 and info["trefferquote"]["quote"] < 0.2:
            schwer.append("Zuordnung trifft weniger als 20 % der aktiven Stammaktien")
        return parameter, info, schwer, hinweise
    if args.quelle == "edgar_13f":
        parameter, info, hinweise = edgar_13f.lauf(ablage, arbeits, modus=args.modus, lokal=args.f13_ordner,
                                                   pruefe_quartal=args.f13_pruefquartal or None)
        schwer = []
        if info["trefferquote"]["zeilen"] >= 100 and info["trefferquote"].get("quote_gewichtet", 0) < 0.3:
            schwer.append("CUSIP-Zuordnung trifft weniger als 30 % der Halterpositionen")
        for name, e in info.get("einzelmeldungen", {}).items():
            if not e["vollstaendig"]:
                schwer.append(f"{name}: Frist abgelaufen, aber die Einzelmeldungen sind unvollständig ({e['status']})")
        v = info.get("vergleich")
        if v and (not v.get("vollstaendig") or v.get("halter_gleich", 0) < 0.95):
            schwer.append(f"Gegenprobe {v['quartal']}: Einzelmeldungen und Datensatz stimmen nicht überein")
        return parameter, info, schwer, hinweise
    if args.quelle == "usaspending":
        parameter, info, hinweise = usaspending.lauf(ablage, arbeits, modus=args.modus, lokal=args.usaspending_ordner)
        schwer = []
        if info["trefferquote"]["zeilen"] >= 100 and info["trefferquote"].get("quote_gewichtet", 0) < 0.2:
            schwer.append("Namensabgleich ordnet weniger als 20 % des Auftragsvolumens zu")
        if info["zeilen_quelle"] and info["ohne_datum"] > 0.02 * info["zeilen_quelle"]:
            schwer.append(f"{info['ohne_datum']} Transaktionen ohne lesbares Auftragsdatum (über 2 %)")
        return parameter, info, schwer, hinweise
    if args.quelle == "fred":
        parameter, info, hinweise = fred.lauf(ablage)
        return parameter, info, [], hinweise
    if args.quelle == "wikipedia":
        parameter, info, hinweise = wikipedia.lauf(ablage)
        return parameter, info, [], hinweise
    raise ValueError(f"unbekannte Quelle: {args.quelle}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quelle", required=True, choices=QUELLEN)
    p.add_argument("--modus", default="laufend", choices=("laufend", "rueckwaerts"))
    p.add_argument("--ausgabe", default="ausgabe")
    p.add_argument("--arbeits", default="arbeit")
    p.add_argument("--ab-jahr", type=int, default=2006)
    p.add_argument("--vorlauf", default=None, help="Ordner mit den Prüfberichten (JSON) des letzten Laufs")
    p.add_argument("--submissions-zip", default=None, help="lokale Sammeldatei statt Abruf (Tests)")
    p.add_argument("--insider-ordner", default=None, help="lokaler Ordner mit Quartalsarchiven statt Abruf (Tests)")
    p.add_argument("--companyfacts-zip", default=None, help="lokale Sammeldatei der Abschlüsse statt Abruf (Tests)")
    p.add_argument("--cfpb-zip", default=None, help="lokale Beschwerdedatei statt Abruf (Tests)")
    p.add_argument("--ftd-ordner", default=None, help="lokaler Ordner mit Lieferausfall-Archiven statt Abruf (Tests)")
    p.add_argument("--f13-ordner", default=None, help="lokaler Ordner mit 13F-Datensätzen statt Abruf (Tests)")
    p.add_argument("--usaspending-ordner", default=None, help="lokaler Ordner mit Auftragsdateien statt Abruf (Tests)")
    p.add_argument("--f13-pruefquartal", default=os.environ.get("F13_PRUEFQUARTAL", ""),
                   help="Gegenprobe: dieses Quartal (z. B. 2026q2) zusätzlich aus den Einzelmeldungen lesen")
    args = p.parse_args(argv)

    ablage = Ablage(Path(args.ausgabe))
    bericht = ablage.berichte / f"pruefbericht__{args.quelle}.md"
    try:
        parameter, info, schwer, hinweise = _fuehre_aus(args, ablage)
    except Exception as fehler:  # jede Störung einer Quelle wird gemeldet, nicht verschluckt
        traceback.print_exc()
        schreibe_bericht(bericht, args.quelle, [], [f"Abbruch: {type(fehler).__name__}: {fehler}"])
        return 1

    kennzahlen: list[dict] = []
    if parameter is not None:
        vorlauf = lies_vorlauf(Path(args.vorlauf) / bericht.with_suffix(".json").name) if args.vorlauf else {}
        kennzahlen, schwer_p = pruefe_parameter(parameter, vorlauf)
        schwer = schwer + schwer_p
    hinweise = hinweise + [f"{k}: {v}" for k, v in info.items()]
    schreibe_bericht(bericht, args.quelle, kennzahlen, schwer, hinweise)
    ablage.schreibe_manifest(args.quelle, {"modus": args.modus, "info": info})
    print(bericht.read_text(encoding="utf-8"))
    if schwer:
        for pfad in ablage.parameter.glob(f"parameter__{args.quelle}__*.parquet"):
            pfad.unlink()
        for tabelle in VERWIRF_BEI_FEHLER.get(args.quelle, ()):
            for pfad in ablage.bereinigt.glob(f"bereinigt__{tabelle}__*.parquet"):
                pfad.unlink()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
