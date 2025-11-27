#!/usr/bin/env python3
"""
Simple Flask web UI for the book_downloader script.

Run:
  pip install flask
  python ui/app.py

Then open http://127.0.0.1:5000
"""
import os
import pathlib
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

# Import functions from the downloader module (must be adjacent)
from book_downloader import (
    search_internet_archive,
    search_gutendex,
    find_best_ia_download,
    download_from_internet_archive,
    download_from_url,
    download_standard_ebook_from_url,
    convert_epub_to_pdf,
    audiobook_to_pdf,
    safe_filename,
)

app = Flask(__name__, template_folder="templates")
BASE_DIR = pathlib.Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Serve downloaded files
@app.route("/downloads/<path:filename>")
def serve_download(filename):
    return send_from_directory(str(DOWNLOAD_DIR), filename, as_attachment=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.json or {}
    title = data.get("title", "").strip()
    author = data.get("author", "").strip() or None
    sites = data.get("sites", ["archive", "gutenberg"])
    results = {"archive": [], "gutenberg": []}
    if "archive" in sites and title:
        try:
            ia = search_internet_archive(title, author, rows=8)
            # annotate with best file (name/type) where possible
            for item in ia:
                identifier = item.get("identifier")
                try:
                    ftype, fname = find_best_ia_download(identifier)
                except Exception:
                    ftype, fname = None, None
                item["_best_format"] = ftype
                item["_best_name"] = fname
            results["archive"] = ia
        except Exception as e:
            results["archive_error"] = str(e)
    if "gutenberg" in sites and title:
        try:
            gut = search_gutendex(title, author)
            results["gutenberg"] = gut
        except Exception as e:
            results["gutenberg_error"] = str(e)
    return jsonify(results)


@app.route("/api/download", methods=["POST"])
def api_download():
    """
    Expected JSON:
      {
        "source": "archive"|"gutenberg"|"standard",
        "identifier": "<archive identifier>",         # for archive
        "filename": "<file name in IA>",             # for archive
        "url": "<direct download url>",              # for gutenberg or direct url
        "standard_url": "<standard ebooks page>",    # for standard ebooks
        "convert": true|false
      }
    """
    data = request.json or {}
    source = data.get("source")
    convert = bool(data.get("convert"))
    try:
        if source == "archive":
            identifier = data["identifier"]
            filename = data["filename"]
            out_path = download_from_internet_archive(identifier, filename, str(DOWNLOAD_DIR))
            # convert if requested and epub
            if convert and out_path.lower().endswith(".epub"):
                pdf_path = str(DOWNLOAD_DIR / (pathlib.Path(out_path).stem + ".pdf"))
                ok = convert_epub_to_pdf(out_path, pdf_path)
                return jsonify({"ok": ok, "path": pdf_path if ok else out_path})
            return jsonify({"ok": True, "path": out_path})
        elif source == "gutenberg":
            url = data["url"]
            # derive suggested name
            suggested = secure_filename(data.get("suggested", "")) or None
            out_path = download_from_url(url, str(DOWNLOAD_DIR), suggested)
            if convert and out_path.lower().endswith(".epub"):
                pdf_path = str(DOWNLOAD_DIR / (pathlib.Path(out_path).stem + ".pdf"))
                ok = convert_epub_to_pdf(out_path, pdf_path)
                return jsonify({"ok": ok, "path": pdf_path if ok else out_path})
            return jsonify({"ok": True, "path": out_path})
        elif source == "standard":
            page_url = data.get("standard_url")
            out_path = download_standard_ebook_from_url(page_url, str(DOWNLOAD_DIR))
            if convert and out_path.lower().endswith(".epub"):
                pdf_path = str(DOWNLOAD_DIR / (pathlib.Path(out_path).stem + ".pdf"))
                ok = convert_epub_to_pdf(out_path, pdf_path)
                return jsonify({"ok": ok, "path": pdf_path if ok else out_path})
            return jsonify({"ok": True, "path": out_path})
        else:
            return jsonify({"ok": False, "error": "Unknown source"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/audiobook", methods=["POST"])
def api_audiobook():
    """
    Accepts multipart/form-data with either:
      - transcript file field named 'transcript'
      - audio file field named 'audio' (and optional --use-whisper trigger param)
    Additional form fields:
      - title
      - author
      - use_whisper (true|false)
    """
    title = request.form.get("title") or "audiobook"
    author = request.form.get("author")
    use_whisper = request.form.get("use_whisper", "false").lower() in ("1", "true", "yes")
    transcript = request.files.get("transcript")
    audio = request.files.get("audio")

    try:
        transcript_path = None
        audio_path = None
        if transcript:
            fname = secure_filename(transcript.filename)
            transcript_path = str(DOWNLOAD_DIR / fname)
            transcript.save(transcript_path)
        if audio:
            fname = secure_filename(audio.filename)
            audio_path = str(DOWNLOAD_DIR / fname)
            audio.save(audio_path)

        pdf_name = secure_filename(safe_filename(title)) + ".pdf"
        pdf_path = str(DOWNLOAD_DIR / pdf_name)

        ok = audiobook_to_pdf(audio_path, transcript_path, pdf_path, title, author, use_whisper)
        if ok:
            return jsonify({"ok": True, "path": pdf_path})
        else:
            return jsonify({"ok": False, "error": "Conversion failed"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
