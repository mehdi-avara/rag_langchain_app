#!/bin/bash
pip install --upgrade pip
pip install uv
uv pip install -U "mineru[core]"

folders=(
   "/mnt/2T/mehdi_avara/vfiles/_1_Gas_turbine"
  #"/mnt/2T/mehdi_avara/vfiles/_2_Compressor"
  #"/mnt/2T/mehdi_avara/vfiles/_3_CD"
)
base_out="/mnt/2T/mehdi_avara/vfiles/outputDirt"

for dir in "${folders[@]}"; do
  echo "Processing folder: $dir"
  folder_name=$(basename "$dir")
  out_dir="$base_out/$folder_name"
  mkdir -p "$out_dir"

  for file in "$dir"/*.pdf; do
    [ -e "$file" ] || continue  # skip if no PDFs
    echo "  Processing: $file -> $out_dir"
    mineru -p "$file" -o "$out_dir" 
  done
done

# mineru-gradio --server-name 0.0.0.0 --server-port 7860 --enable-vllm-engine true