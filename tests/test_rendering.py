from __future__ import annotations

import json
import zipfile
from pathlib import Path

from automd.models import Document, OutputMode, ProcessingOptions, SourceSpec
from automd.rendering import build_artifacts, build_chunks, render_markdown


def documents() -> list[Document]:
    return [
        Document(
            "s1",
            "Project",
            "src/a.py",
            "src/a.py",
            "text/x-python",
            "print(```)",
            language="python",
            sha256="a" * 64,
        ),
        Document(
            "s1",
            "Project",
            "docs/a.py",
            "docs/a.py",
            "text/x-python",
            "print('世界')",
            language="python",
            sha256="b" * 64,
        ),
    ]


def test_markdown_is_faithful_and_anchors_are_unique() -> None:
    output = render_markdown(
        "project", documents(), [SourceSpec("s1", "upload", "Project")], ProcessingOptions()
    )
    assert "print(```)" in output
    assert "世界" in output
    assert output.count('<a id="') == 2
    assert "````python" in output


def test_chunks_are_stable() -> None:
    options = ProcessingOptions(chunk_target=200, chunk_overlap=20)
    first = build_chunks(documents(), options)
    second = build_chunks(documents(), options)
    assert first == second
    assert all(chunk["schema"] == "automd.rag.v1" for chunk in first)


def test_rag_bundle_contains_expected_contracts(tmp_path: Path) -> None:
    options = ProcessingOptions(output_mode=OutputMode.RAG, output_name="demo")
    artifacts = build_artifacts(
        tmp_path,
        requested_name="demo",
        documents=documents(),
        skipped=[],
        warnings=[],
        sources=[SourceSpec("s1", "upload", "Project")],
        options=options,
    )
    with zipfile.ZipFile(artifacts[0].path) as archive:
        assert set(archive.namelist()) == {"demo.md", "chunks.jsonl", "manifest.json"}
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "automd.rag.v1"
        assert manifest["counts"]["documents"] == 2


def test_rag_chunks_bound_long_lines_and_strip_private_url_parts() -> None:
    item = documents()[0]
    item.content = "A" * 12_000
    item.source_url = "https://example.org/file?access_token=sample#private"
    chunks = build_chunks([item], ProcessingOptions(chunk_target=200, chunk_overlap=20))
    assert len(chunks) > 1
    assert all(len(chunk["text"]) < 1_650 for chunk in chunks)
    assert all(chunk["source"]["url"] == "https://example.org/file" for chunk in chunks)
    assert all(chunk["text"].startswith("```python\n") for chunk in chunks)
    assert sum(chunk["text"].count("A") for chunk in chunks) == 12_000


def test_rag_chunk_preserves_code_indentation() -> None:
    item = documents()[0]
    item.content = "    return 17  "
    chunk = build_chunks([item], ProcessingOptions())[0]
    assert "\n    return 17  \n" in chunk["text"]
