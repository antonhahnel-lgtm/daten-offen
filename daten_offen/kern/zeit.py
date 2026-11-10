"""Handelskalender (NYSE) und Regel für ``verfuegbar_ab``.

Regel: Ein Wert ist handelbar bekannt
  * zum Annahmezeitpunkt, wenn dieser an einem Handelstag vor Börsenschluss liegt,
  * sonst zur Eröffnung (09:30 ET) des nächsten Handelstags.
Börsenschluss ist 16:00 ET, an verkürzten Tagen 13:00 ET.
Alle gespeicherten Zeitstempel sind UTC.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
EROEFFNUNG = time(9, 30)
SCHLUSS = time(16, 0)
SCHLUSS_VERKUERZT = time(13, 0)

# Außerplanmäßige ganztägige Schließungen der NYSE seit 2001.
SONDERSCHLIESSUNGEN = {
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),
    date(2004, 6, 11),   # Staatstrauer Reagan
    date(2007, 1, 2),    # Staatstrauer Ford
    date(2012, 10, 29), date(2012, 10, 30),  # Hurrikan Sandy
    date(2018, 12, 5),   # Staatstrauer Bush
    date(2025, 1, 9),    # Staatstrauer Carter
}


def ostersonntag(jahr: int) -> date:
    """Gregorianischer Ostersonntag (anonymer Algorithmus)."""
    a = jahr % 19
    b, c = divmod(jahr, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    monat = (h + l - 7 * m + 114) // 31
    tag = (h + l - 7 * m + 114) % 31 + 1
    return date(jahr, monat, tag)


def _n_ter_wochentag(jahr: int, monat: int, wochentag: int, n: int) -> date:
    """n-ter Wochentag (0 = Montag) eines Monats."""
    d = date(jahr, monat, 1)
    versatz = (wochentag - d.weekday()) % 7
    return d + timedelta(days=versatz + 7 * (n - 1))


def _letzter_wochentag(jahr: int, monat: int, wochentag: int) -> date:
    d = date(jahr + (monat == 12), monat % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - wochentag) % 7)


def _beobachtet(d: date) -> date:
    """Samstag -> Freitag davor, Sonntag -> Montag danach."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def feiertage(jahr: int) -> frozenset:
    """Ganztägige NYSE-Feiertage eines Jahres (ohne Sonderschließungen)."""
    tage = set()
    neujahr = date(jahr, 1, 1)
    # Neujahr an einem Samstag wird nicht am Freitag davor begangen.
    if neujahr.weekday() == 6:
        tage.add(date(jahr, 1, 2))
    elif neujahr.weekday() != 5:
        tage.add(neujahr)
    tage.add(_n_ter_wochentag(jahr, 1, 0, 3))      # Martin Luther King
    tage.add(_n_ter_wochentag(jahr, 2, 0, 3))      # Washington's Birthday
    tage.add(ostersonntag(jahr) - timedelta(days=2))  # Karfreitag
    tage.add(_letzter_wochentag(jahr, 5, 0))       # Memorial Day
    if jahr >= 2022:
        tage.add(_beobachtet(date(jahr, 6, 19)))   # Juneteenth
    tage.add(_beobachtet(date(jahr, 7, 4)))        # Independence Day
    tage.add(_n_ter_wochentag(jahr, 9, 0, 1))      # Labor Day
    tage.add(_n_ter_wochentag(jahr, 11, 3, 4))     # Thanksgiving
    tage.add(_beobachtet(date(jahr, 12, 25)))      # Weihnachten
    return frozenset(tage)


def ist_handelstag(d: date) -> bool:
    return d.weekday() < 5 and d not in feiertage(d.year) and d not in SONDERSCHLIESSUNGEN


def naechster_handelstag(d: date) -> date:
    """Erster Handelstag strikt nach ``d``."""
    n = d + timedelta(days=1)
    while not ist_handelstag(n):
        n += timedelta(days=1)
    return n


def handelsschluss(d: date) -> time:
    """Schlusszeit eines Handelstags; 13:00 ET an verkürzten Tagen."""
    thanksgiving = _n_ter_wochentag(d.year, 11, 3, 4)
    if d == thanksgiving + timedelta(days=1):
        return SCHLUSS_VERKUERZT
    if (d.month, d.day) == (12, 24):
        return SCHLUSS_VERKUERZT
    if (d.month, d.day) == (7, 3) and ist_handelstag(d):
        return SCHLUSS_VERKUERZT
    return SCHLUSS


def handelbar_ab(zeitpunkt: datetime) -> datetime:
    """Frühester handelbarer Zeitpunkt (UTC) für eine Information, die zu ``zeitpunkt`` öffentlich wurde."""
    if zeitpunkt.tzinfo is None:
        raise ValueError("Zeitpunkt braucht eine Zeitzone")
    lokal = zeitpunkt.astimezone(ET)
    d = lokal.date()
    if ist_handelstag(d) and lokal.time() < handelsschluss(d):
        return zeitpunkt.astimezone(UTC)
    n = naechster_handelstag(d)
    return datetime.combine(n, EROEFFNUNG, tzinfo=ET).astimezone(UTC)


def handelbar_ab_serie(s: pd.Series) -> pd.Series:
    """Vektorisierte Fassung von :func:`handelbar_ab` für eine UTC-Zeitreihe (NaT bleibt NaT)."""
    s = pd.to_datetime(s, utc=True)
    if s.empty:
        return s
    ok = s.notna()
    lokal = s[ok].dt.tz_convert(ET)
    tage = lokal.dt.date
    eindeutig = sorted(set(tage))
    tabelle = {}
    for d in eindeutig:
        n = naechster_handelstag(d)
        tabelle[d] = (
            ist_handelstag(d),
            handelsschluss(d),
            pd.Timestamp(datetime.combine(n, EROEFFNUNG, tzinfo=ET)).tz_convert("UTC"),
        )
    ist_ht = tage.map(lambda d: tabelle[d][0]).astype(bool)
    schluss_sek = tage.map(lambda d: tabelle[d][1].hour * 3600 + tabelle[d][1].minute * 60)
    sek = lokal.dt.hour * 3600 + lokal.dt.minute * 60 + lokal.dt.second
    naechste = pd.to_datetime(tage.map(lambda d: tabelle[d][2]), utc=True)
    sofort = ist_ht & (sek < schluss_sek)
    ergebnis = s.copy()
    ergebnis[ok] = s[ok].where(sofort, naechste.astype(s.dtype))
    return ergebnis


def monatsende_handelbar(jahr: int, monat: int) -> datetime:
    """Eröffnung des ersten Handelstags nach Monatsende (für Monatsaggregate)."""
    letzter = date(jahr + (monat == 12), monat % 12 + 1, 1) - timedelta(days=1)
    n = naechster_handelstag(letzter)
    return datetime.combine(n, EROEFFNUNG, tzinfo=ET).astimezone(UTC)
