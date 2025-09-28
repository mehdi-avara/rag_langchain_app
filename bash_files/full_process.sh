#!/usr/bin/env bash
set -uo pipefail

# Folders to process
folders=(
  "/mnt/2T/mehdi_avara/vfiles/_1_Gas_turbine copy"
  "/mnt/2T/mehdi_avara/vfiles/_2_Compressor copy"
  "/mnt/2T/mehdi_avara/vfiles/_3_CD copy"
)

# Where to log
LOG_DIR="/mnt/2T/mehdi_avara/run_logs"
mkdir -p "$LOG_DIR"
OCR_FAILS="$LOG_DIR/ocr_failures.txt"
INGEST_FAILS="$LOG_DIR/ingest_failures.txt"
ALL_LOG="$LOG_DIR/run.log"

# Start fresh
: > "$OCR_FAILS"
: > "$INGEST_FAILS"
: > "$ALL_LOG"

for dir in "${folders[@]}"; do
  echo "Processing folder: $dir" | tee -a "$ALL_LOG"

  # Derive a class from folder name (adjust if you need something else)
  class_arg=$(basename "$dir")

  shopt -s nullglob
  for file in "$dir"/*.pdf; do
    echo "  OCR: $file" | tee -a "$ALL_LOG"

    # Output path with _ocr suffix next to the original
    out="${file%.pdf}_ocr.pdf"

    # 1) OCR step
    if ! ocrmypdf --skip-text "$file" "$out" >>"$ALL_LOG" 2>&1; then
      echo "$file" >> "$OCR_FAILS"
      echo "    ❌ OCR failed -> $file" | tee -a "$ALL_LOG"
      # Skip ingestion if OCR failed
      continue
    fi

    echo "    ✅ OCR OK -> $out" | tee -a "$ALL_LOG"

    # 2) Ingestion step (use the OCR’d file; fix flag name if your CLI uses a single dash)
    # Your example looked like "-class folder_name" split across lines; most CLIs expect --class
    if ! python -m app.ingestion.main --file "$out" --class "$class_arg" >>"$ALL_LOG" 2>&1; then
      echo "$out" >> "$INGEST_FAILS"
      echo "    ❌ Ingestion failed -> $out" | tee -a "$ALL_LOG"
    else
      echo "    ✅ Ingestion OK -> $out" | tee -a "$ALL_LOG"
    fi
  done
done

echo
echo "Done."
echo "OCR failures:     $OCR_FAILS"
echo "Ingestion fails:  $INGEST_FAILS"
echo "Full log:         $ALL_LOG"%   