#!/bin/bash
set -e

DATA_DIR=/data
PBF_FILE="$DATA_DIR/kyiv.osm.pbf"
OSRM_FILE="$DATA_DIR/kyiv.osrm"
PROFILE="/opt/car.lua"

if [ -f "$OSRM_FILE.fileIndex" ]; then
  echo "[osrm-prepare] Pre-processed data found, skipping."
  exit 0
fi

echo "[osrm-prepare] Downloading Kyiv region extract…"
wget --no-check-certificate -O "$PBF_FILE" \
  "https://download.bbbike.org/osm/bbbike/Kyiv/Kyiv.osm.pbf" 2>/dev/null

FILE_SIZE=$(stat -c%s "$PBF_FILE" 2>/dev/null || echo 0)
if [ "$FILE_SIZE" -lt 100000 ]; then
  echo "[osrm-prepare] BBBike failed (${FILE_SIZE}B), trying Geofabrik…"
  wget --no-check-certificate -O "$PBF_FILE" \
    "https://download.geofabrik.de/europe/ukraine-latest.osm.pbf"
fi

echo "[osrm-prepare] Extracting (MLD algorithm)…"
osrm-extract -p "$PROFILE" "$PBF_FILE"

echo "[osrm-prepare] Partitioning…"
osrm-partition "$OSRM_FILE"

echo "[osrm-prepare] Customizing…"
osrm-customize "$OSRM_FILE"

rm -f "$PBF_FILE"
echo "[osrm-prepare] Ready."
