#!/usr/bin/env python3
"""
book_downloader.py

Searches Internet Archive, Project Gutenberg (Gutendex), and Standard Ebooks (direct URL)
for books and downloads them. If PDF is unavailable, will download EPUB and convert to PDF.
Also supports audiobook -> PDF conversion by embedding transcripts or (optionally) transcribing
local audio using OpenAI Whisper.

Legal: Only use this script for public-domain or otherwise-licensed content you have the right
to download. The author is not responsible for misuse.
"""
from __future__ import annotations
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional, Dict, List
import requests
from tqdm import tqdm
from bs4 import BeautifulSoup

# Optional dependencies
try:
    import pypandoc
except Exception:
    pypandoc = None

try:
    from ebooklib import epub
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from reportlab.lib.styles import ParagraphStyle
except Exception:
    epub = None
    canvas = None

# Whisper is optional for local transcription
try:
    import whisper
except Exception:
    whisper = None

USER_AGENT = "book-downloader/2.0 (zenithu-s)"
HEADERS = {"User-Agent": USER_AGENT}
DEFAULT_OUTPUT = "books"


def safe_filename(s: str) -> str:
    return "".join(c if c.isalnum() or c in " .-_()" else "_" for c in s).strip()


def download_file(url: str, dest_path: str) -> None:
    resp = requests.get(url, stream=True, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0) or 0)
    with open(dest_path, "wb") as f, tqdm(
        total=total or None, unit="B", unit_scale=True, desc=os.path.basename(dest_path)
    ) as pbar:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                pbar.update(len(chunk))


# --------------------
# Internet Archive
# --------------------
def search_internet_archive(title: str, author: Optional[str] = None, rows: int = 5):
    q = f'title:("{title}")'
    if author:
        q += f' AND creator:("{author}")'
    params = {
        "q": q,
        "fl": "identifier,title,creator",
        "rows": rows,
        "output": "json"
    }
    url = "https://archive.org/advancedsearch.php"
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    docs = data.get("response", {}).get("docs", [])
    results = []
    for d in docs:
        results.append({
            "identifier": d.get("identifier"),
            "title": d.get("title"),
            "creator": d.get("creator")
        })
    return results


def get_ia_files(identifier: str):
    url = f"https://archive.org/metadata/{identifier}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    files = data.get("files", [])
    return files


def find_best_ia_download(identifier: str):
    files = get_ia_files(identifier)
    pdfs = [f for f in files if "pdf" in (f.get("format","") or "").lower()]
    epubs = [f for f in files if "epub" in (f.get("format","") or "").lower()]
    if pdfs:
        chosen = sorted(pdfs, key=lambda x: int(x.get('size') or 0), reverse=True)[0]
        return ("pdf", chosen.get("name"))
    if epubs:
        return ("epub", epubs[0].get("name"))
    # fallback
    for ext in ("djvu","txt","kindle"):
        candidates = [f for f in files if ext in (f.get("format","") or "").lower()]
        if candidates:
            return (ext, candidates[0].get("name"))
    return (None, None)


def download_from_internet_archive(identifier: str, filename: str, out_dir: str):
    url = f"https://archive.org/download/{identifier}/{filename}"
    dest = os.path.join(out_dir, filename)
    download_file(url, dest)
    return dest


# --------------------
# Gutendex / Project Gutenberg
# --------------------
def search_gutendex(title: str, author: Optional[str] = None, page_size: int = 20):
    base = "https://gutendex.com/books/"
    params = {"search": title}
    r = requests.get(base, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    results = []
    for b in data.get("results", []):
        if author:
            authors = [a.get("name","") for a in b.get("authors",[])]
            if not any(author.lower() in a.lower() for a in authors):
                continue
        results.append({
            "id": b.get("id"),
            "title": b.get("title"),
            "authors": b.get("authors"),
            "formats": b.get("formats", {})
        })
    return results


def find_best_gutenberg_download(formats: Dict[str,str]):
    # prefer PDF, then EPUB
    for key in formats:
        if "pdf" in key.lower():
            return ("pdf", formats[key])
    for key in formats:
        if "epub" in key.lower():
            return ("epub", formats[key])
    return (None, None)


def download_from_url(url: str, out_dir: str, suggested_name: Optional[str] = None):
    if not suggested_name:
        suggested_name = os.path.basename(url.split("?")[0])
    dest = os.path.join(out_dir, suggested_name)
    download_file(url, dest)
    return dest


# --------------------
# Standard Ebooks (simple support)
# --------------------
def download_standard_ebook_from_url(page_url: str, out_dir: str):
    # Accepts a standardebooks.org/ebooks/... URL, scrapes the page for EPUB download link.
    r = requests.get(page_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    # look for links that end with .epub or contain 'EPUB'
    candidate = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".epub"):
            candidate = href
            break
        text = (a.get_text() or "").lower()
        if "epub" in text and href:
            candidate = href
            break
    if not candidate:
        # try the pattern /ebooks/.../download
        link = soup.find("a", class_="ebook-download")
        if link and link.get("href"):
            candidate = link.get("href")
    if not candidate:
        raise RuntimeError("Could not find EPUB download link on Standard Ebooks page.")
    # Make absolute URL if needed
    if candidate.startswith("/"):
        base = re.match(r"(https?://[^/]+)", page_url)
        if base:
            candidate = base.group(1) + candidate
    filename = os.path.basename(candidate.split("?")[0])
    return download_from_url(candidate, out_dir, filename)


# --------------------
# EPUB -> PDF conversion helpers
# --------------------
def has_ebook_convert():
    return shutil.which("ebook-convert") is not None


def convert_with_ebook_convert(epub_path: str, pdf_path: str) -> bool:
    cmd = ["ebook-convert", epub_path, pdf_path]
    try:
        subprocess.check_call(cmd)
        return True
    except subprocess.CalledProcessError:
        return False


def convert_with_pypandoc(epub_path: str, pdf_path: str) -> bool:
    if pypandoc is None:
        return False
    try:
        pypandoc.convert_file(epub_path, 'pdf', outputfile=pdf_path)
        return True
    except Exception:
        return False


def convert_with_ebooklib_fallback(epub_path: str, pdf_path: str) -> bool:
    if epub is None or canvas is None:
        return False
    try:
        book = epub.read_epub(epub_path)
        story = []
        styles = getSampleStyleSheet()
        normal = styles['Normal']
        for item in book.get_items():
            if item.get_type() == epub.EpubHtml:
                content = item.get_body_content().decode(errors="ignore")
                # strip HTML tags simply
                text = re.sub(r'<[^>]+>', '', content)
                paragraphs = [p.strip() for p in text.splitlines() if p.strip()]
                for p in paragraphs:
                    story.append(Paragraph(p, normal))
                    story.append(Spacer(1, 6))
        if not story:
            # fallback: write a minimal page
            c = canvas.Canvas(pdf_path, pagesize=letter)
            c.drawString(72, 720, "No textual content could be extracted.")
            c.save()
            return True
        doc = SimpleDocTemplate(pdf_path, pagesize=letter,
                                rightMargin=72,leftMargin=72,
                                topMargin=72,bottomMargin=72)
        doc.build(story)
        return True
    except Exception:
        return False


def convert_epub_to_pdf(epub_path: str, pdf_path: str) -> bool:
    # Prefer Calibre
    if has_ebook_convert():
        print("Converting with Calibre ebook-convert...")
        if convert_with_ebook_convert(epub_path, pdf_path):
            return True
    # Try pypandoc
    if pypandoc is not None:
        print("Converting with pypandoc (Pandoc)...")
        if convert_with_pypandoc(epub_path, pdf_path):
            return True
    # Fallback
    print("Falling back to Python EPUB->PDF converter (may be low-quality)...")
    return convert_with_ebooklib_fallback(epub_path, pdf_path)


# --------------------
# Audiobook -> PDF conversion helpers
# --------------------
def transcript_to_pdf(transcript_path: str, pdf_path: str, title: Optional[str] = None, author: Optional[str] = None) -> bool:
    if canvas is None:
        return False
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        styles = getSampleStyleSheet()
        story = []
        title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], spaceAfter=12)
        if title:
            story.append(Paragraph(title, title_style))
        if author:
            story.append(Paragraph(f"by {author}", styles['Italic']))
            story.append(Spacer(1, 12))
        normal = styles['Normal']
        # Split into paragraphs
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        for p in paragraphs:
            story.append(Paragraph(p.replace('\n','<br/>'), normal))
            story.append(Spacer(1, 6))
        doc = SimpleDocTemplate(pdf_path, pagesize=letter,
                                rightMargin=72,leftMargin=72,
                                topMargin=72,bottomMargin=72)
        doc.build(story)
        return True
    except Exception:
        return False


def transcribe_with_whisper(audio_path: str, model: str = "small") -> Optional[str]:
    if whisper is None:
        return None
    try:
        print("Loading Whisper model:", model)
        m = whisper.load_model(model)
        print("Transcribing audio (this may take a while)...")
        result = m.transcribe(audio_path)
        text = result.get("text")
        return text
    except Exception as e:
        print("Whisper transcription failed:", e)
        return None


def audiobook_to_pdf(audio_path: Optional[str], transcript_path: Optional[str], pdf_path: str, title: Optional[str] = None, author: Optional[str] = None, use_whisper: bool = False) -> bool:
    # If transcript given, use it
    if transcript_path and os.path.exists(transcript_path):
        print("Creating PDF from transcript:", transcript_path)
        return transcript_to_pdf(transcript_path, pdf_path, title, author)
    # Otherwise, if user asked to use whisper and whisper is available
    if use_whisper and audio_path and os.path.exists(audio_path):
        if whisper is None:
            print("Whisper package not installed; cannot transcribe locally.")
            return False
        text = transcribe_with_whisper(audio_path)
        if not text:
            return False
        # write temporary transcript
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as tf:
            tf.write(text)
            tmp_transcript = tf.name
        try:
            ok = transcript_to_pdf(tmp_transcript, pdf_path, title, author)
            return ok
        finally:
            try:
                os.remove(tmp_transcript)
            except Exception:
                pass
    # No transcript and no transcription available: create a metadata-only PDF
    if canvas is None:
        return False
    try:
        c = canvas.Canvas(pdf_path, pagesize=letter)
        width, height = letter
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, height - 72, title or "Audiobook")
        c.setFont("Helvetica", 12)
        if author:
            c.drawString(72, height - 100, f"Author: {author}")
        if audio_path:
            c.drawString(72, height - 130, f"Audio file: {audio_path}")
        c.drawString(72, height - 160, "No transcript available. To generate a transcript, provide a --audiobook-transcript or use --use-whisper with the whisper package and ffmpeg installed.")
        c.save()
        return True
    except Exception:
        return False


# --------------------
# High-level flow
# --------------------
def process_search_and_download(title: Optional[str], author: Optional[str], sites: List[str], output_dir: str, do_convert: bool, standard_url: Optional[str], audiobook_audio: Optional[str], audiobook_transcript: Optional[str], audiobook_title: Optional[str], audiobook_author: Optional[str], use_whisper: bool):
    os.makedirs(output_dir, exist_ok=True)
    results = []
    # Standard Ebooks direct URL
    if standard_url:
        print("Attempting Standard Ebooks download from:", standard_url)
        try:
            path = download_standard_ebook_from_url(standard_url, output_dir)
            print("Downloaded Standard Ebooks file:", path)
            if do_convert and (path.lower().endswith(".epub") or ".epub" in path.lower()):
                pdf_name = os.path.splitext(os.path.basename(path))[0] + ".pdf"
                pdf_path = os.path.join(output_dir, pdf_name)
                if convert_epub_to_pdf(path, pdf_path):
                    results.append(pdf_path)
                else:
                    results.append(path)
            else:
                results.append(path)
        except Exception as e:
            print("Standard Ebooks download failed:", e)

    # IA
    if "archive" in sites and title:
        print("Searching Internet Archive...")
        try:
            ia_results = search_internet_archive(title, author)
        except Exception as e:
            print("Internet Archive search failed:", e)
            ia_results = []
        for r in ia_results:
            identifier = r.get("identifier")
            pretty = r.get("title") or identifier
            print(f"Found IA item: {pretty} (id={identifier})")
            ftype, fname = find_best_ia_download(identifier)
            if not ftype:
                print("  No downloadable format found for this IA item.")
                continue
            print(f"  Best format: {ftype} -> {fname}")
            try:
                downloaded = download_from_internet_archive(identifier, fname, output_dir)
            except Exception as e:
                print("  Download failed:", e)
                continue
            if ftype != "pdf" and do_convert and fname.lower().endswith(".epub"):
                pdf_name = os.path.splitext(fname)[0] + ".pdf"
                pdf_path = os.path.join(output_dir, pdf_name)
                ok = convert_epub_to_pdf(downloaded, pdf_path)
                if ok:
                    print("  Converted to PDF:", pdf_path)
                    results.append(pdf_path)
                else:
                    print("  Conversion failed.")
                    results.append(downloaded)
            else:
                results.append(downloaded)

    # Gutenberg
    if "gutenberg" in sites and title:
        print("Searching Project Gutenberg (Gutendex)...")
        try:
            guten_results = search_gutendex(title, author)
        except Exception as e:
            print("Gutendex search failed:", e)
            guten_results = []
        for gr in guten_results:
            print(f"Found Gutenberg book: {gr.get('title')}")
            ftype, url = find_best_gutenberg_download(gr.get("formats", {}))
            if not ftype or not url:
                print("  No suitable downloadable format.")
                continue
            suggested = safe_filename(gr.get("title") + (" - epub" if ftype=="epub" else " - pdf"))
            if url.lower().endswith(".epub") or ".epub" in url:
                if not suggested.lower().endswith(".epub"):
                    suggested += ".epub"
            elif url.lower().endswith(".pdf") or ".pdf" in url:
                if not suggested.lower().endswith(".pdf"):
                    suggested += ".pdf"
            try:
                downloaded = download_from_url(url, output_dir, suggested)
            except Exception as e:
                print("  Download failed:", e)
                continue
            if ftype != "pdf" and do_convert and (downloaded.lower().endswith(".epub") or ".epub" in downloaded.lower()):
                pdf_name = os.path.splitext(os.path.basename(downloaded))[0] + ".pdf"
                pdf_path = os.path.join(output_dir, pdf_name)
                ok = convert_epub_to_pdf(downloaded, pdf_path)
                if ok:
                    print("  Converted to PDF:", pdf_path)
                    results.append(pdf_path)
                else:
                    print("  Conversion failed.")
                    results.append(downloaded)
            else:
                results.append(downloaded)

    # Audiobook conversion
    if audiobook_audio or audiobook_transcript:
        pdf_name = safe_filename((audiobook_title or "audiobook")) + ".pdf"
        pdf_path = os.path.join(output_dir, pdf_name)
        ok = audiobook_to_pdf(audiobook_audio, audiobook_transcript, pdf_path, audiobook_title, audiobook_author, use_whisper)
        if ok:
            print("Audiobook PDF created:", pdf_path)
            results.append(pdf_path)
        else:
            print("Audiobook -> PDF conversion failed or not possible.")

    return results


def main():
    parser = argparse.ArgumentParser(description="Book downloader (Internet Archive + Gutenberg + Standard Ebooks) with EPUB->PDF and Audiobook->PDF conversion.")
    parser.add_argument("--title", required=False, help="Title to search for")
    parser.add_argument("--author", required=False, help="Author to filter by")
    parser.add_argument("--sites", required=False, default="archive,gutenberg", help="Comma-separated sites: archive,gutenberg")
    parser.add_argument("--standard-url", required=False, help="Direct Standard Ebooks book page URL to download")
    parser.add_argument("--output", required=False, default=DEFAULT_OUTPUT, help="Output directory")
    parser.add_argument("--convert", action="store_true", help="Convert EPUB to PDF when PDF not found")
    parser.add_argument("--audiobook-audio", required=False, help="Path to local audiobook audio file to transcribe (optional)")
    parser.add_argument("--audiobook-transcript", required=False, help="Path to an existing transcript text file to embed")
    parser.add_argument("--audiobook-title", required=False, help="Title to use in audiobook PDF")
    parser.add_argument("--audiobook-author", required=False, help="Author to use in audiobook PDF")
    parser.add_argument("--use-whisper", action="store_true", help="If set and whisper is available, transcribe audio locally")
    args = parser.parse_args()

    sites = [s.strip().lower() for s in args.sites.split(",") if s.strip()]

    print("Starting search and download:")
    if args.title:
        print(f" Title: {args.title}")
    if args.author:
        print(f" Author: {args.author}")
    if args.standard_url:
        print(f" Standard Ebooks URL: {args.standard_url}")
    print(f" Sites: {sites}")
    print(f" Output: {args.output}")
    print(f" Convert EPUB->PDF: {args.convert}")
    if args.audiobook_audio:
        print(f" Audiobook audio: {args.audiobook_audio}")
    if args.audiobook_transcript:
        print(f" Audiobook transcript: {args.audiobook_transcript}")
    if args.use_whisper:
        print(" Whisper transcription requested (whisper package must be installed).")

    results = process_search_and_download(
        args.title, args.author, sites, args.output, args.convert,
        args.standard_url, args.audiobook_audio, args.audiobook_transcript,
        args.audiobook_title, args.audiobook_author, args.use_whisper
    )
    if results:
        print("\nCompleted. Files downloaded/created:")
        for r in results:
            print(" -", r)
    else:
        print("\nNo files were downloaded or created. Try a different query or check network/permissions.")


if __name__ == "__main__":
    main()