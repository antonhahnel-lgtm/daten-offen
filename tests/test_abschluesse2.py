"""Lieferung 12: Umsatzwachstum, Nettoverschuldung, Rückkäufe, Dividendenwechsel, Verwässerung, F&E-Erfolgsbilanz,
Lockup-Ablauf und Abspaltung."""
import numpy as np
import pandas as pd
import pytest

from daten_offen.kern.pruefung import pruefe_parameter
from daten_offen.quellen import edgar_ereignisse as e
from daten_offen.quellen import edgar_xbrl as x
from tests.hilfen import QE, QS, Fakten

UMSATZ = {2022: [100, 100, 100, 100], 2023: [110, 120, 130, 140]}
RUECKKAUF = {2022: [5, 5, 15, 20], 2023: [10, 25, 25, 40]}          # aufgelaufen seit Jahresbeginn


def firma() -> Fakten:
    f = Fakten()
    for jahr in (2022, 2023):
        for k in (1, 2, 3, 4):
            ende = f"{jahr}-{QE[k]}"
            accn, form = (f"Q-{jahr}-{k}", "10-Q") if k < 4 else (f"K-{jahr}", "10-K")
            filed = f"{jahr}-{ {1: '05', 2: '08', 3: '11'}[k] }-10" if k < 4 else f"{jahr + 1}-02-20"
            if k < 4:
                f.plus("Revenues", UMSATZ[jahr][k - 1], accn, form, filed, ende, start=f"{jahr}-{QS[k]}")
                if jahr - 1 in UMSATZ:
                    f.plus("Revenues", UMSATZ[jahr - 1][k - 1], accn, form, filed, f"{jahr - 1}-{QE[k]}", start=f"{jahr - 1}-{QS[k]}")
            else:
                f.plus("Revenues", sum(UMSATZ[jahr]), accn, form, filed, ende, start=f"{jahr}-01-01")
            f.plus("PaymentsForRepurchaseOfCommonStock", RUECKKAUF[jahr][k - 1], accn, form, filed, ende, start=f"{jahr}-01-01")
            f.plus("NetCashProvidedByUsedInOperatingActivities", 10 * k, accn, form, filed, ende, start=f"{jahr}-01-01")
            start = f"{jahr}-{QS[k]}" if k < 4 else f"{jahr}-01-01"
            f.plus("WeightedAverageNumberOfSharesOutstandingBasic", 1000, accn, form, filed, ende, start=start, einheit="shares")
            f.plus("WeightedAverageNumberOfDilutedSharesOutstanding", 1040, accn, form, filed, ende, start=start, einheit="shares")
            f.plus("AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount", 60, accn, form, filed, ende,
                   start=start, einheit="shares")
            f.plus("CommonStockDividendsPerShareDeclared", 0.25, accn, form, filed, ende, start=start, einheit="USD/shares")
            f.plus("Assets", 1000, accn, form, filed, ende)
            f.plus("LongTermDebtNoncurrent", 300, accn, form, filed, ende)
            f.plus("CashAndCashEquivalentsAtCarryingValue", 50, accn, form, filed, ende)
            f.plus("ShortTermInvestments", 30, accn, form, filed, ende)
            if k == 4:
                f.plus("EntityPublicFloat", 5000, accn, form, filed, f"{jahr}-06-30", gruppe="dei")
    return f


@pytest.fixture(scope="module")
def ergebnis():
    berichte = pd.DataFrame(x.berichtszeilen(77, firma().json(77)))
    p, info = x.baue_parameter(berichte, pd.DataFrame())
    return berichte.set_index("accn"), p


def wert(p, pid, stand):
    t = p[(p["parameter_id"] == pid) & (p["stand"] == stand)]
    assert len(t) == 1, f"{pid}/{stand}: {len(t)} Zeilen"
    return t["wert"].iloc[0]


def test_neue_felder(ergebnis):
    berichte, _ = ergebnis
    z = berichte.loc["K-2023"]
    assert z["buyback"] == 40 and z["buyback_q"] == 4 and z["dps"] == 0.25 and z["sh_basic"] == 1000 and z["antidil"] == 60
    assert z["streubesitz"] == 5000 and np.isnan(berichte.loc["Q-2023-2", "streubesitz"])
    assert berichte.loc["Q-2023-2", "buyback"] == 25 and berichte.loc["Q-2023-2", "buyback_q"] == 2


def test_wachstum_verschuldung_verwaesserung(ergebnis):
    _, p = ergebnis
    assert wert(p, "UA1-08", "Q-2023-2") == pytest.approx(0.20)                # 120 gegen 100
    assert p[(p["parameter_id"] == "UA1-08") & (p["stand"] == "Q-2022-2")].empty  # ohne Vergleichszahl kein Wert
    assert wert(p, "WR2-02", "Q-2023-1") == pytest.approx((300 - 80) / 1000)
    assert wert(p, "UA3-05", "K-2023") == pytest.approx((60 + 40) / 1000)


def test_rueckkaeufe_zwoelf_monate(ergebnis):
    _, p = ergebnis
    assert wert(p, "UA3-02", "K-2022") == 20 and wert(p, "UA3-02", "K-2023") == 40
    # Halbjahr 2023: Einzelquartale 10 und 15, dazu drittes und viertes Quartal 2022 (10 und 5)
    assert wert(p, "UA3-02", "Q-2023-2") == 40
    assert p[(p["parameter_id"] == "UA3-02") & (p["stand"] == "Q-2022-2")].empty  # noch keine vier Quartale


def test_dividendenwechsel():
    tage = np.arange(12) * 91
    nan = np.full(12, np.nan)
    kasse = np.ones(12)
    # acht Quartale ohne Dividende, dann vier mit: Aufnahme im neunten Bericht, danach nichts mehr
    gezahlt = np.array([0.0] * 8 + [5.0] * 4)
    assert list(np.nan_to_num(x._dividendenwechsel(tage, gezahlt, gezahlt, nan, nan, kasse))) == [0] * 8 + [1] + [0] * 3
    # sechs Quartale mit Dividende, dann keine: Streichung im siebten Bericht (nur dort)
    gezahlt = np.array([5.0] * 6 + [0.0] * 6)
    assert list(np.nan_to_num(x._dividendenwechsel(tage, gezahlt, gezahlt, nan, nan, kasse))) == [0] * 6 + [-1] + [0] * 5
    # nur die erklärte Dividende je Aktie ist bekannt
    je_aktie = np.array([0.25] * 5 + [0.0] * 7)
    assert x._dividendenwechsel(tage, nan, nan, je_aktie, je_aktie, kasse)[5] == -1
    # Jahreszahler (ein Quartal im Jahr): weder Aufnahme noch Streichung
    gezahlt = np.array([5.0, 0, 0, 0] * 3)
    assert np.isnan(x._dividendenwechsel(tage, gezahlt, gezahlt, nan, nan, kasse)).all()
    # ohne Kapitalflussrechnung ist „keine Dividende“ nicht belegt
    gezahlt = np.array([5.0] * 6 + [np.nan] * 6)
    assert np.isnan(x._dividendenwechsel(tage, gezahlt, gezahlt, nan, nan, nan)).all()


def test_erfolgsbilanz():
    rng = np.random.default_rng(7)
    jahre = 14
    tage = np.arange(jahre) * 365
    fue = rng.uniform(5, 30, jahre)
    umsatz = 100 * np.cumprod(1 + rng.uniform(-0.05, 0.25, jahre))
    aus = x._erfolgsbilanz(tage, umsatz, fue)
    assert np.isnan(aus[:10]).all() and not np.isnan(aus[10:]).any()         # elf Jahre in Folge nötig
    # Gegenrechnung für das letzte Jahr
    wachstum = np.log(umsatz[1:] / umsatz[:-1])                               # Wachstum von Jahr t (Index t−1)
    x_ = np.log1p(fue / umsatz)
    steigungen = []
    for abstand in range(1, 6):
        t = [q for q in range(jahre - 1, jahre - 9, -1) if q - abstand >= 0 and q >= 1]
        steigungen.append(np.polyfit([x_[q - abstand] for q in t], [wachstum[q - 1] for q in t], 1)[0])
    assert aus[-1] == pytest.approx(np.mean(steigungen))
    # Lücke in der Jahresfolge oder zu wenige Jahre mit F&E: kein Wert
    assert np.isnan(x._erfolgsbilanz(np.delete(tage, 7), np.delete(umsatz, 7), np.delete(fue, 7))).all()
    assert np.isnan(x._erfolgsbilanz(tage, umsatz, np.where(np.arange(jahre) < 12, 0.0, fue))).all()


def meldungen(zeilen):
    m = pd.DataFrame(zeilen, columns=["cik", "accession", "form", "tag"])
    m["annahme_utc"] = pd.to_datetime(m["tag"]).dt.tz_localize("UTC") + pd.Timedelta(hours=15)
    m["verfuegbar_ab"], m["items"] = m["annahme_utc"], ""
    return m


def test_lockup_und_abspaltung():
    m = meldungen([
        (1, "a1", "10-K", "2006-03-01"), (1, "a2", "424B4", "2010-05-10"),          # etablierte Firma: kein Börsengang
        (2, "b1", "424B4", "2010-06-01"), (2, "b2", "10-Q", "2010-08-10"), (2, "b3", "424B4", "2011-02-01"),
        (3, "c1", "424B1", "2006-06-01"),                                             # Verzeichnis reicht nicht weit genug zurück
        (4, "d1", "10-12B", "2015-01-10"), (4, "d2", "10-12B", "2015-02-01"), (4, "d3", "EFFECT", "2015-06-20"),
        (4, "d4", "EFFECT", "2015-09-01"), (5, "e1", "EFFECT", "2015-06-20"),
    ])
    p = e.baue_parameter(m)
    lockup = p[p["parameter_id"] == "UA4-04"]
    assert lockup[["cik", "stand", "wert"]].values.tolist() == [[2, "b1", 180.0]]
    assert lockup["ereignis_zeit"].iloc[0] == pd.Timestamp("2010-11-28 15:00", tz="UTC")
    assert lockup["verfuegbar_ab"].iloc[0] == pd.Timestamp("2010-06-01 15:00", tz="UTC")
    spin = p[p["parameter_id"] == "UA4-02"].sort_values("wert")
    assert spin[["cik", "stand", "wert"]].values.tolist() == [[4, "d1", 1.0], [4, "d3", 2.0]]
    # der künftige Ablauftag ist kein Stichtagsverstoß
    assert not [s for s in pruefe_parameter(p)[1] if "UA4-04" in s]
