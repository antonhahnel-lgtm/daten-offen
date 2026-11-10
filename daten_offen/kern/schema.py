"""Festes Schema der Parameter-Tabellen und Registratur der gebauten Parameter."""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

PARAM_SPALTEN = ["cik", "parameter_id", "ereignis_zeit", "verfuegbar_ab", "wert", "stand"]
ID_MUSTER = re.compile(r"^[A-Z]{2}\d-\d{2}$")
MARKT_CIK = 0  # Parameter ohne Firmenbezug (Markt, Makro) tragen cik = 0


@dataclass(frozen=True)
class Parameter:
    id: str
    name: str
    definition: str
    einheit: str
    frequenz: str
    offenlegung: str
    quelle: str
    lizenz: str
    historie_ab: str
    verzoegerung: str
    schwaechen: str
    ereignis_vor_verfuegbar: bool = True  # ereignis_zeit darf nicht nach verfuegbar_ab liegen


REGISTRATUR: dict[str, Parameter] = {}


def registriere(*parameter: Parameter) -> None:
    for p in parameter:
        if not ID_MUSTER.match(p.id):
            raise ValueError(f"ungültige Parameter-ID: {p.id}")
        if p.id in REGISTRATUR and REGISTRATUR[p.id] != p:
            raise ValueError(f"Parameter-ID doppelt vergeben: {p.id}")
        REGISTRATUR[p.id] = p


def als_parameter(df: pd.DataFrame) -> pd.DataFrame:
    """Bringt eine Tabelle in das feste Schema und prüft die Grundregeln.

    Zeilen ohne Wert werden verworfen; fehlende Schlüssel führen zum Abbruch.
    """
    fehlend = [s for s in PARAM_SPALTEN if s not in df.columns]
    if fehlend:
        raise ValueError(f"Spalten fehlen: {fehlend}")
    aus = df[PARAM_SPALTEN].copy()
    aus["wert"] = pd.to_numeric(aus["wert"], errors="coerce").astype("float64")
    aus = aus[aus["wert"].notna()]
    for s in ("cik", "parameter_id", "verfuegbar_ab", "ereignis_zeit"):
        if aus[s].isna().any():
            raise ValueError(f"Leere Werte in Pflichtspalte {s}")
    aus["cik"] = aus["cik"].astype("int64")
    aus["parameter_id"] = aus["parameter_id"].astype(str)
    aus["stand"] = aus["stand"].fillna("").astype(str)
    for s in ("ereignis_zeit", "verfuegbar_ab"):
        aus[s] = pd.to_datetime(aus[s], utc=True).astype("datetime64[us, UTC]")
    unbekannt = sorted(set(aus["parameter_id"]) - set(REGISTRATUR))
    if unbekannt:
        raise ValueError(f"Nicht registrierte Parameter-IDs: {unbekannt}")
    return aus.sort_values(["parameter_id", "cik", "verfuegbar_ab", "ereignis_zeit"], kind="stable").reset_index(drop=True)


def leer() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cik": pd.Series(dtype="int64"),
            "parameter_id": pd.Series(dtype=str),
            "ereignis_zeit": pd.Series(dtype="datetime64[us, UTC]"),
            "verfuegbar_ab": pd.Series(dtype="datetime64[us, UTC]"),
            "wert": pd.Series(dtype="float64"),
            "stand": pd.Series(dtype=str),
        }
    )
