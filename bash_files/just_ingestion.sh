#!/usr/bin/env bash
set -uo pipefail

folders=(
  "/mnt/2T/mehdi_avara/vfiles/_1_Gas_turbine"
  "/mnt/2T/mehdi_avara/vfiles/_2_Compressor"
  "/mnt/2T/mehdi_avara/vfiles/_3_CD"
)

# Logging
LOG_DIR="/mnt/2T/mehdi_avara/run_logs"
mkdir -p "$LOG_DIR"
INGEST_FAILS="$LOG_DIR/ingest_failures.txt"
ALL_LOG="$LOG_DIR/run.log"

# Reset logs
: > "$INGEST_FAILS"
: > "$ALL_LOG"

for dir in "${folders[@]}"; do
  echo "Processing folder: $dir" | tee -a "$ALL_LOG"

  # use folder name as class argument
  class_arg=$(basename "$dir")

  shopt -s nullglob
  for file in "$dir"/*.pdf; do
    echo "  Ingest: $file" | tee -a "$ALL_LOG"

    if ! python -m app.ingestion.main --file "$file" --class "$class_arg" >>"$ALL_LOG" 2>&1; then
      echo "$file" >> "$INGEST_FAILS"
      echo "    ❌ Ingestion failed -> $file" | tee -a "$ALL_LOG"
    else
      echo "    ✅ Ingestion OK -> $file" | tee -a "$ALL_LOG"
    fi
  done
done

echo
echo "Done."
echo "Failures logged in: $INGEST_FAILS"
echo "Full run log:       $ALL_LOG"