"""Namensabgleich: ordnet Firmennamen fremder Quellen (Arbeitgeber, Auftragnehmer, Anmelder, Beklagte)
einer CIK zu. Jede Zuordnung trägt eine Konfidenz; die Trefferquote je Quelle gehört in den Prüfbericht.

Stufen:
  1,00  bereinigter Name stimmt exakt (aktueller Name)
  0,95  bereinigter Name stimmt exakt mit einem früheren Namen
  0,90  Übereinstimmung nach Entfernen von Zusätzen wie HOLDINGS oder GROUP
  <0,90 ähnlichster Name bei gleichem Anfangswort, Ähnlichkeit ab 0,92 und eindeutig bester Treffer
Mehrdeutige Namen werden nicht zugeordnet, außer genau eine der Firmen hat einen Börsenticker.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

import pandas as pd

RECHTSFORM = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "LLC", "LP", "LLP",
              "PLC", "SA", "AG", "NV", "SE", "BV", "GMBH", "TRUST"}
ZUSATZ = {"HOLDINGS", "HOLDING", "GROUP", "INTERNATIONAL", "INTL", "GLOBAL", "ENTERPRISES", "WORLDWIDE", "USA", "US"}
STAAT = re.compile(r"/[A-Z]{2,3}/?\s*$")          # EDGAR hängt teils den Gründungsstaat an: "ALPHA CORP /DE/"
ZEICHEN = re.compile(r"[^A-Z0-9 ]+")
MINDEST_AEHNLICHKEIT = 0.92


def bereinige(name: str | None) -> str:
    """Großschreibung, ohne Satzzeichen, ohne Rechtsform am Ende und ohne führendes THE."""
    if not isinstance(name, str):
        return ""
    t = STAAT.sub("", name.upper().strip())
    t = t.replace("&", " AND ").replace("'", "")
    woerter = ZEICHEN.sub(" ", t).split()
    if woerter and woerter[0] == "THE":
        woerter = woerter[1:]
    while len(woerter) > 1 and woerter[-1] in RECHTSFORM:
        woerter.pop()
    return " ".join(woerter)


def kern(name_bereinigt: str) -> str:
    """Bereinigter Name ohne allgemeine Zusätze (HOLDINGS, GROUP ...)."""
    woerter = [w for w in name_bereinigt.split() if w not in ZUSATZ and w not in RECHTSFORM]
    return " ".join(woerter)


class Namensabgleich:
    def __init__(self, firmen: pd.DataFrame):
        """``firmen``: Spalten cik, name; optional tickers und fruehere_namen (JSON-Liste mit Feld name)."""
        self.exakt: dict[str, set[int]] = {}
        self.frueher: dict[str, set[int]] = {}
        self.kerne: dict[str, set[int]] = {}
        self.nach_anfang: dict[str, list[tuple[str, int]]] = {}
        self.mit_ticker: set[int] = set()
        hat_ticker = "tickers" in firmen.columns
        hat_frueher = "fruehere_namen" in firmen.columns
        for z in firmen.itertuples(index=False):
            cik = int(z.cik)
            if hat_ticker and isinstance(z.tickers, str) and z.tickers:
                self.mit_ticker.add(cik)
            n = bereinige(z.name)
            if n:
                self.exakt.setdefault(n, set()).add(cik)
                k = kern(n)
                if k:
                    self.kerne.setdefault(k, set()).add(cik)
                self.nach_anfang.setdefault(n.split()[0], []).append((n, cik))
            if hat_frueher and isinstance(z.fruehere_namen, str) and z.fruehere_namen not in ("", "[]"):
                try:
                    alte = json.loads(z.fruehere_namen)
                except ValueError:
                    alte = []
                for a in alte:
                    m = bereinige(a.get("name") if isinstance(a, dict) else a)
                    if m and m != n:
                        self.frueher.setdefault(m, set()).add(cik)

    def _eindeutig(self, ciks: set[int] | None) -> int | None:
        if not ciks:
            return None
        if len(ciks) == 1:
            return next(iter(ciks))
        boerse = ciks & self.mit_ticker
        return next(iter(boerse)) if len(boerse) == 1 else None

    def finde(self, name: str | None) -> tuple[int | None, float, str]:
        """(cik, konfidenz, art) – art: exakt, frueher, kern, aehnlich, mehrdeutig, keiner."""
        n = bereinige(name)
        if not n:
            return None, 0.0, "keiner"
        for tabelle, konfidenz, art in ((self.exakt, 1.0, "exakt"), (self.frueher, 0.95, "frueher")):
            if n in tabelle:
                cik = self._eindeutig(tabelle[n])
                return (cik, konfidenz, art) if cik is not None else (None, 0.0, "mehrdeutig")
        k = kern(n)
        if k and k in self.kerne:
            cik = self._eindeutig(self.kerne[k])
            return (cik, 0.90, "kern") if cik is not None else (None, 0.0, "mehrdeutig")
        beste, zweite, beste_cik = 0.0, 0.0, None
        for kandidat, cik in self.nach_anfang.get(n.split()[0], ()):
            if abs(len(kandidat) - len(n)) > 0.2 * max(len(n), 1) + 2:
                continue
            a = SequenceMatcher(None, n, kandidat).ratio()
            if a > beste:
                if cik != beste_cik:
                    zweite = beste
                beste, beste_cik = a, cik
            elif a > zweite and cik != beste_cik:
                zweite = a
        if beste >= MINDEST_AEHNLICHKEIT and beste - zweite >= 0.03:
            return beste_cik, round(0.89 * beste, 3), "aehnlich"
        return None, 0.0, "keiner"

    def ordne_zu(self, namen: pd.Series) -> pd.DataFrame:
        """Zuordnung für eine Namensspalte (gleicher Index); jeder verschiedene Name wird einmal gesucht."""
        eindeutige = {n: self.finde(n) for n in pd.unique(namen.dropna())}
        leer = (None, 0.0, "keiner")
        treffer = [eindeutige.get(n, leer) for n in namen]
        aus = pd.DataFrame(treffer, columns=["cik", "konfidenz", "art"], index=namen.index)
        aus["cik"] = aus["cik"].astype("Int64")
        return aus


def trefferquote(zuordnung: pd.DataFrame, gewicht: pd.Series | None = None) -> dict:
    """Anteil zugeordneter Zeilen, optional gewichtet (z. B. mit dem Auftragswert), und Verteilung der Arten."""
    zugeordnet = zuordnung["cik"].notna()
    aus = {"zeilen": int(len(zuordnung)), "quote": round(float(zugeordnet.mean()), 4) if len(zuordnung) else 0.0,
           "arten": zuordnung["art"].value_counts().to_dict()}
    if gewicht is not None and float(gewicht.sum()) > 0:
        aus["quote_gewichtet"] = round(float(gewicht[zugeordnet].sum() / gewicht.sum()), 4)
    return aus
