"""Keep original page/section provenance; refuse ambiguous Word revisions."""
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from docx import Document
from docx.table import Table
from pypdf import PdfReader

EXTRACTION_VERSION = "tcw-extract-1"
SUPPORTED = {".pdf", ".docx", ".txt", ".md"}

@dataclass
class Block:
    text: str
    page: int | None
    section: str

def clean(s):
    s = s.replace("\x00", "").replace("\r", "")
    return re.sub(r"[ \t]+", " ", s).strip()

def heading(s):
    return (0 < len(s) < 145 and
            (s.isupper() and bool(re.search(r"[A-Z]", s))
             or bool(re.match(r"^(?:\d+(?:\.\d+)*\.?\s+[A-Z]|Step \d+\s)", s))))

def extract(path):
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError("Supported formats: PDF, DOCX, TXT, Markdown.")
    if p.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("Maximum source file size is 30 MiB.")
    blocks, warnings = [], []
    if ext == ".pdf":
        reader = PdfReader(p)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs require an unlocked source copy.")
        if len(reader.pages) > 600:
            raise ValueError("PDF exceeds the 600-page demo limit.")
        pages = [(page.extract_text() or "").splitlines() for page in reader.pages]
        repeated = Counter()
        for lines in pages:
            repeated.update(set(clean(x) for x in lines[:3] + lines[-3:] if clean(x)))
        headers = {x for x, n in repeated.items() if len(pages) >= 5 and n / len(pages) >= .6}
        for number, lines in enumerate(pages, 1):
            section, parts = f"PDF physical page {number}", []
            for idx, line in enumerate(lines):
                s = clean(line)
                edge = idx < 3 or idx >= len(lines) - 3
                if not s or edge and (s in headers or re.fullmatch(r"\d+|[ivxlcdm]+", s, re.I)):
                    continue
                if heading(s):
                    if parts:
                        blocks.append(Block("\n".join(parts), number, section))
                    section, parts = s, [s]
                else:
                    parts.append(s)
            if parts:
                blocks.append(Block("\n".join(parts), number, section))
            if not any(clean(x) for x in lines):
                warnings.append(f"PDF physical page {number}: no extractable text; images/OCR not indexed.")
    elif ext == ".docx":
        with ZipFile(p) as z:
            if sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
                raise ValueError("Expanded DOCX exceeds the extraction limit.")
            xml = etree.fromstring(z.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            if xml.findall(".//w:ins", ns) or xml.findall(".//w:del", ns):
                raise ValueError("Unresolved tracked changes. Supply an approved clean DOCX.")
        document = Document(p)
        section = "Document body"
        for item in document.iter_inner_content():
            if isinstance(item, Table):
                rows = [clean(" | ".join(c.text for c in r.cells)) for r in item.rows]
                if rows:
                    for row in rows[1:] or rows:
                        blocks.append(Block((rows[0] + "\n" + row) if row != rows[0] else row, None, section))
                continue
            raw, s = item.text, clean(item.text)
            style = item.style.name if item.style else ""
            if not s or style.lower().startswith("toc") or re.match(r"^\d+\.\s+.*\t\d+\s*$", raw):
                continue
            if style.lower().startswith("heading") or heading(s):
                section = s
            blocks.append(Block(s, None, section))
        warnings.append("DOCX has no reliable physical page mapping; citations use section and chunk.")
    else:
        s = p.read_text(encoding="utf-8-sig")
        section = "Document body"
        for part in re.split(r"\n\s*\n", s):
            part = part.strip()
            if not part:
                continue
            first = part.splitlines()[0]
            if first.startswith("#"):
                section = first.lstrip("# ").strip()
            elif len(first) < 100 and len(part.splitlines()) > 1:
                section = first
            blocks.append(Block(part, None, section))
    if sum(len(b.text) for b in blocks) < 35:
        raise ValueError("No usable text was extracted. Scanned PDFs need OCR before ingestion.")
    # Never echo a matched value in an error or log.
    text = "\n".join(b.text for b in blocks)
    secret = r"(?i)\b(?:password|passwd|pwd|api[_ -]?key|client_secret|access_token)\s*[:=]\s*[\"']?[^\s<>]{4,}"
    if re.search(secret, text) or "-----BEGIN PRIVATE KEY-----" in text:
        raise ValueError("Possible embedded credentials detected. Excluded pending a clean source copy.")
    return blocks, warnings

def chunk(blocks, size=1700, overlap=220):
    """Only combine within one page/section. Overlap never crosses that boundary."""
    grouped = []
    for b in blocks:
        if grouped and (grouped[-1].page, grouped[-1].section) == (b.page, b.section):
            grouped[-1].text += "\n" + b.text
        else:
            grouped.append(Block(b.text, b.page, b.section))
    chunks = []
    for b in grouped:
        start = 0
        while start < len(b.text):
            end = min(start + size, len(b.text))
            if end < len(b.text):
                cut = max(b.text.rfind("\n", start + size // 2, end),
                          b.text.rfind(" ", start + size // 2, end))
                if cut > start:
                    end = cut
            s = b.text[start:end].strip()
            if s:
                chunks.append({"text": s, "page_number": b.page, "section": b.section,
                               "ordinal": len(chunks), "char_start": start, "char_end": end})
            if end == len(b.text):
                break
            start = max(start + 1, end - overlap)
            while start < end and not b.text[start - 1].isspace():
                start += 1
    return chunks
