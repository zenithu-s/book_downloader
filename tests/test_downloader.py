import os
import tempfile
import shutil
import io
import sys
import pytest
from book_downloader import safe_filename, transcript_to_pdf, audiobook_to_pdf

def test_safe_filename():
    s = 'Pride & Prejudice: An "example"/test?'
    out = safe_filename(s)
    assert '&' not in out and '"' not in out and '/' not in out

def test_transcript_to_pdf_creates_file(tmp_path):
    # Create a small transcript
    t = tmp_path / "transcript.txt"
    t.write_text("This is a test transcript.\n\nThis is paragraph two.", encoding="utf-8")
    pdf_path = tmp_path / "out.pdf"
    ok = transcript_to_pdf(str(t), str(pdf_path), title="Test Title", author="Author")
    assert ok
    assert pdf_path.exists()
    # Minimum size check
    assert pdf_path.stat().st_size > 0

def test_audiobook_to_pdf_no_transcript_creates_metadata_pdf(tmp_path):
    # No transcript and no whisper: should create metadata-only pdf
    pdf_path = tmp_path / "audio_meta.pdf"
    ok = audiobook_to_pdf(None, None, str(pdf_path), title="Audio Book Title", author="Author", use_whisper=False)
    assert ok
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0

# Note: We do not test Whisper transcription here to keep CI light and avoid installing heavy deps.
