from datetime import date, datetime

import pandas as pd
import pytest

from daten_offen.kern import zeit as z

# Amtlicher NYSE-Kalender (ganztägige Schließungen)
NYSE = {
    2020: ["01-01", "01-20", "02-17", "04-10", "05-25", "07-03", "09-07", "11-26", "12-25"],
    2021: ["01-01", "01-18", "02-15", "04-02", "05-31", "07-05", "09-06", "11-25", "12-24"],
    2022: ["01-17", "02-21", "04-15", "05-30", "06-20", "07-04", "09-05", "11-24", "12-26"],
    2023: ["01-02", "01-16", "02-20", "04-07", "05-29", "06-19", "07-04", "09-04", "11-23", "12-25"],
    2024: ["01-01", "01-15", "02-19", "03-29", "05-27", "06-19", "07-04", "09-02", "11-28", "12-25"],
    2025: ["01-01", "01-20", "02-17", "04-18", "05-26", "06-19", "07-04", "09-01", "11-27", "12-25"],
    2026: ["01-01", "01-19", "02-16", "04-03", "05-25", "06-19", "07-03", "09-07", "11-26", "12-25"],
}


@pytest.mark.parametrize("jahr", sorted(NYSE))
def test_feiertage(jahr):
    assert sorted(d.strftime("%m-%d") for d in z.feiertage(jahr)) == NYSE[jahr]


def test_sonderschliessung_und_wochenende():
    assert not z.ist_handelstag(date(2025, 1, 9))
    assert not z.ist_handelstag(date(2024, 3, 30))
    assert z.naechster_handelstag(date(2024, 3, 28)) == date(2024, 4, 1)


def et(*a):
    return datetime(*a, tzinfo=z.ET)


@pytest.mark.parametrize("ein, aus", [
    (et(2024, 3, 27, 15, 59, 59), et(2024, 3, 27, 15, 59, 59)),   # im Handel
    (et(2024, 3, 27, 16, 0), et(2024, 3, 28, 9, 30)),             # ab Börsenschluss: nächster Handelstag
    (et(2024, 3, 27, 7, 0), et(2024, 3, 27, 7, 0)),               # vorbörslich
    (et(2024, 3, 28, 17, 0), et(2024, 4, 1, 9, 30)),              # vor Karfreitag und Wochenende
    (et(2024, 7, 3, 13, 0), et(2024, 7, 5, 9, 30)),               # verkürzter Tag
    (et(2024, 11, 29, 12, 59), et(2024, 11, 29, 12, 59)),         # verkürzter Tag, vor 13 Uhr
    (et(2024, 12, 24, 14, 0), et(2024, 12, 26, 9, 30)),
    (et(2024, 6, 22, 10, 0), et(2024, 6, 24, 9, 30)),             # Samstag
])
def test_handelbar_ab(ein, aus):
    assert z.handelbar_ab(ein) == aus
    serie = z.handelbar_ab_serie(pd.Series([pd.Timestamp(ein).tz_convert("UTC")]))
    assert serie.iloc[0] == pd.Timestamp(aus)


def test_serie_mit_luecke_und_zeitumstellung():
    s = pd.Series(pd.to_datetime(["2024-03-08T21:30:00Z", None, "2024-03-11T13:00:00Z"], utc=True))
    r = z.handelbar_ab_serie(s)
    assert r.iloc[0] == pd.Timestamp("2024-03-11 09:30", tz=z.ET)   # Sommerzeit beginnt am 10.03.2024
    assert pd.isna(r.iloc[1])
    assert r.iloc[2] == s.iloc[2]


def test_ohne_zeitzone_abgelehnt():
    with pytest.raises(ValueError):
        z.handelbar_ab(datetime(2024, 1, 2, 10, 0))


def test_monatsende():
    assert z.monatsende_handelbar(2024, 3) == et(2024, 4, 1, 9, 30)
    assert z.monatsende_handelbar(2024, 12) == et(2025, 1, 2, 9, 30)
