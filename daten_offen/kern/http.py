"""HTTP-Abruf mit Anfragegrenze, Wiederholung und deklariertem User-Agent."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import requests

WIEDERHOLBARE_STATUS = {429, 500, 502, 503, 504}


class QuelleNichtErreichbar(RuntimeError):
    pass


class Abruf:
    """Sitzung für eine Quelle.

    ``anfragen_pro_sekunde`` begrenzt die Rate (SEC erlaubt höchstens 10; Vorgabe hier 8).
    Die Kontaktadresse kommt aus KONTAKT_EMAIL, ersatzweise MAIL_USER (wie im Insider-Monitor),
    jeweils als GitHub Secret.
    """

    def __init__(self, anfragen_pro_sekunde: float = 8.0, versuche: int = 6, timeout: int = 120,
                 kontakt_noetig: bool = True, sitzung: requests.Session | None = None):
        kontakt = (os.environ.get("KONTAKT_EMAIL", "") or os.environ.get("MAIL_USER", "")).strip()
        if kontakt_noetig and not kontakt:
            raise RuntimeError("Umgebungsvariable KONTAKT_EMAIL (oder MAIL_USER) fehlt (GitHub Secret anlegen)")
        self.abstand = 1.0 / anfragen_pro_sekunde
        self.versuche = versuche
        self.timeout = timeout
        self.sitzung = sitzung or requests.Session()
        self.sitzung.headers.update({
            "User-Agent": f"daten-offen Forschung {kontakt}".strip(),
            "Accept-Encoding": "gzip, deflate",
        })
        self._letzte = 0.0
        self._sperre = threading.Lock()
        self.anfragen = 0

    def _warte(self) -> None:
        with self._sperre:                      # die Anfragegrenze gilt auch für parallele Abrufe insgesamt
            jetzt = time.monotonic()
            start = max(jetzt, self._letzte + self.abstand)
            self._letzte = start
        if start > jetzt:
            time.sleep(start - jetzt)

    def hole(self, url: str, stream: bool = False, erlaube_404: bool = False, **kw) -> requests.Response | None:
        letzter_fehler: Exception | None = None
        for versuch in range(self.versuche):
            self._warte()
            self.anfragen += 1
            try:
                antwort = self.sitzung.get(url, timeout=self.timeout, stream=stream, **kw)
            except requests.RequestException as fehler:
                letzter_fehler = fehler
            else:
                if antwort.status_code in (200, 206):
                    return antwort
                if antwort.status_code == 404 and erlaube_404:
                    antwort.close()
                    return None
                letzter_fehler = RuntimeError(f"HTTP {antwort.status_code} für {url}")
                wartezeit_kopf = antwort.headers.get("Retry-After", "")
                antwort.close()
                if antwort.status_code not in WIEDERHOLBARE_STATUS and antwort.status_code != 403:
                    break
                if wartezeit_kopf.isdigit():
                    time.sleep(min(int(wartezeit_kopf), 600))
                    continue
            time.sleep(min(2 ** versuch * 2, 120))
        raise QuelleNichtErreichbar(f"{url}: {letzter_fehler}")

    def hole_json(self, url: str, **kw):
        return self.hole(url, **kw).json()

    def hole_anfang(self, url: str, anzahl: int = 12000, erlaube_404: bool = False) -> bytes | None:
        """Liest nur die ersten ``anzahl`` Bytes (für Meldungsköpfe großer Dateien)."""
        antwort = self.hole(url, stream=True, erlaube_404=erlaube_404, headers={"Range": f"bytes=0-{anzahl - 1}"})
        if antwort is None:
            return None
        daten = b""
        for block in antwort.iter_content(chunk_size=4096):
            daten += block
            if len(daten) >= anzahl:
                break
        antwort.close()
        return daten[:anzahl]

    def hole_datei(self, url: str, ziel: Path, erlaube_404: bool = False) -> Path | None:
        """Lädt eine Datei in Blöcken; schreibt erst nach vollständigem Abruf an den Zielort."""
        ziel = Path(ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        antwort = self.hole(url, stream=True, erlaube_404=erlaube_404)
        if antwort is None:
            return None
        vorlaeufig = ziel.with_suffix(ziel.suffix + ".teil")
        with open(vorlaeufig, "wb") as f:
            for block in antwort.iter_content(chunk_size=1 << 20):
                if block:
                    f.write(block)
        antwort.close()
        vorlaeufig.replace(ziel)
        return ziel
