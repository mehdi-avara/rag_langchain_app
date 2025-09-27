from pathlib import Path
import re
import requests
from typing import Optional

def _pick_pdf_for_download(md_path: Path) -> Path | None:
    """Prefer *_origin.pdf, then *_layout.pdf, else any .pdf in the same folder."""
    folder = md_path.parent
    # Highest priority
    for pattern in ["*_origin.pdf", "*_layout.pdf", "*.pdf"]:
        matches = sorted(folder.glob(pattern))
        if matches:
            return matches[0]
    return None

def _rewrite_image_paths(md_text: str, md_path: Path) -> str:
    """
    Make image URLs absolute (file paths) relative to the MD's folder.
    Handles: ![alt](images/foo.jpg), ![alt](./images/foo.jpg), ![alt](foo.jpg), etc.
    """
    base = md_path.parent.as_posix()

    # Markdown images: ![alt](url "title")
    # We won't touch http(s) or data: URLs.
    def repl(m):
        url = m.group("url").strip()
        if re.match(r"^(https?:|data:)", url, flags=re.I):
            return m.group(0)
        # Build absolute file path relative to the MD file folder
        abs_url = Path(base, url).as_posix()
        return f'![{m.group("alt")}]({abs_url}{m.group("title") or ""})'

    md_img_pat = re.compile(
        r'!\[(?P<alt>[^\]]*)\]\('
        r'(?P<url>[^)\s]+)'
        r'(?P<title>\s+"[^"]*")?'
        r'\)',
        flags=re.I
    )
    return md_img_pat.sub(repl, md_text)

def download_origin_pdf(md_path: Path, download_url: str) -> Optional[Path]:
    """
    Download *_origin.pdf file from the given URL and save it to the same folder as the markdown file.
    
    Args:
        md_path: Path to the markdown file
        download_url: URL to download the PDF from
        
    Returns:
        Path to the downloaded PDF file, or None if download failed
    """
    # Get the folder where the markdown file is located
    folder = md_path.parent
    
    # Create the filename for the origin PDF
    md_name = md_path.stem  # Get filename without extension
    origin_pdf_name = f"{md_name}_origin.pdf"
    origin_pdf_path = folder / origin_pdf_name
    
    # Download the PDF file
    response = requests.get(download_url, stream=True)
    response.raise_for_status()
    
    # Save the PDF file
    with open(origin_pdf_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    return origin_pdf_path

        

