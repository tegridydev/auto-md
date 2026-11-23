from __future__ import annotations

import threading
import zipfile
from pathlib import Path

from automd.models import OutputMode, ProcessingOptions, SourceSpec
from automd.pipeline import Pipeline


def test_pipeline_processes_folder_filters_and_archive(tmp_path: Path) -> None:
    workspace = tmp_path / "job"
    upload = workspace / "uploads" / "src"
    (upload / "project").mkdir(parents=True)
    (upload / "project/app.py").write_text(
        "print('hello 世界')\n", encoding="utf-8", newline="\r\n"
    )
    (upload / "project/node_modules/pkg").mkdir(parents=True)
    (upload / "project/node_modules/pkg/index.js").write_text("noise")
    with zipfile.ZipFile(upload / "project/docs.zip", "w") as archive:
        archive.writestr("guide/readme.md", "# Guide\n\nUseful")
    events: list[str] = []
    pipeline = Pipeline(
        workspace,
        threading.Event(),
        lambda event, phase, completed, total, message, source_id: events.append(phase),
    )
    result = pipeline.run(
        [SourceSpec("src", "upload", "project")],
        ProcessingOptions(output_mode=OutputMode.MARKDOWN, output_name="project"),
    )
    output = result.artifacts[0].path.read_bytes().decode("utf-8")
    assert "hello 世界" in output
    assert "\r" not in output
    assert "Useful" in output
    assert "node_modules" not in output
    assert "packaging" in events


def test_docx_in_nested_archive_remains_a_single_document(tmp_path: Path) -> None:
    from docx import Document as WordDocument

    upload = tmp_path / "uploads" / "src"
    upload.mkdir(parents=True)
    word = WordDocument()
    word.add_heading("Quarterly notes", level=1)
    word.add_paragraph("A standalone document.")
    document_path = tmp_path / "fixture.docx"
    word.save(document_path)
    with zipfile.ZipFile(upload / "archive.zip", "w") as archive:
        archive.write(document_path, "notes.docx")
    result = Pipeline(tmp_path, threading.Event(), lambda *_: None).run(
        [SourceSpec("src", "upload", "Project")], ProcessingOptions()
    )
    assert len(result.documents) == 1
    assert result.documents[0].path == "archive.zip/notes.docx"
    markdown = result.artifacts[0].path.read_text(encoding="utf-8")
    assert "Quarterly notes" in markdown
    assert "A standalone document." in markdown
    assert "[Content_Types].xml" not in markdown


def test_folder_upload_applies_project_root_ignore_rules(tmp_path: Path) -> None:
    project = tmp_path / "uploads" / "src" / "project"
    project.mkdir(parents=True)
    (project / ".gitignore").write_text("/scratch.txt\n")
    (project / "scratch.txt").write_text("omitted")
    (project / "notes.txt").write_text("kept")
    result = Pipeline(tmp_path, threading.Event(), lambda *_: None).run(
        [SourceSpec("src", "upload", "Project")], ProcessingOptions()
    )
    assert [doc.path for doc in result.documents] == ["project/notes.txt"]
