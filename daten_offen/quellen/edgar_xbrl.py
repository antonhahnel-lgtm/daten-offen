"""Abschlussdaten (XBRL) aus der amtlichen Sammeldatei ``companyfacts.zip`` und daraus Fundamentalparameter.

Die Berichtszeilen (eine Zeile je 10-K/10-Q) folgen der im Insider-Monitor erprobten Logik
(``xbrl_rows``): je Größe der Posten mit dem höchsten Vorrang, bei Zeitraumgrößen der kürzeste
verfügbare Zeitraum samt Vorjahreswert aus derselben Einreichung. Darauf bauen hier zusätzlich
Einzelquartale, Zwölfmonatswerte und Jahresvergleiche auf.

Stichtag: Ein Bericht gilt ab der Annahme seiner Einreichung (10-Q/10-K) als bekannt. Die
Ergebnis-Pressemitteilung (8-K Item 2.02) erscheint oft Tage früher, enthält aber keine
strukturierten Zahlen; die Parameter sind deshalb eher zu spät als zu früh datiert.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from ..kern.ablage import Ablage
from ..kern.http import Abruf
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab_serie

SAMMEL_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
DATEI_MUSTER = re.compile(r"^CIK(\d{10})\.json$")
TABELLE = "edgar_abschluesse"

# Reihenfolge = Vorrang: der erste vorhandene Posten gewinnt. Die ersten Gruppen stammen
# unverändert aus dem Insider-Monitor (FIN_TAGS); die weiteren kommen für die Kennzahlen hinzu.
ZEITRAUM = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "SalesRevenueNet",
                "SalesRevenueGoodsNet", "RevenuesNetOfInterestExpense", "GrossInvestmentIncomeOperating",
                "InvestmentIncomeOperating"],
    "rev_int": ["InterestIncomeExpenseNet", "InterestAndDividendIncomeOperating",
                "InterestIncomeExpenseAfterProvisionForLoanLoss"],
    "rev_nonint": ["NoninterestIncome"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "op_cf": ["NetCashProvidedByUsedInOperatingActivities",
              "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"],
    "gross_profit": ["GrossProfit"],
    "sga": ["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"],
    "rnd": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "adv": ["AdvertisingExpense", "MarketingAndAdvertisingExpense"],
    "dep": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "Depreciation"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "div": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends", "PaymentsOfOrdinaryDividends"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
}
STICHTAG = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "sti": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "OtherShortTermInvestments"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt", "DebtLongtermAndShorttermCombinedAmount"],
    "assets": ["Assets"],
    "equity": ["StockholdersEquity"],
    "shares": ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding",
               "WeightedAverageNumberOfSharesOutstandingBasic"],
    "assets_cur": ["AssetsCurrent"],
    "liab_cur": ["LiabilitiesCurrent"],
    "recv": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
}
FELDER = {**ZEITRAUM, **STICHTAG}
QUARTALE = {"Q": 1, "H": 2, "T": 3, "Y": 4}
BERICHTSFORMEN = ("10-K", "10-Q")
TAG_JAHR = 365
SPLIT_GRENZE = 3.0  # Sprung der Aktienzahl über Faktor 3: vermutlich Split, kein Emissionssignal

_Q = "SEC EDGAR, Sammeldatei companyfacts.zip (https://www.sec.gov/search-filings/edgar-application-programming-interfaces)"
_L = "gemeinfrei (US-Behörde)"
_G = "gesetzlich: Form 10-K (jährlich) und 10-Q (quartalsweise), XBRL-Pflicht"


def _p(id_, name, definition, einheit, schwaechen="", frequenz="je Quartalsbericht"):
    return Parameter(id=id_, name=name, definition=definition, einheit=einheit, frequenz=frequenz,
                     offenlegung=_G, quelle=_Q, lizenz=_L, historie_ab="2009 (große Firmen), 2011 (alle)",
                     verzoegerung="Annahmezeit des 10-Q/10-K (aus edgar_index); die Pressemitteilung ist oft früher",
                     schwaechen=schwaechen)


registriere(
    _p("UA1-01", "Gewinnüberraschung (SUE)",
       "Quartalsgewinn minus Gewinn des Vorjahresquartals, geteilt durch die Streuung dieser Differenz über "
       "die acht Vorquartale (mindestens vier); saisonaler Random Walk ohne Analystendaten", "Standardabweichungen",
       schwaechen="Nettogewinn statt Gewinn je Aktie; Sondereffekte nicht bereinigt"),
    _p("UA1-02", "Zahlenlage",
       "+1 positiv (Umsatz über 2 % über Vorjahr, Gewinn, operativer Cashflow nicht negativ), −1 negativ "
       "(Umsatz über 2 % unter Vorjahr, kein Gewinn), 0 gemischt; Definition fin_lage_roh des Insider-Monitors",
       "Stufe −1/0/+1",
       schwaechen="Die Sperren des Insider-Monitors (junger Börsengang, durch 8-K überholt) werden dort angewandt"),
    _p("UA1-03", "Accruals", "(Gewinn − operativer Cashflow) der letzten zwölf Monate / Bilanzsumme", "Verhältnis"),
    _p("UA1-04", "Cash-Profitabilität", "operativer Cashflow der letzten zwölf Monate / Bilanzsumme", "Verhältnis",
       schwaechen="Näherung an Ball u. a. (2016): Cashflow statt operativem Gewinn ohne Accruals"),
    _p("UA1-05", "Bilanzwachstum", "Bilanzsumme / Bilanzsumme ein Jahr zuvor − 1", "Verhältnis"),
    _p("UA1-06", "F-Score", "Summe von neun Ja/Nein-Signalen nach Piotroski (2000) aus zwei Jahresabschlüssen",
       "Punkte 0–9", frequenz="je Jahresbericht",
       schwaechen="Nur wenn alle neun Signale berechenbar sind; Renditen auf die Bilanzsumme zum Jahresende"),
    _p("UA1-07", "Cash-Reichweite",
       "(Zahlungsmittel + kurzfristige Anlagen) / Mittelabfluss je Quartal; nur bei Mittelabfluss, höchstens 40 "
       "(wie fin_runway_q im Insider-Monitor)", "Quartale",
       schwaechen="Die Plausibilitätsschwelle gegen den Börsenwert wendet der Insider-Monitor an"),
    _p("UA2-01", "M-Score",
       "Beneish (1999): −4,84 + 0,920·DSRI + 0,528·GMI + 0,404·AQI + 0,892·SGI + 0,115·DEPI − 0,172·SGAI "
       "+ 4,679·TATA − 0,327·LVGI aus zwei Jahresabschlüssen", "Punktwert (über −1,78 auffällig)",
       frequenz="je Jahresbericht", schwaechen="Nur wenn alle acht Bausteine berechenbar sind; nicht für Finanzfirmen"),
    _p("UA3-01", "Netto-Aktienemission (12 Monate)", "Aktienzahl / Aktienzahl ein Jahr zuvor − 1", "Verhältnis",
       schwaechen="Nicht splitbereinigt: Sprünge über Faktor 3 werden verworfen; kleinere Splits bleiben als Fehler"),
    _p("GA1-02", "F&E-Aufwand (12 Monate)", "Forschungs- und Entwicklungsaufwand der letzten zwölf Monate",
       "US-Dollar", schwaechen="Verhältnis zum Marktwert wird im privaten Repo gebildet"),
    _p("GA1-06", "Organisationskapital",
       "Fortgeschriebener Vertriebs- und Verwaltungsaufwand (15 % Abschreibung je Jahr, Startwert Aufwand / 0,25) "
       "/ Bilanzsumme, nach Eisfeldt & Papanikolaou (2013)", "Verhältnis", frequenz="je Jahresbericht",
       schwaechen="Ohne Preisbereinigung; Startwert hängt vom ersten verfügbaren Jahr ab"),
    _p("GA3-03", "Werbeausgaben-Änderung", "Werbeaufwand des Jahres / Vorjahr − 1", "Verhältnis",
       frequenz="je Jahresbericht", schwaechen="Viele Firmen weisen Werbeaufwand nicht gesondert aus"),
    _p("GW1-04", "Finanzrestriktion (Whited-Wu-Index)",
       "−0,091·Cashflow/Bilanzsumme − 0,062·Dividendenzahler + 0,021·langfristige Schulden/Bilanzsumme "
       "− 0,044·ln(Bilanzsumme in Mio. $) + 0,102·Branchenwachstum − 0,035·Umsatzwachstum, aus dem Jahresabschluss; "
       "höher = stärker finanziell beschränkt (Whited & Wu 2006)", "Indexwert", frequenz="je Jahresbericht",
       schwaechen="Jahres- statt Quartalswerte; Bilanzsumme nicht preisbereinigt; Branchenwachstum (dreistelliger "
                  "SIC, mindestens drei Firmen) aus dem Vorjahr, weil das laufende Jahr am Stichtag noch nicht "
                  "vollständig gemeldet ist"),
    _p("PR2-03", "Effektiver Steuersatz", "Ertragsteueraufwand / Ergebnis vor Steuern des Jahres, nur bei Gewinn vor Steuern",
       "Verhältnis", frequenz="je Jahresbericht", schwaechen="Latente Steuerpositionen fehlen noch"),
)


# --------------------------------------------------------------------------- Berichtszeilen
def _zahl(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    return x if np.isfinite(x) else np.nan


def _tage(a: str, b: str) -> int | None:
    try:
        return (pd.Timestamp(b) - pd.Timestamp(a)).days
    except (ValueError, TypeError):
        return None


def zeitraumklasse(start: str | None, ende: str) -> str:
    """Q = Quartal, H = Halbjahr, T = neun Monate, Y = Jahr, I = Stichtag (wie _dur_class im Insider-Monitor)."""
    if not start:
        return "I"
    d = _tage(start, ende)
    if d is None:
        return ""
    if 55 <= d <= 115:
        return "Q"
    if 150 <= d <= 210:
        return "H"
    if 240 <= d <= 300:
        return "T"
    if 330 <= d <= 400:
        return "Y"
    return ""


def _waehle(liste: list, ende: str, vorrang: tuple) -> tuple[str, float]:
    """Wert zum Stichtag ``ende`` nach Klassen- und Postenvorrang."""
    bester = None
    for rang, klasse, e, wert in liste:
        if e != ende or klasse not in vorrang or np.isnan(wert):
            continue
        k = (vorrang.index(klasse), rang)
        if bester is None or k < bester[0]:
            bester = (k, klasse, wert)
    return (bester[1], bester[2]) if bester else ("", np.nan)


def _waehle_vorjahr(liste: list, ende: str, klasse: str) -> float:
    """Vorjahreswert aus derselben Einreichung (Vergleichszahlen im Bericht)."""
    if not klasse:
        return np.nan
    ziel = pd.Timestamp(ende) - pd.Timedelta(days=TAG_JAHR)
    bester = None
    for rang, k, e, wert in liste:
        if k != klasse or np.isnan(wert):
            continue
        d = abs((pd.Timestamp(e) - ziel).days)
        if d <= 25 and (bester is None or (d, rang) < bester[0]):
            bester = ((d, rang), wert)
    return bester[1] if bester else np.nan


def berichtszeilen(cik: int, js: dict) -> list[dict]:
    """companyfacts-JSON einer Firma -> eine Zeile je 10-K/10-Q."""
    fakten = (js or {}).get("facts", {}) or {}
    topf: dict = {}
    for gruppe in ("us-gaap", "ifrs-full"):
        topf.update(fakten.get(gruppe, {}) or {})
    if not topf:
        return []
    je: dict[str, dict] = {}
    for feld, posten in FELDER.items():
        for rang, name in enumerate(posten):
            for einheit, eintraege in ((topf.get(name) or {}).get("units", {}) or {}).items():
                if einheit not in ("USD", "shares"):
                    continue
                for e in eintraege:
                    if e.get("form") not in BERICHTSFORMEN:
                        continue
                    accn, ende, filed = e.get("accn"), e.get("end"), e.get("filed")
                    if not (accn and ende and filed):
                        continue
                    klasse = zeitraumklasse(e.get("start"), ende)
                    if not klasse:
                        continue
                    d = je.setdefault(accn, {"form": e["form"], "filed": filed})
                    d.setdefault(feld, []).append((rang, klasse, ende, _zahl(e.get("val"))))
    # Aktienzahl vom Deckblatt (Stand kurz vor der Einreichung), getrennt, weil ihr Datum nach dem Periodenende liegt
    deckblatt: dict[str, tuple[str, float]] = {}
    for einheit, eintraege in (((fakten.get("dei", {}) or {}).get("EntityCommonStockSharesOutstanding") or {})
                               .get("units", {}) or {}).items():
        if einheit != "shares":
            continue
        for e in eintraege:
            accn, ende, wert = e.get("accn"), e.get("end"), _zahl(e.get("val"))
            if accn and ende and e.get("form") in BERICHTSFORMEN and not np.isnan(wert):
                if accn not in deckblatt or ende > deckblatt[accn][0]:
                    deckblatt[accn] = (ende, wert)
    zeilen = []
    for accn, d in je.items():
        # Die Aktienzahl wird teils zum Deckblattdatum statt zum Periodenende ausgewiesen; sie darf das
        # Periodenende nicht bestimmen (sonst blieben alle anderen Größen der Zeile leer).
        enden = [e for f in FELDER if f != "shares" and f in d for (_, _, e, _) in d[f]] \
            or [e for (_, _, e, _) in d.get("shares", [])]
        if not enden:
            continue
        pe = max(enden)
        z = {"cik": cik, "accn": accn, "form": d["form"], "filed": d["filed"], "period_end": pe, "rev_src": ""}
        for f in ZEITRAUM:
            klasse, wert = _waehle(d.get(f, []), pe, ("Q", "H", "T", "Y"))
            z[f] = wert
            z[f + "_py"] = _waehle_vorjahr(d.get(f, []), pe, klasse)
            z[f + "_q"] = QUARTALE.get(klasse, np.nan)
        # Banken tragen keinen Umsatz: Zinsüberschuss plus zinsunabhängige Erträge treten an seine Stelle
        if np.isnan(z["revenue"]):
            teile = [z["rev_int"], z["rev_nonint"]]
            if any(not np.isnan(x) for x in teile):
                z["revenue"] = float(np.nansum(teile))
                z["revenue_q"] = next((z[f + "_q"] for f in ("rev_int", "rev_nonint") if not np.isnan(z[f + "_q"])), np.nan)
                vj = [z["rev_int_py"], z["rev_nonint_py"]]
                if any(not np.isnan(x) for x in vj):
                    z["revenue_py"] = float(np.nansum(vj))
                z["rev_src"] = "bank"
        for f in STICHTAG:
            # Aktien: Stichtagswert, ersatzweise der gewichtete Durchschnitt des kürzesten Zeitraums
            vorrang = ("I", "Q", "H", "T", "Y") if f == "shares" else ("I",)
            z[f] = _waehle(d.get(f, []), pe, vorrang)[1]
        z["shares_deckblatt"] = deckblatt.get(accn, ("", np.nan))[1]
        if any(not np.isnan(z[f]) for f in FELDER):
            zeilen.append(z)
    return zeilen


# --------------------------------------------------------------------------- Kennzahlen je Firma
def _einzelquartale(tage: np.ndarray, wert: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Einzelquartalswerte aus Quartals- und aufgelaufenen Werten (Halbjahr, neun Monate, Jahr).

    ``tage``: Periodenende als Tageszahl, aufsteigend. Ein Wert über q Quartale minus die q−1
    vorangehenden Einzelquartale desselben Geschäftsjahres; fehlt eines, bleibt der Wert leer.
    """
    n = len(tage)
    aus = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(wert[i]) or np.isnan(q[i]):
            continue
        k = int(q[i])
        if k == 1:
            aus[i] = wert[i]
            continue
        summe, gefunden = 0.0, 0
        for j in range(i - 1, -1, -1):
            abstand = tage[i] - tage[j]
            if abstand > (k - 1) * 92 + 25:
                break
            if abstand < 60 or np.isnan(aus[j]):
                continue
            summe += aus[j]
            gefunden += 1
        if gefunden == k - 1:
            aus[i] = wert[i] - summe
    return aus


def _zwoelf_monate(tage: np.ndarray, einzel: np.ndarray, wert: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Zwölfmonatswert: Jahreswert, wenn der Bericht ein Jahr abdeckt, sonst Summe der letzten vier Einzelquartale."""
    n = len(tage)
    aus = np.full(n, np.nan)
    for i in range(n):
        if q[i] == 4 and not np.isnan(wert[i]):
            aus[i] = wert[i]
            continue
        if np.isnan(einzel[i]):
            continue
        summe, gefunden = einzel[i], 1
        for j in range(i - 1, -1, -1):
            abstand = tage[i] - tage[j]
            if abstand > 3 * 92 + 25:
                break
            if abstand < 60 or np.isnan(einzel[j]):
                continue
            summe += einzel[j]
            gefunden += 1
        if gefunden == 4:
            aus[i] = summe
    return aus


def _vorjahr(tage: np.ndarray, wert: np.ndarray, maske: np.ndarray | None = None) -> np.ndarray:
    """Wert des Berichts, dessen Periodenende rund ein Jahr (±25 Tage) zurückliegt."""
    n = len(tage)
    aus = np.full(n, np.nan)
    for i in range(n):
        bester = None
        for j in range(i - 1, -1, -1):
            abstand = tage[i] - tage[j]
            if abstand > TAG_JAHR + 25:
                break
            if abstand < TAG_JAHR - 25 or np.isnan(wert[j]) or (maske is not None and not maske[j]):
                continue
            guete = abs(abstand - TAG_JAHR)
            if bester is None or guete < bester[0]:
                bester = (guete, wert[j])
        if bester:
            aus[i] = bester[1]
    return aus


def _verh(a, b):
    """a / b, leer bei b <= 0 oder fehlenden Werten."""
    a, b = np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / b, np.nan)


def kennzahlen_firma(g: pd.DataFrame) -> pd.DataFrame:
    """Kennzahlen je Bericht einer Firma. ``g``: Berichte, je Periodenende die zuerst eingereichte Fassung."""
    g = g.sort_values(["period_end", "filed"], kind="stable").drop_duplicates("period_end", keep="first")
    tage = g["period_end"].to_numpy().astype("datetime64[D]").astype("int64")
    sp = lambda name: g[name].to_numpy(dtype="float64")
    jahr = g["form"].to_numpy() == "10-K"
    aus = pd.DataFrame({"accn": g["accn"].to_numpy()}, index=g.index)

    ni_q = _einzelquartale(tage, sp("net_income"), sp("net_income_q"))
    cf_q = _einzelquartale(tage, sp("op_cf"), sp("op_cf_q"))
    ni_12 = _zwoelf_monate(tage, ni_q, sp("net_income"), sp("net_income_q"))
    cf_12 = _zwoelf_monate(tage, cf_q, sp("op_cf"), sp("op_cf_q"))
    rnd_12 = _zwoelf_monate(tage, _einzelquartale(tage, sp("rnd"), sp("rnd_q")), sp("rnd"), sp("rnd_q"))
    aktiva = sp("assets")

    # UA1-01: saisonale Differenz, geteilt durch die Streuung der acht Vorquartale
    diff = ni_q - _vorjahr(tage, ni_q)
    sue = np.full(len(g), np.nan)
    for i in range(len(g)):
        if np.isnan(diff[i]):
            continue
        vorher = [diff[j] for j in range(i - 1, -1, -1) if tage[i] - tage[j] <= 8 * 92 + 25 and not np.isnan(diff[j])]
        if len(vorher) >= 4:
            streuung = np.std(vorher, ddof=1)
            if streuung > 0:
                sue[i] = diff[i] / streuung
    aus["UA1-01"] = sue

    # UA1-02: Zahlenlage wie fin_lage_roh
    with np.errstate(divide="ignore", invalid="ignore"):
        umsatz, umsatz_vj = sp("revenue"), sp("revenue_py")
        rev_yoy = np.where(np.abs(umsatz_vj) > 0, umsatz / umsatz_vj - 1, np.nan)
        ni_je_q = sp("net_income") / sp("net_income_q")
        cf_je_q = sp("op_cf") / sp("op_cf_q")
    bekannt = ~np.isnan(rev_yoy) | ~np.isnan(ni_je_q)
    positiv = (rev_yoy > 0.02) & (ni_je_q > 0) & (np.isnan(cf_je_q) | (cf_je_q > 0))
    negativ = (rev_yoy < -0.02) & (ni_je_q <= 0)
    lage = np.where(bekannt, 0.0, np.nan)
    lage[bekannt & positiv] = 1.0
    lage[bekannt & negativ] = -1.0
    aus["UA1-02"] = lage

    aus["UA1-03"] = _verh(ni_12 - cf_12, aktiva)
    aus["UA1-04"] = _verh(cf_12, aktiva)
    aus["UA1-05"] = _verh(aktiva, _vorjahr(tage, aktiva)) - 1

    # UA1-07: Reichweite wie fin_runway_q
    kasse = np.where(np.isnan(sp("cash")) & np.isnan(sp("sti")), np.nan, np.nan_to_num(sp("cash")) + np.nan_to_num(sp("sti")))
    abfluss = -cf_je_q
    reichweite = _verh(kasse, abfluss)
    aus["UA1-07"] = np.where(reichweite <= 40, reichweite, np.nan)

    # UA3-01: Aktienzahl gegen Vorjahr; Deckblattangabe hat Vorrang, große Sprünge gelten als Split
    aktien = np.where(np.isnan(sp("shares_deckblatt")), sp("shares"), sp("shares_deckblatt"))
    faktor = _verh(aktien, _vorjahr(tage, aktien))
    aus["split_verdacht"] = (faktor > SPLIT_GRENZE) | (faktor < 1 / SPLIT_GRENZE)
    aus["UA3-01"] = np.where(aus["split_verdacht"], np.nan, faktor - 1)

    aus["GA1-02"] = np.where(rnd_12 > 0, rnd_12, np.nan)

    # --- Jahreskennzahlen: nur Jahresberichte, Vergleich mit dem Jahresbericht des Vorjahres
    def j(name):  # Jahreswert einer Zeitraumgröße (nur wenn der Bericht ein Jahr abdeckt)
        return np.where(jahr & (sp(name + "_q") == 4), sp(name), np.nan)

    def vj(wert):
        return _vorjahr(tage, wert, maske=jahr)

    umsatz_j, ni_j, cf_j = j("revenue"), j("net_income"), j("op_cf")
    brutto = np.where(np.isnan(j("gross_profit")), umsatz_j - j("cogs"), j("gross_profit"))
    aktiva_j = np.where(jahr, aktiva, np.nan)
    umlauf, kurzfr, ford, sach, schuld = (np.where(jahr, sp(n), np.nan) for n in ("assets_cur", "liab_cur", "recv", "ppe", "debt"))
    aktien_j = np.where(jahr, aktien, np.nan)

    # UA1-06 Piotroski
    roa, roa_vj = _verh(ni_j, aktiva_j), _verh(vj(ni_j), vj(aktiva_j))
    cfo = _verh(cf_j, aktiva_j)
    signale = [
        (roa > 0, roa), (cfo > 0, cfo), (roa > roa_vj, roa - roa_vj), (cfo > roa, cfo - roa),
        (_verh(schuld, aktiva_j) < _verh(vj(schuld), vj(aktiva_j)), _verh(schuld, aktiva_j) - _verh(vj(schuld), vj(aktiva_j))),
        (_verh(umlauf, kurzfr) > _verh(vj(umlauf), vj(kurzfr)), _verh(umlauf, kurzfr) - _verh(vj(umlauf), vj(kurzfr))),
        (aktien_j <= vj(aktien_j) * 1.02, aktien_j - vj(aktien_j)),
        (_verh(brutto, umsatz_j) > _verh(vj(brutto), vj(umsatz_j)), _verh(brutto, umsatz_j) - _verh(vj(brutto), vj(umsatz_j))),
        (_verh(umsatz_j, aktiva_j) > _verh(vj(umsatz_j), vj(aktiva_j)), _verh(umsatz_j, aktiva_j) - _verh(vj(umsatz_j), vj(aktiva_j))),
    ]
    vollstaendig = np.all([~np.isnan(pruef) for _, pruef in signale], axis=0)
    aus["UA1-06"] = np.where(vollstaendig, np.sum([s.astype(float) for s, _ in signale], axis=0), np.nan)

    # UA2-01 Beneish
    sga_j, dep_j = j("sga"), j("dep")
    with np.errstate(divide="ignore", invalid="ignore"):
        dsri = _verh(ford, umsatz_j) / _verh(vj(ford), vj(umsatz_j))
        gmi = _verh(vj(brutto), vj(umsatz_j)) / _verh(brutto, umsatz_j)
        aqi = (1 - _verh(umlauf + sach, aktiva_j)) / (1 - _verh(vj(umlauf) + vj(sach), vj(aktiva_j)))
        sgi = _verh(umsatz_j, vj(umsatz_j))
        depi = _verh(vj(dep_j), vj(dep_j) + vj(sach)) / _verh(dep_j, dep_j + sach)
        sgai = _verh(sga_j, umsatz_j) / _verh(vj(sga_j), vj(umsatz_j))
        tata = _verh(ni_j - cf_j, aktiva_j)
        lvgi = _verh(schuld + kurzfr, aktiva_j) / _verh(vj(schuld) + vj(kurzfr), vj(aktiva_j))
        m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
             - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    aus["UA2-01"] = np.where(np.isfinite(m), m, np.nan)

    # GA1-06 Organisationskapital: fortgeschriebener Vertriebs- und Verwaltungsaufwand
    kapital = np.full(len(g), np.nan)
    stand, letzter_tag = np.nan, None
    for i in range(len(g)):
        if np.isnan(sga_j[i]) or sga_j[i] <= 0:
            continue
        if letzter_tag is None:
            stand = sga_j[i] / 0.25
        else:
            jahre = (tage[i] - letzter_tag) / 365.25
            stand = stand * 0.85 ** jahre + sga_j[i]
        letzter_tag = tage[i]
        kapital[i] = stand
    aus["GA1-06"] = _verh(kapital, aktiva_j)

    werbung = j("adv")
    aus["GA3-03"] = _verh(werbung, vj(werbung)) - 1
    steuersatz = _verh(j("tax"), j("pretax"))
    aus["PR2-03"] = np.where((steuersatz >= -1) & (steuersatz <= 2), steuersatz, np.nan)

    # Bausteine des Whited-Wu-Index; das Branchenwachstum kommt firmenübergreifend in baue_parameter hinzu
    with np.errstate(divide="ignore", invalid="ignore"):
        aus["ww_firma"] = (-0.091 * _verh(ni_j + dep_j, aktiva_j) - 0.062 * (np.nan_to_num(j("div")) > 0)
                           + 0.021 * _verh(schuld, aktiva_j) - 0.044 * np.log(np.where(aktiva_j > 0, aktiva_j / 1e6, np.nan))
                           - 0.035 * (_verh(umsatz_j, vj(umsatz_j)) - 1))
    aus["umsatz_j"], aus["umsatz_vj"] = umsatz_j, vj(umsatz_j)
    return aus


PARAMETER_IDS = ["UA1-01", "UA1-02", "UA1-03", "UA1-04", "UA1-05", "UA1-06", "UA1-07", "UA2-01", "UA3-01",
                 "GA1-02", "GA1-06", "GA3-03", "PR2-03", "GW1-04"]
MINDEST_BRANCHE = 3


def _whited_wu(b: pd.DataFrame, firmen: pd.DataFrame | None) -> pd.Series:
    """Whited-Wu-Index je Jahresbericht: Firmenbausteine plus Umsatzwachstum der Branche im Vorjahr."""
    leer_ = pd.Series(np.nan, index=b.index)
    if firmen is None or firmen.empty or "sic" not in firmen.columns:
        return leer_
    sic3 = firmen.dropna(subset=["sic"]).drop_duplicates("cik").set_index("cik")["sic"].astype(str).str.slice(0, 3)
    branche = b["cik"].map(sic3)
    jahr = b["period_end"].dt.year
    gueltig = b["umsatz_j"].notna() & b["umsatz_vj"].notna() & (b["umsatz_vj"] > 0) & branche.notna()
    g = b[gueltig].assign(branche=branche[gueltig], jahr=jahr[gueltig]).groupby(["branche", "jahr"])
    summen = g.agg(umsatz=("umsatz_j", "sum"), vorjahr=("umsatz_vj", "sum"), firmen=("cik", "nunique"))
    wachstum = (summen["umsatz"] / summen["vorjahr"] - 1)[summen["firmen"] >= MINDEST_BRANCHE]
    schluessel = pd.MultiIndex.from_arrays([branche, jahr - 1])
    isg = pd.Series(wachstum.reindex(schluessel).to_numpy(), index=b.index)
    return b["ww_firma"] + 0.102 * isg


def baue_parameter(berichte: pd.DataFrame, meldungen: pd.DataFrame,
                   firmen: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Parameter aus den Berichtszeilen; Annahmezeit je Bericht aus dem Meldungsverzeichnis.
    ``firmen`` (cik, sic) wird nur für den Branchenbezug des Whited-Wu-Index gebraucht."""
    if berichte.empty:
        return leer(), {"berichte": 0}
    b = berichte.copy()
    b["period_end"] = pd.to_datetime(b["period_end"], errors="coerce")
    b["filed"] = pd.to_datetime(b["filed"], errors="coerce")
    b = b[b["period_end"].notna() & b["filed"].notna() & (b["period_end"] <= b["filed"])]
    b = b.sort_values(["cik", "period_end", "filed"], kind="stable").reset_index(drop=True)
    kenn = pd.concat([kennzahlen_firma(g) for _, g in b.groupby("cik", sort=False)])
    b = b.loc[kenn.index].join(kenn.drop(columns="accn"))
    b["GW1-04"] = _whited_wu(b, firmen)

    zeit = pd.DataFrame(columns=["accn", "annahme_utc", "verfuegbar_ab"])
    if not meldungen.empty:
        zeit = (meldungen.rename(columns={"accession": "accn"})[["accn", "annahme_utc", "verfuegbar_ab"]]
                .sort_values("annahme_utc").drop_duplicates("accn"))
    b = b.merge(zeit, on="accn", how="left")
    fehlt = b["verfuegbar_ab"].isna()
    ersatz = (b.loc[fehlt, "filed"] + pd.Timedelta(hours=17, minutes=30)).dt.tz_localize(
        ET, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    b["verfuegbar_ab"] = pd.to_datetime(b["verfuegbar_ab"], utc=True).astype("datetime64[us, UTC]")
    b.loc[fehlt, "verfuegbar_ab"] = handelbar_ab_serie(ersatz).astype("datetime64[us, UTC]")
    b["ereignis_zeit"] = b["period_end"].dt.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward") \
        .dt.tz_convert("UTC").astype("datetime64[us, UTC]")
    teile = []
    for pid in PARAMETER_IDS:
        t = b[b[pid].notna()]
        teile.append(pd.DataFrame({"cik": t["cik"].to_numpy(), "parameter_id": pid, "ereignis_zeit": t["ereignis_zeit"].values,
                                   "verfuegbar_ab": t["verfuegbar_ab"].values, "wert": t[pid].to_numpy(dtype="float64"),
                                   "stand": t["accn"].to_numpy()}))
    teile = [t for t in teile if len(t)]
    info = {"berichte": int(len(b)), "firmen": int(b["cik"].nunique()), "ohne_annahmezeit": int(fehlt.sum()),
            "split_verdacht": int(b["split_verdacht"].sum())}
    return (als_parameter(pd.concat(teile, ignore_index=True)) if teile else leer()), info


# --------------------------------------------------------------------------- Lauf
def lies_sammeldatei(zip_pfad: Path) -> tuple[pd.DataFrame, int]:
    zeilen: list[dict] = []
    teile: list[pd.DataFrame] = []
    dateien = 0
    with zipfile.ZipFile(zip_pfad) as archiv:
        for name in archiv.namelist():
            treffer = DATEI_MUSTER.match(Path(name).name)
            if not treffer:
                continue
            with archiv.open(name) as f:
                try:
                    js = json.load(f)
                except ValueError:
                    continue
            dateien += 1
            zeilen.extend(berichtszeilen(int(treffer.group(1)), js))
            if len(zeilen) >= 20_000:          # Wörterbücher brauchen ein Vielfaches des Tabellenspeichers
                teile.append(pd.DataFrame(zeilen))
                zeilen = []
    if zeilen:
        teile.append(pd.DataFrame(zeilen))
    return (pd.concat(teile, ignore_index=True) if teile else pd.DataFrame()), dateien


def lauf(ablage: Ablage, arbeits: Path, zip_pfad: Path | None = None,
         abruf: Abruf | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    """Vollständiger Neuaufbau aus der Sammeldatei (die SEC erzeugt sie jede Nacht neu)."""
    arbeits = Path(arbeits)
    if zip_pfad is None:
        abruf = abruf or Abruf()
        zip_pfad = abruf.hole_datei(SAMMEL_URL, arbeits / "companyfacts.zip")
    berichte, dateien = lies_sammeldatei(Path(zip_pfad))
    if berichte.empty:
        raise RuntimeError("Sammeldatei enthält keine auswertbaren Abschlüsse")
    hinweise: list[str] = []
    jahr = pd.to_datetime(berichte["filed"], errors="coerce").dt.year
    for j, teil in berichte.groupby(jahr):
        ablage.schreibe_bereinigt(TABELLE, str(int(j)), teil)
    meldungen = ablage.lies_bereinigt("edgar_meldungen", spalten=["accession", "annahme_utc", "verfuegbar_ab"],
                                      filter=[("form", "in", list(BERICHTSFORMEN))])
    if meldungen.empty:
        hinweise.append("Meldungsverzeichnis fehlt; Annahmezeiten werden aus dem Einreichungsdatum geschätzt")
    firmen = ablage.lies_bereinigt("edgar_firmen", spalten=["cik", "sic"])
    if firmen.empty:
        hinweise.append("Firmentabelle fehlt; der Whited-Wu-Index (GW1-04) entfällt")
    parameter, info = baue_parameter(berichte, meldungen, firmen)
    info["quelldateien"] = dateien
    ablage.schreibe_parameter("edgar_xbrl", parameter)
    return parameter, info, hinweise
