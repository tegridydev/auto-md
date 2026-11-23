from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from automd.extraction import Extractor, decode_text
from automd.models import ProcessingOptions, StagedFile


def staged(path: Path) -> StagedFile:
    return StagedFile("source", "Example", path, path.name)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["LF", "CRLF", "CR"])
def test_text_preserves_unicode_and_whitespace(tmp_path: Path, newline: str) -> None:
    path = tmp_path / "hello.py"
    content = "def hello():\n    return 'G’day 世界'  \n"
    raw = content.replace("\n", newline).encode("utf-8")
    path.write_bytes(raw)
    document = Extractor().extract(staged(path), ProcessingOptions())
    assert document.content == content.rstrip("\n")
    assert document.sha256 == hashlib.sha256(raw).hexdigest()
    assert document.language == "python"
    assert document.content_kind == "raw"


def test_cp1252_fallback_reports_warning() -> None:
    text, warning = decode_text(b"caf\xe9")
    assert text == "café"
    assert warning


def test_html_becomes_markdown_without_scripts(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text("<main><h1>Hello</h1><script>bad()</script><p>World</p></main>")
    document = Extractor().extract(staged(path), ProcessingOptions())
    assert "# Hello" in document.content
    assert "World" in document.content
    assert "bad()" not in document.content
    assert document.content_kind == "markdown"


def test_notebook_keeps_cells_and_optional_text_output(tmp_path: Path) -> None:
    path = tmp_path / "demo.ipynb"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["# Notes"]},
                    {
                        "cell_type": "code",
                        "source": ["print('ok')"],
                        "outputs": [{"output_type": "stream", "text": ["ok\\n"]}],
                    },
                ]
            }
        )
    )
    options = ProcessingOptions(include_notebook_outputs=True)
    document = Extractor().extract(staged(path), options)
    assert "Cell 1 · Markdown" in document.content
    assert "```python" in document.content
    assert "### Output" in document.content


def test_image_ocr_with_bundled_models(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    path = tmp_path / "scan.png"
    with Image.new("RGB", (480, 125), "white") as image:
        draw = ImageDraw.Draw(image)
        draw.text((16, 20), "AUTO MD REPORT", font=ImageFont.load_default(size=42), fill="black")
        image.save(path)
    document = Extractor().extract(staged(path), ProcessingOptions())
    assert "REPORT" in document.content.upper()


def test_image_type_must_match_allowlisted_decoder(tmp_path: Path) -> None:
    from PIL import Image, UnidentifiedImageError

    path = tmp_path / "mismatched.png"
    with Image.new("RGB", (8, 8)) as image:
        image.save(path, format="GIF")
    with pytest.raises(UnidentifiedImageError):
        Extractor().extract(staged(path), ProcessingOptions())


def test_pdf_rendering_is_bounded_before_allocation() -> None:
    from automd.extraction import _pdf_scale

    assert _pdf_scale(float("inf"), 100) is None
    assert _pdf_scale(100_000, 100_000) is None
    scale = _pdf_scale(2_000, 1_000)
    assert scale is not None
    assert 2_000 * scale <= 3_000
