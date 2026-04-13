"""
File parser for PDF, Markdown, and TXT uploads.
Extracts text and splits into chunks.
"""

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger('mirofish.parser')


def parse_file(filepath: str) -> str:
    """
    Extract text content from a file.

    Supports: .pdf (PyMuPDF), .md, .markdown, .txt
    Raises FileNotFoundError or ValueError on bad input.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    suffix = path.suffix.lower()
    parsers = {
        '.pdf': _parse_pdf,
        '.md': _parse_text,
        '.markdown': _parse_text,
        '.txt': _parse_text,
    }

    parser = parsers.get(suffix)
    if parser is None:
        raise ValueError(f"Unsupported file type: {suffix}")

    return parser(filepath)


def split_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> List[str]:
    """
    Split text into overlapping chunks, preferring sentence boundaries.

    Returns empty list for blank text.
    """
    if not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        end = _find_sentence_boundary(text, start, end, chunk_size)

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break
        start = end - chunk_overlap

    return chunks


# -- internal --

def _parse_pdf(filepath: str) -> str:
    """Extract text from PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("PyMuPDF required: pip install pymupdf")

    pages: list[str] = []
    with fitz.open(filepath) as doc:
        for page in doc:
            page_text = page.get_text()
            if page_text.strip():
                pages.append(page_text)

    return "\n\n".join(pages)


def _parse_text(filepath: str) -> str:
    """Read text file with UTF-8, fallback to replace errors."""
    raw = Path(filepath).read_bytes()

    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass

    # Try charset_normalizer if available
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best and best.encoding:
            return raw.decode(best.encoding, errors='replace')
    except Exception:
        pass

    return raw.decode('utf-8', errors='replace')


def _find_sentence_boundary(
    text: str, start: int, end: int, chunk_size: int
) -> int:
    """Try to break at a sentence boundary within the chunk window."""
    if end >= len(text):
        return end

    separators = ['. ', '! ', '? ', '.\n', '!\n', '?\n', '\n\n']
    segment = text[start:end]

    for sep in separators:
        last_pos = segment.rfind(sep)
        if last_pos != -1 and last_pos > chunk_size * 0.3:
            return start + last_pos + len(sep)

    return end
