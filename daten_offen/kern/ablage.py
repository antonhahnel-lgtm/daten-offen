"""Ablage der Ergebnisse als Parquet-Dateien, nach Jahr geteilt, mit Manifest.

Dateinamen sind flach (Release-Assets kennen keine Ordner):
  bereinigt__<tabelle>__<teil>.parquet
  parameter__<quelle>__<jahr>.parquet
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .schema import als_parameter


def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Ablage:
    def __init__(self, wurzel: Path):
        self.wurzel = Path(wurzel)
        self.bereinigt = self.wurzel / "bereinigt"
        self.parameter = self.wurzel / "parameter"
        self.berichte = self.wurzel / "berichte"
        for d in (self.bereinigt, self.parameter, self.berichte):
            d.mkdir(parents=True, exist_ok=True)
        self.eintraege: list[dict] = []

    def _vermerke(self, pfad: Path, zeilen: int, art: str) -> None:
        self.eintraege.append({"datei": pfad.name, "art": art, "zeilen": int(zeilen),
                               "bytes": pfad.stat().st_size, "sha256": _sha256(pfad)})

    def schreibe_bereinigt(self, tabelle: str, teil: str, df: pd.DataFrame) -> Path:
        pfad = self.bereinigt / f"bereinigt__{tabelle}__{teil}.parquet"
        df.to_parquet(pfad, index=False, compression="zstd")
        self._vermerke(pfad, len(df), "bereinigt")
        return pfad

    def schreibe_parameter(self, quelle: str, df: pd.DataFrame) -> list[Path]:
        """Schreibt eine Parameter-Tabelle, geteilt nach dem Jahr von ``verfuegbar_ab``."""
        df = als_parameter(df)
        pfade = []
        if df.empty:
            return pfade
        jahre = df["verfuegbar_ab"].dt.year
        for jahr, teil in df.groupby(jahre, sort=True):
            pfad = self.parameter / f"parameter__{quelle}__{int(jahr)}.parquet"
            teil.to_parquet(pfad, index=False, compression="zstd")
            self._vermerke(pfad, len(teil), "parameter")
            pfade.append(pfad)
        return pfade

    def lies_bereinigt(self, tabelle: str, spalten: list[str] | None = None,
                       filter: list[tuple] | None = None) -> pd.DataFrame:
        """Liest alle Teile einer bereinigten Tabelle; ``spalten`` und ``filter`` begrenzen den Speicherbedarf
        (Filter im Format von pyarrow, z. B. ``[("form", "in", ["4", "8-K"])]``)."""
        dateien = sorted(self.bereinigt.glob(f"bereinigt__{tabelle}__*.parquet"))
        if not dateien:
            return pd.DataFrame()
        teile = [pq.read_table(p, columns=spalten, filters=filter).to_pandas() for p in dateien]
        teile = [t for t in teile if len(t)] or teile[:1]
        return pd.concat(teile, ignore_index=True)

    def schreibe_manifest(self, quelle: str, zusatz: dict | None = None) -> Path:
        manifest = {"quelle": quelle, "erstellt_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "dateien": self.eintraege, **(zusatz or {})}
        pfad = self.berichte / f"manifest__{quelle}.json"
        pfad.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return pfad
