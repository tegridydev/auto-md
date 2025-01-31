import datetime
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


import chardet
from pdfminer.high_level import extract_text as extract_pdf_text
import docx
from bs4 import BeautifulSoup
import magic

# -------------------------------
# Global Constants
# -------------------------------

GLOBAL_VERSION = "2.0"
DEFAULT_TAGS = ["auto-md", "documentation", "AI", "LLM", "RAG"]
DEFAULT_SUMMARY = "Converted by Auto‑MD v2.0 interactive converter."


# -------------------------------
# Helper Functions
# -------------------------------

def is_hidden(file: Path) -> bool:
    """Return True if any part of the file path starts with a dot."""
    return any(part.startswith('.') for part in file.parts)


def is_text_based(file: Path) -> bool:
    """
    Dynamically determine whether a file is text-based using its MIME type.

    Returns True if the MIME type starts with 'text/', or if it matches one of the
    additional allowed types (e.g. PDFs, DOCX, HTML, JSON, or XML).
    """
    try:
        mime = magic.from_file(str(file), mime=True)
    except Exception as e:
        logging.error(f"Error detecting MIME type for {file}: {e}")
        return False

    if mime is None:
        return False

    if mime.startswith("text/"):
        return True


    allowed_mimes = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "text/html",
        "application/json",
        "application/xml",
    }
    return mime in allowed_mimes


def should_process(file: Path) -> bool:
    """
    Determine whether a file should be processed:
      - It must not be hidden.
      - Its MIME type (determined dynamically) indicates that it is text-based.
    """
    return (not is_hidden(file)) and is_text_based(file)


def clean_text(text: str) -> str:
    """Remove non‑ASCII characters and extra whitespace."""
    return re.sub(r'[^\x00-\x7F]+', '', re.sub(r'\s+', ' ', text)).strip()


def create_yaml_front_matter(
        title: str,
        source: str,
        version: str = GLOBAL_VERSION,
        tags: Optional[List[str]] = None,
        summary: str = DEFAULT_SUMMARY
) -> str:
    """Create a YAML front matter block with metadata."""
    if tags is None:
        tags = DEFAULT_TAGS
    metadata = {
        "title": title,
        "date": datetime.datetime.now().isoformat(),
        "source": source,
        "document_id": str(uuid.uuid4()),
        "version": version,
        "tags": tags,
        "summary": summary,
    }
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f'{key}: "{value}"')
    lines.append("---")
    return "\n".join(lines)


def format_as_markdown(
        text: str,
        title: str,
        file_path: str,
        include_metadata: bool,
        include_toc: bool,
        toc_entries: Dict[str, str],
        global_mode: bool = False
) -> str:
    """
    Format the given text into a Markdown document.

    If include_metadata is True and global_mode is False, a YAML front matter block
    is prepended. In global_mode (when combining multiple files) the per‑file YAML is omitted.
    A top‑level header is added, and a clear chunk delimiter ("---") is appended.
    """
    content_parts = []

    if include_metadata and not global_mode:
        content_parts.append(create_yaml_front_matter(title, get_source(file_path)))

    content_parts.append(f"# {title}\n")

    if include_toc:
        toc_entries[title] = f"#{title.lower().replace(' ', '-')}"

    content_parts.append(text)
    content_parts.append("\n---\n")

    return "\n".join(content_parts)


def get_source(file_path: str) -> str:
    """
    Determine the source (repository or folder) from the file path.
    If the path contains 'github.com', return the last two path parts;
    otherwise return the parent folder.
    """
    lower_path = file_path.lower()
    if "github.com" in lower_path:
        repo_parts = Path(file_path).parts
        return "/".join(repo_parts[-2:]) if len(repo_parts) >= 2 else file_path
    return str(Path(file_path).parent)


def generate_toc(toc_entries: Dict[str, str]) -> str:
    """Generate a Markdown table of contents from collected entries."""
    toc_lines = ["## Table of Contents"]
    for title, link in toc_entries.items():
        toc_lines.append(f"- [{title}]({link})")
    return "\n".join(toc_lines) + "\n"


# -------------------------------
# Advanced Text Extraction
# -------------------------------

def read_file(path: str) -> Optional[str]:
    """
    Read and extract text from various file types.

    - For PDFs, uses pdfminer.six.
    - For DOCX files, uses python‑docx.
    - For HTML files, uses BeautifulSoup.
    - Otherwise, assumes plain text and uses chardet for encoding detection.
    """
    file_path = Path(path)
    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            return extract_pdf_text(path)
        elif ext == ".docx":
            doc = docx.Document(path)
            return "\n".join(para.text for para in doc.paragraphs)
        elif ext in {".html", ".htm", ".xhtml"}:
            with open(path, 'rb') as f:
                raw_data = f.read()
            soup = BeautifulSoup(raw_data, "html.parser")
            return soup.get_text(separator="\n")
        else:
            with open(path, 'rb') as f:
                raw_data = f.read()
            result = chardet.detect(raw_data)
            encoding = result.get('encoding') or 'utf-8'
            return raw_data.decode(encoding, errors='replace')
    except Exception as e:
        logging.error(f"Failed to read file {path}: {e}")
        return None


# -------------------------------
# File Processing Functions
# -------------------------------

def process_file(
        file_path: str,
        output_dir: str,
        single_file: bool,
        include_metadata: bool,
        include_toc: bool,
        toc_entries: Dict[str, str],
        logger: logging.Logger,
        global_mode: bool = False
) -> Optional[str]:
    """
    Process a single file into Markdown.

    Parameters:
      - file_path: The path to the file.
      - output_dir: Directory for individual file output (if not single_file).
      - single_file: If True, files will be combined into one output.
      - global_mode: If True, do not include per‑file YAML front matter (for combined output).
    """
    logger.info(f"Processing file: {file_path}")
    text = read_file(file_path)
    if not text or not text.strip():
        logger.warning(f"File is empty or could not be read: {file_path}")
        return None

    title = Path(file_path).stem.replace('_', ' ').replace('-', ' ')
    cleaned_text = clean_text(text)
    md_text = format_as_markdown(
        cleaned_text, title, file_path, include_metadata, include_toc, toc_entries, global_mode=global_mode
    )
    if not single_file:
        out_file = Path(output_dir) / f"{title}.md"
        out_file.write_text(md_text, encoding="utf-8")
        logger.info(f"Saved markdown to: {out_file}")
    return md_text


def extract_zip(zip_path: str, extract_to: str, logger: logging.Logger) -> None:
    """Extract a ZIP archive to a specified folder."""
    logger.info(f"Extracting zip file: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        logger.info(f"Extracted to: {extract_to}")
    except Exception as e:
        logger.error(f"Error extracting zip file {zip_path}: {e}")


def clone_git_repo(repo_url: str, temp_folder: str, depth: Optional[int], logger: logging.Logger) -> None:
    """Clone a GitHub repository into the specified temporary folder."""
    logger.info(f"Cloning GitHub repository: {repo_url}")
    try:
        cmd = ["git", "clone"]
        if depth is not None:
            cmd.extend(["--depth", str(depth)])
        cmd.extend([repo_url, temp_folder])
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(result.stdout)
        logger.info(f"Cloned to: {temp_folder}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error cloning GitHub repository {repo_url}: {e}")
        logger.error(e.stderr)


def scan_source(source: str, logger: logging.Logger) -> Tuple[List[Path], List[Path]]:
    """
    Scan the input source and return a tuple:
      (list_of_eligible_files, list_of_temporary_directories_created)

    The source can be:
      - A folder (recursively scanned, dynamically filtering out hidden/non‑text files)
      - A ZIP file (extracted into a temporary folder)
      - A GitHub repository URL (cloned into a temporary folder)
      - A single file
    """
    temp_dirs = []
    files: List[Path] = []
    if os.path.isdir(source):
        files = [f for f in Path(source).rglob("*") if f.is_file() and should_process(f)]
    elif source.lower().endswith(".zip"):
        temp_extract = Path(tempfile.mkdtemp(prefix="automd2_zip_"))
        temp_dirs.append(temp_extract)
        try:
            extract_zip(source, str(temp_extract), logger)
        except Exception as e:
            logger.error(f"Error during ZIP extraction: {e}")
            return [], temp_dirs
        files = [f for f in temp_extract.rglob("*") if f.is_file() and should_process(f)]
    elif source.startswith("https://github.com"):
        temp_repo = Path(tempfile.mkdtemp(prefix="automd2_repo_"))
        temp_dirs.append(temp_repo)
        clone_git_repo(source, str(temp_repo), None, logger)
        files = [f for f in temp_repo.rglob("*") if f.is_file() and should_process(f)]
    elif os.path.isfile(source):
        file_path = Path(source)
        if should_process(file_path):
            files = [file_path]
        else:
            logger.error("The provided file is either hidden or not a recognized text file.")
    else:
        logger.error("Input source not recognized. Provide a folder, ZIP file, GitHub URL, or file.")
    return files, temp_dirs


def parse_selection(selection: str, max_index: int) -> List[int]:
    """
    Parse a comma-separated list of numbers (and ranges) into a list of 0‑based indices.

    Example: "1,3-5" returns [0, 2, 3, 4].
    """
    indices = []
    tokens = selection.split(',')
    for token in tokens:
        token = token.strip()
        if '-' in token:
            try:
                start, end = token.split('-')
                indices.extend(range(int(start) - 1, int(end)))
            except Exception:
                continue
        else:
            try:
                indices.append(int(token) - 1)
            except Exception:
                continue
    return sorted(set(i for i in indices if 0 <= i < max_index))


# -------------------------------
# Main Interactive Menu
# -------------------------------

def main() -> None:

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("automd2")

    print("=" * 60)
    print("Welcome to Auto‑MD v2.0 – File-to-Markdown Converter")
    print("=" * 60)
    print("\nEnter your input source. This can be a folder path, a ZIP file path,")
    print("a GitHub repository URL (e.g., https://github.com/user/repo), or a single file path.")
    source = input("Input source: ").strip()
    if not source:
        print("No input provided. Exiting.")
        sys.exit(1)


    files, temp_dirs = scan_source(source, logger)
    if not files:
        print("No eligible text files were found. Exiting.")
        sys.exit(1)


    if len(files) == 1:
        selected_files = files
        print("\nOnly one eligible file was found; auto-selected:")
        print(f"  1. {files[0]}")
    else:
        print("\nEligible files found:")
        for idx, file in enumerate(files, start=1):
            print(f"  {idx}. {file}")
        print("\nEnter the numbers of the files to process (comma separated) or type 'all':")
        selection = input("Selection: ").strip().lower()
        if selection == "all":
            selected_files = files
        else:
            selected_indices = parse_selection(selection, len(files))
            if not selected_indices:
                print("No valid files selected. Exiting.")
                sys.exit(1)
            selected_files = [files[i] for i in selected_indices]

    print("\nSelected files:")
    for file in selected_files:
        print(f"  - {file}")


    out_mode = input("\nOutput to a single combined Markdown file? (y/n) [y]: ").strip().lower() or "y"
    single_file = (out_mode == "y")

    if single_file:
        output_path = input("Enter the output file path (e.g., combined_output.md): ").strip()
        if not output_path:
            print("No output file provided. Exiting.")
            sys.exit(1)
    else:
        output_path = input("Enter the output directory path: ").strip()
        if not output_path:
            print("No output directory provided. Exiting.")
            sys.exit(1)
        Path(output_path).mkdir(parents=True, exist_ok=True)


    include_metadata = (input(
        "Include metadata (YAML front matter) in the output? (y/n) [y]: ").strip().lower() or "y") == "y"
    include_toc = (input("Include a table of contents? (y/n) [y]: ").strip().lower() or "y") == "y"


    custom_tags_input = input("Enter custom tags (comma separated) or press enter to use defaults: ").strip()
    custom_tags = [tag.strip() for tag in custom_tags_input.split(',') if
                   tag.strip()] if custom_tags_input else DEFAULT_TAGS
    custom_summary = input("Enter a custom summary or press enter to use default: ").strip() or DEFAULT_SUMMARY


    combined_content = []
    toc_entries: Dict[str, str] = {}

    print("\nProcessing files...")

    global_mode = single_file
    for file in selected_files:
        md_text = process_file(
            str(file),
            output_path if not single_file else str(Path(output_path).parent),
            single_file,
            include_metadata,
            include_toc,
            toc_entries,
            logger,
            global_mode=global_mode
        )
        if md_text:
            combined_content.append(md_text)

    if single_file and combined_content:

        global_yaml = create_yaml_front_matter(
            title="Combined Auto‑MD v2.0 Output",
            source=source,
            tags=custom_tags,
            summary=custom_summary
        )
        toc_block = generate_toc(toc_entries) if include_toc else ""
        content_body = "\n---\n".join(combined_content)
        final_content = "\n".join([global_yaml, toc_block, content_body])
        Path(output_path).write_text(final_content, encoding="utf-8")
        print(f"\nCombined Markdown file saved to: {output_path}")
    elif not single_file:
        print(f"\nIndividual Markdown files have been saved in: {output_path}")
    else:
        print("\nNo content was processed.")


    for d in temp_dirs:
        shutil.rmtree(d, ignore_errors=True)

    print("\nProcessing complete. Exiting.")


if __name__ == "__main__":
    main()
