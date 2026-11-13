#!/usr/bin/env bash
# Baut die Historie der Patente (GA1-01) und die Zitationen (GA1-09) aus den von Hand geladenen Sammeldateien von
# PatentsView und lädt das Ergebnis in die Releases. Läuft nur auf dem eigenen Rechner: Die Dateien liegen hinter
# einer Anmeldung (https://data.uspto.gov/bulkdata/datasets/pvgpatdis, USPTO-Konto genügt).
#
# Aufruf im Repo-Ordner:  bash werkzeuge/patente_historie.sh <Ordner mit den Dateien>
# Der Ordner enthält, entpackt (.tsv) oder wie geladen (.tsv.zip):
#   g_patent, g_assignee_not_disambiguated (ersatzweise g_assignee_disambiguated), wahlweise g_us_patent_citation
# PYTHON=<Pfad> wählt den Interpreter (Vorgabe: python).
set -euo pipefail
ORDNER="${1:?Ordner mit den Sammeldateien angeben}"
PY="${PYTHON:-python}"

if [ -e ausgabe ] && [ -n "$(ls -A ausgabe 2>/dev/null)" ]; then
  echo "Der Ordner ausgabe ist nicht leer; bitte vorher leeren (er wird vollständig in die Releases geladen)." >&2
  exit 1
fi
mkdir -p ausgabe/bereinigt vorlauf
gh release download pruefbericht -D vorlauf -p "pruefbericht__uspto_*.json" --clobber || true
gh release download bereinigt-edgar -D ausgabe/bereinigt --clobber -p "bereinigt__edgar_firmen__*.parquet"
gh release download bereinigt-web -D ausgabe/bereinigt --clobber -p "bereinigt__patente_*.parquet" || true

"$PY" -m daten_offen.lauf --quelle uspto_patente --vorlauf vorlauf --patente-ordner "$ORDNER"
if ls "$ORDNER"/g_us_patent_citation.tsv* >/dev/null 2>&1; then
  "$PY" -m daten_offen.lauf --quelle uspto_zitate --vorlauf vorlauf --patente-ordner "$ORDNER"
fi

rm -f ausgabe/bereinigt/bereinigt__edgar_firmen__*.parquet     # gehört der Quelle edgar_index
bash werkzeuge/veroeffentliche.sh
