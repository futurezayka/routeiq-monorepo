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

echo "[osrm-prepare] Downloading Kyiv region extract (~30 MB)…"
wget --no-check-certificate -O "$PBF_FILE" \
  "https://download.bbbike.org/osm/bbbike/Kyiv/Kyiv.osm.pbf" || {
    echo "[osrm-prepare] BBBike download failed, trying Geofabrik Ukraine extract…"
    wget --no-check-certificate -O "$PBF_FILE" \
      "https://download.geofabrik.de/europe/ukraine-latest.osm.pbf"
  }

echo "[osrm-prepare] Extracting (MLD algorithm)…"
osrm-extract -p "$PROFILE" "$PBF_FILE"

echo "[osrm-prepare] Partitioning…"
osrm-partition "$OSRM_FILE"

echo "[osrm-prepare] Customizing…"
osrm-customize "$OSRM_FILE"

rm -f "$PBF_FILE"
echo "[osrm-prepare] Ready."
