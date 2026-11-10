#!/usr/bin/env bash
# Lädt die Ergebnisse eines Laufs als Release-Assets hoch (vorhandene Dateien werden ersetzt).
# Zuordnung nach Dateiname: edgar_*/insider_* -> *-edgar, fred_* -> *-makro, wiki*/cfpb*/klinik* -> *-web.
set -euo pipefail
shopt -s nullglob

lade() {
  local tag="$1" titel="$2"
  shift 2
  if [ "$#" -eq 0 ]; then
    echo "Release $tag: nichts hochzuladen"
    return 0
  fi
  if ! gh release view "$tag" >/dev/null 2>&1; then
    gh release create "$tag" --title "$titel" --latest=false \
      --notes "Automatisch erzeugt. Aufbau und Lesebeispiel: SCHNITTSTELLE.md."
  fi
  # in Blöcken hochladen, damit die Befehlszeile kurz bleibt
  local block=()
  for datei in "$@"; do
    block+=("$datei")
    if [ "${#block[@]}" -ge 40 ]; then
      gh release upload "$tag" "${block[@]}" --clobber
      block=()
    fi
  done
  if [ "${#block[@]}" -gt 0 ]; then
    gh release upload "$tag" "${block[@]}" --clobber
  fi
  echo "Release $tag: $# Dateien"
}

B=ausgabe/bereinigt
P=ausgabe/parameter
lade bereinigt-edgar "Bereinigte EDGAR-Daten" "$B"/bereinigt__edgar_*.parquet "$B"/bereinigt__insider_*.parquet
lade bereinigt-makro "Bereinigte Makrodaten (FRED/ALFRED)" "$B"/bereinigt__fred_*.parquet
lade bereinigt-web "Bereinigte Web- und Registerdaten" "$B"/bereinigt__wiki_*.parquet "$B"/bereinigt__cfpb_*.parquet "$B"/bereinigt__klinik_*.parquet
lade parameter-edgar "Parameter aus EDGAR" "$P"/parameter__edgar_*.parquet
lade parameter-makro "Parameter Gesamtwirtschaft" "$P"/parameter__fred__*.parquet
lade parameter-web "Parameter aus Web- und Registerdaten" "$P"/parameter__wikipedia__*.parquet "$P"/parameter__cfpb__*.parquet "$P"/parameter__klinik__*.parquet
lade pruefbericht "Prüfberichte und Manifeste" ausgabe/berichte/*

# Jede erzeugte Datei muss einem Release zugeordnet sein
for datei in "$B"/*.parquet "$P"/*.parquet; do
  case "$(basename "$datei")" in
    bereinigt__edgar_*|bereinigt__insider_*|bereinigt__fred_*|bereinigt__wiki_*|bereinigt__cfpb_*|bereinigt__klinik_*) ;;
    parameter__edgar_*|parameter__fred__*|parameter__wikipedia__*|parameter__cfpb__*|parameter__klinik__*) ;;
    *) echo "Keinem Release zugeordnet: $datei" >&2; exit 1 ;;
  esac
done
