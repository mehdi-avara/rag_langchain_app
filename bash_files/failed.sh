#!/usr/bin/env bash
set -uo pipefail

# Input file with failed PDFs
FAILED_LIST="/mnt/2T/mehdi_avara/run_logs/ingest_failures.txt"

# Logging
LOG_DIR="/mnt/2T/mehdi_avara/run_logs"
mkdir -p "$LOG_DIR"
RETRY_LOG="$LOG_DIR/retry_run.log"
RETRY_FAILS="$LOG_DIR/retry_failures.txt"

# Reset logs
: > "$RETRY_LOG"
: > "$RETRY_FAILS"

# Check if list exists and not empty
if [[ ! -s "$FAILED_LIST" ]]; then
  echo "No failed files found in $FAILED_LIST"
  exit 0
fi

echo "Re-processing failed files from: $FAILED_LIST" | tee -a "$RETRY_LOG"

while IFS= read -r file; do
  [[ -z "$file" ]] && continue   # skip empty lines
  if [[ ! -f "$file" ]]; then
    echo "  ⚠️ File not found: $file" | tee -a "$RETRY_LOG"
    echo "$file" >> "$RETRY_FAILS"
    continue
  fi

  echo "  Ingest: $file" | tee -a "$RETRY_LOG"

  # derive class_arg from parent folder name
  class_arg=$(basename "$(dirname "$file")")

  if ! python -m app.ingestion.main --file "$file" --class "$class_arg" >>"$RETRY_LOG" 2>&1; then
    echo "$file" >> "$RETRY_FAILS"
    echo "    ❌ Ingestion failed -> $file" | tee -a "$RETRY_LOG"
  else
    echo "    ✅ Ingestion OK -> $file" | tee -a "$RETRY_LOG"
  fi
done < "$FAILED_LIST"

echo
echo "Done."
echo "Retry failures logged in: $RETRY_FAILS"
echo "Full retry run log:       $RETRY_LOG"%    