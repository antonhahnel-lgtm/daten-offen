"""Prüfungen je Lauf: Abdeckung, Lücken, Ausreißer, Dubletten, Stichtag, Abweichung zum Vorlauf."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import REGISTRATUR


def pruefe_parameter(df: pd.DataFrame, vorlauf: dict | None = None) -> tuple[list[dict], list[str]]:
    """Prüft eine Parameter-Tabelle. Gibt Kennzahlen je Parameter und die Liste schwerer Fehler zurück."""
    kennzahlen, schwer = [], []
    vorlauf = vorlauf or {}
    if df.empty:
        return kennzahlen, ["keine Zeilen"]
    for pid, teil in df.groupby("parameter_id", sort=True):
        dubletten = int(teil.duplicated(["cik", "ereignis_zeit", "stand", "wert"]).sum())
        w = teil["wert"].to_numpy(dtype="float64")
        streuung = np.nanstd(w)
        ausreisser = int((np.abs(w - np.nanmean(w)) > 10 * streuung).sum()) if streuung > 0 else 0
        unendlich = int(np.isinf(w).sum())
        reg = REGISTRATUR.get(pid)
        stichtag = 0
        if reg is not None and reg.ereignis_vor_verfuegbar:
            stichtag = int((teil["ereignis_zeit"] > teil["verfuegbar_ab"]).sum())
        zeilen = len(teil)
        vor = vorlauf.get(pid, {}).get("zeilen")
        abweichung = None if not vor else round(zeilen / vor - 1, 4)
        kennzahlen.append({
            "parameter_id": pid, "zeilen": zeilen, "firmen": int(teil["cik"].nunique()),
            "von": teil["verfuegbar_ab"].min().strftime("%Y-%m-%d"),
            "bis": teil["verfuegbar_ab"].max().strftime("%Y-%m-%d"),
            "dubletten": dubletten, "ausreisser": ausreisser, "unendlich": unendlich,
            "stichtagsverstoesse": stichtag, "abweichung_vorlauf": abweichung,
        })
        if stichtag:
            schwer.append(f"{pid}: {stichtag} Werte mit ereignis_zeit nach verfuegbar_ab")
        if unendlich:
            schwer.append(f"{pid}: {unendlich} unendliche Werte")
        if dubletten > 0.01 * zeilen:
            schwer.append(f"{pid}: {dubletten} Dubletten")
        if abweichung is not None and abweichung < -0.2:
            schwer.append(f"{pid}: Zeilenzahl {abweichung:+.0%} gegenüber Vorlauf")
    return kennzahlen, schwer


def schreibe_bericht(pfad: Path, quelle: str, kennzahlen: list[dict], schwer: list[str],
                     hinweise: list[str] | None = None) -> None:
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    zeilen = [f"# Prüfbericht {quelle}", "", f"Status: {'FEHLER' if schwer else 'in Ordnung'}", ""]
    if schwer:
        zeilen += ["## Schwere Fehler", ""] + [f"- {s}" for s in schwer] + [""]
    if hinweise:
        zeilen += ["## Hinweise", ""] + [f"- {h}" for h in hinweise] + [""]
    if kennzahlen:
        spalten = list(kennzahlen[0].keys())
        zeilen += ["## Kennzahlen je Parameter", "", "| " + " | ".join(spalten) + " |",
                   "|" + "---|" * len(spalten)]
        for k in kennzahlen:
            zeilen.append("| " + " | ".join("" if k[s] is None else str(k[s]) for s in spalten) + " |")
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    pfad.with_suffix(".json").write_text(
        json.dumps({"quelle": quelle, "schwer": schwer, "hinweise": hinweise or [],
                    "kennzahlen": {k["parameter_id"]: k for k in kennzahlen}}, indent=2, ensure_ascii=False),
        encoding="utf-8")


def lies_vorlauf(pfad: Path) -> dict:
    pfad = Path(pfad)
    if not pfad.exists():
        return {}
    try:
        return json.loads(pfad.read_text(encoding="utf-8")).get("kennzahlen", {})
    except (json.JSONDecodeError, OSError):
        return {}
