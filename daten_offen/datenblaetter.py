"""Erzeugt DATENBLAETTER.md aus der Registratur: ``python -m daten_offen.datenblaetter > DATENBLAETTER.md``."""
from __future__ import annotations

from .kern.schema import REGISTRATUR
from .quellen import (cfpb, edgar_13f, edgar_ereignisse, edgar_insider, edgar_rollen, edgar_xbrl,  # noqa: F401
                      fred, klinik, sec_ftd, usaspending, uspto_patente, uspto_zitate, wikipedia)  # die Module registrieren ihre Parameter


def text() -> str:
    zeilen = ["# Datenblätter", "",
              "Automatisch aus dem Code erzeugt. Jede Zeile der Parameter-Tabellen trägt eine dieser IDs.", ""]
    for pid in sorted(REGISTRATUR):
        p = REGISTRATUR[pid]
        zeilen += [f"## {p.id} {p.name}", "",
                   "| Angabe | Inhalt |", "|---|---|",
                   f"| Definition | {p.definition} |", f"| Einheit | {p.einheit} |",
                   f"| Frequenz | {p.frequenz} |", f"| Offenlegung | {p.offenlegung} |",
                   f"| Quelle | {p.quelle} |", f"| Lizenz | {p.lizenz} |",
                   f"| Historie ab | {p.historie_ab} |", f"| Verzögerung | {p.verzoegerung} |",
                   f"| Bekannte Schwächen | {p.schwaechen or '–'} |", ""]
    return "\n".join(zeilen)


if __name__ == "__main__":
    print(text())
