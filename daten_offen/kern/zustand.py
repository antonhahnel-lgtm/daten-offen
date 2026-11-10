"""Fortsetzbarer Stand eines Laufs und Zeitbudget (6-Stunden-Grenze je GitHub-Job)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


class Zustand:
    def __init__(self, pfad: Path):
        self.pfad = Path(pfad)
        self.daten: dict = {}
        if self.pfad.exists():
            self.daten = json.loads(self.pfad.read_text(encoding="utf-8"))

    def hole(self, schluessel: str, vorgabe=None):
        return self.daten.get(schluessel, vorgabe)

    def setze(self, schluessel: str, wert) -> None:
        self.daten[schluessel] = wert
        self.speichere()

    def speichere(self) -> None:
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        vorlaeufig = self.pfad.with_suffix(".teil")
        vorlaeufig.write_text(json.dumps(self.daten, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        vorlaeufig.replace(self.pfad)


class Zeitbudget:
    """Meldet, wann ein Lauf abbrechen und sich fortsetzen lassen muss."""

    def __init__(self, minuten: float | None = None):
        if minuten is None:
            minuten = float(os.environ.get("ZEITBUDGET_MIN", "300"))
        self.ende = time.monotonic() + minuten * 60

    def abgelaufen(self) -> bool:
        return time.monotonic() >= self.ende


def merke_fortsetzung(ausgabe: Path, quelle: str) -> None:
    """Legt eine Markierung ab; der Workflow startet die Quelle dann erneut."""
    (Path(ausgabe) / f"FORTSETZEN__{quelle}").write_text("1", encoding="utf-8")
