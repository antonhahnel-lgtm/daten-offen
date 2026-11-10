import shutil
from datetime import date
from pathlib import Path

import pytest

from daten_offen.kern import http
from daten_offen.kern.ablage import Ablage
from daten_offen.kern.zustand import Zeitbudget
from daten_offen.quellen import edgar_insider as ins
from tests.hilfen import baue_form345_zip


class Antwort:
    def __init__(self, status, inhalt=b"", kopf=None):
        self.status_code, self._inhalt, self.headers = status, inhalt, kopf or {}

    def iter_content(self, chunk_size):
        yield self._inhalt

    def json(self):
        return {"ok": True}

    def close(self):
        pass


class Sitzung:
    def __init__(self, antworten):
        self.antworten, self.headers, self.aufrufe = list(antworten), {}, []

    def get(self, url, **kw):
        self.aufrufe.append(url)
        return self.antworten.pop(0)


@pytest.fixture(autouse=True)
def schnell(monkeypatch):
    monkeypatch.setenv("KONTAKT_EMAIL", "test@example.org")
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def test_user_agent_und_wiederholung(tmp_path):
    sitzung = Sitzung([Antwort(503), Antwort(429, kopf={"Retry-After": "1"}), Antwort(200, b"abc")])
    abruf = http.Abruf(sitzung=sitzung, anfragen_pro_sekunde=1000)
    assert "test@example.org" in sitzung.headers["User-Agent"]
    ziel = abruf.hole_datei("https://x/y.zip", tmp_path / "y.zip")
    assert ziel.read_bytes() == b"abc" and len(sitzung.aufrufe) == 3
    assert not (tmp_path / "y.zip.teil").exists()


def test_404_erlaubt_und_harter_fehler(tmp_path):
    abruf = http.Abruf(sitzung=Sitzung([Antwort(404), Antwort(400)]), anfragen_pro_sekunde=1000)
    assert abruf.hole_datei("https://x/a", tmp_path / "a", erlaube_404=True) is None
    with pytest.raises(http.QuelleNichtErreichbar):
        abruf.hole("https://x/b")


def test_ohne_kontakt_kein_abruf(monkeypatch):
    monkeypatch.delenv("KONTAKT_EMAIL")
    monkeypatch.delenv("MAIL_USER", raising=False)
    with pytest.raises(RuntimeError, match="KONTAKT_EMAIL"):
        http.Abruf()
    monkeypatch.setenv("MAIL_USER", "projekt@example.org")
    assert "projekt@example.org" in http.Abruf(sitzung=Sitzung([])).sitzung.headers["User-Agent"]


class FalscherErsterPfad:
    """Erster bekannter Ablageort liefert 404, der zweite die Datei."""

    def __init__(self, vorlage: Path):
        self.vorlage, self.urls = vorlage, []

    def hole(self, url, **kw):
        raise http.QuelleNichtErreichbar("Datenseite gesperrt")

    def hole_datei(self, url, ziel, erlaube_404=False):
        self.urls.append(url)
        if "structureddata" in url or "2024q1" not in url:
            return None
        Path(ziel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.vorlage, ziel)
        return Path(ziel)


def test_insider_lauf_mit_ausweichpfad_und_budget(tmp_path):
    vorlage = baue_form345_zip(
        tmp_path / "v.zip",
        [["A-1", "05-MAR-2024", "", "4", 1000, "ALPHA", "ALPH", "0"]],
        [["A-1", 2001, "P", "Director", ""]],
        [["A-1", 1, "Common", "04-MAR-2024", "P", 1000, 10, "A", 5000, "D"]])
    ablage = Ablage(tmp_path / "aus")
    abruf = FalscherErsterPfad(vorlage)
    parameter, info, hinweise = ins.lauf(ablage, tmp_path / "arb", ab_jahr=2024, heute=date(2024, 7, 2), abruf=abruf)
    assert any("dera/data/form-345/2024q1" in u for u in abruf.urls)
    assert info["zeilen"] == 1 and any("2024q2" in h for h in hinweise)
    assert any("Datenseite nicht lesbar" in h for h in hinweise)
    assert parameter[parameter["parameter_id"] == "IH1-03"]["wert"].iloc[0] == 10000
    assert not list((tmp_path / "arb").glob("*.zip"))                      # Archiv nach dem Lesen entfernt

    leer_ablage = Ablage(tmp_path / "aus2")
    _, info2, _ = ins.lauf(leer_ablage, tmp_path / "arb2", ab_jahr=2024, heute=date(2024, 7, 2), abruf=abruf,
                           budget=Zeitbudget(0))
    assert info2 == {"unvollstaendig": True}
    assert (tmp_path / "aus2" / "FORTSETZEN__edgar_insider").exists()
