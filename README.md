```markdown
# Book Downloader (Internet Archive + Project Gutenberg + Standard Ebooks)
A small, well-documented Python tool to search and download books from multiple public/legal sources (Internet Archive and Project Gutenberg via Gutendex). If a PDF is not available but an EPUB is, it can convert EPUB → PDF. It can also convert audiobooks to PDF by using an existing transcript or by performing local speech-to-text transcription (optional) with OpenAI Whisper.

Important legal note
- Only download books that are public domain or that you have explicit right to download. This tool is provided for lawful use only. The author of the tool is not responsible for misuse.

Features added
- Search Internet Archive and Project Gutenberg (Gutendex).
- Support direct Standard Ebooks pages and download EPUB when provided (simple page scraping).
- Download PDF when available, otherwise download EPUB and convert to PDF.
- EPUB→PDF conversion via (in order): Calibre `ebook-convert`, Pandoc (via pypandoc), fallback Python converter using ebooklib + reportlab.
- Audiobook → PDF conversion:
  - If a transcript (.txt, .srt) is available, it will be embedded into the PDF.
  - Optionally, if `whisper` (OpenAI Whisper) and `ffmpeg` are available, the tool can transcribe local audio files and produce a transcript PDF.
- Unit tests (pytest) and a GitHub Actions CI workflow.

Prerequisites
- Python 3.8+
- pip install -r requirements.txt
- For best EPUB→PDF conversion: install Calibre and ensure `ebook-convert` is on your PATH.
  - Calibre: https://calibre-ebook.com/download
- Optional for EPUB→PDF: Pandoc (used by pypandoc).
- Optional for audiobook transcription: OpenAI Whisper requires `ffmpeg` and the `whisper` Python package. See below.

Installation
1. Create and activate a virtualenv (recommended).
2. pip install -r requirements.txt

Quick usage examples
- Download book and convert EPUB→PDF when needed:
  python book_downloader.py --title "Pride and Prejudice" --convert

- Search only Internet Archive and save to ./ia_books:
  python book_downloader.py --title "Frankenstein" --sites archive --output ./ia_books

- Provide a Standard Ebooks URL and download EPUB:
  python book_downloader.py --standard-url "https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice" --convert

- Convert audiobook to PDF with an existing transcript:
  python book_downloader.py --audiobook-transcript "/path/to/transcript.txt" --audiobook-title "My Audio Book" --audiobook-author "Some Author" --output ./books

- Convert local audiobook audio to PDF using Whisper (if installed):
  python book_downloader.py --audiobook-audio "/path/to/book.mp3" --audiobook-title "My Audio Book" --use-whisper --output ./books

Usage (CLI)
  See `python book_downloader.py --help` for full CLI options. Notable flags:
  --title: Title to search for
  --author: Optional author filter
  --sites: Comma-separated list of sites to search (archive,gutenberg). Default: both.
  --standard-url: Direct Standard Ebooks URL to download from (optional)
  --convert: Convert EPUB→PDF when PDF not found
  --audiobook-transcript: Path to an existing transcript text file to embed into PDF
  --audiobook-audio: Path to local audio file to transcribe (requires --use-whisper for transcription)
  --use-whisper: If present, attempt local transcription using the Whisper model (whisper package required)
  --output: Output directory. Default: ./books

Testing & CI
- Run tests locally:
  pip install -r requirements.txt
  pip install -r requirements-dev.txt
  pytest

- GitHub Actions CI is provided in `.github/workflows/ci.yml`. It installs dependencies and runs pytest.

Limitations and notes
- Standard Ebooks support is based on page scraping and direct download links; it works for known Standard Ebooks pages but is not an official API integration.
- Whisper transcription is optional. Installing `whisper` and `ffmpeg` will let the tool attempt audio transcription locally; transcription can be slow and consumes CPU/GPU depending on the model you choose.
- Conversions are best-effort; for high-quality EPUB→PDF use Calibre's `ebook-convert`.

If you'd like:
- Add more public sources (Standard Ebooks search improvements, Librivox, HathiTrust where allowed).
- Add embedding of audio file attachments into the PDF (platform-specific, requires more advanced PDF handling).
- A GUI or web frontend.
```
