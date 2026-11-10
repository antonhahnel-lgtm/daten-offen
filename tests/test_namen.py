import json

import pandas as pd
import pytest

from daten_offen.kern.namen import Namensabgleich, bereinige, kern, trefferquote

FIRMEN = pd.DataFrame({
    "cik": [1, 2, 3, 4, 5, 6, 7],
    "name": ["ALPHA CORP /DE/", "Beta Holdings, Inc.", "GAMMA & SONS CO", "DELTA AIR LINES, INC.",
             "OMEGA INC", "OMEGA INC", "The Zeta Company"],
    "tickers": ["ALPH", "BETA", None, "DAL", "OMG", None, "ZETA"],
    "fruehere_namen": ["[]", json.dumps([{"name": "BETA SYSTEMS CORP"}]), "[]", "[]", "[]", "[]", "[]"],
})


@pytest.fixture(scope="module")
def abgleich():
    return Namensabgleich(FIRMEN)


def test_bereinigung():
    assert bereinige("ALPHA CORP /DE/") == "ALPHA"
    assert bereinige("Beta Holdings, Inc.") == "BETA HOLDINGS"
    assert bereinige("GAMMA & SONS CO") == "GAMMA AND SONS"
    assert bereinige("The Zeta Company") == "ZETA"
    assert bereinige("O'Reilly Automotive, Inc.") == "OREILLY AUTOMOTIVE"
    assert bereinige(None) == "" and bereinige("Inc") == "INC"
    assert kern("BETA HOLDINGS") == "BETA"


@pytest.mark.parametrize("name, cik, art", [
    ("Alpha Corporation", 1, "exakt"),
    ("beta systems corp.", 2, "frueher"),
    ("Beta Group LLC", 2, "kern"),
    ("Gamma and Sons Company", 3, "exakt"),
    ("Delta Airlines Inc", 4, "aehnlich"),          # Schreibweise ohne Leerzeichen
    ("Omega Incorporated", 5, "exakt"),             # zwei Firmen gleichen Namens: die börsennotierte
    ("Zeta Co", 7, "exakt"),
    ("Delta Faucet Company", None, "keiner"),       # gleiches Anfangswort, andere Firma
    ("Unbekannt GmbH", None, "keiner"),
    ("", None, "keiner"),
])
def test_finde(abgleich, name, cik, art):
    gefunden, konfidenz, wie = abgleich.finde(name)
    assert (gefunden, wie) == (cik, art)
    assert (konfidenz > 0) == (cik is not None) and konfidenz <= 1


def test_mehrdeutig_ohne_ticker():
    a = Namensabgleich(pd.DataFrame({"cik": [5, 6], "name": ["OMEGA INC", "OMEGA INC"], "tickers": [None, None]}))
    assert a.finde("Omega") == (None, 0.0, "mehrdeutig")


def test_spalte_und_quote(abgleich):
    namen = pd.Series(["Alpha Corporation", "Unbekannt GmbH", None, "Alpha Corporation"], index=[10, 11, 12, 13])
    z = abgleich.ordne_zu(namen)
    assert list(z.index) == [10, 11, 12, 13] and z["cik"].tolist()[0] == 1 and pd.isna(z.loc[12, "cik"])
    q = trefferquote(z, gewicht=pd.Series([100.0, 50.0, 0.0, 50.0], index=z.index))
    assert q["quote"] == 0.5 and q["quote_gewichtet"] == 0.75 and q["arten"]["exakt"] == 2
