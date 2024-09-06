import os
import re
import zipfile
import shutil
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Dict
from markdown_formatter import format_as_markdown, generate_toc

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".mdown",
    ".mkdn",
    ".mkd",
    ".mdwn",
    ".mdtxt",
    ".mdtext",
    ".text",
    ".html",
    ".htm",
    ".xhtml",
    ".shtml",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".py",
    ".pyw",
    ".pyc",
    ".pyo",
    ".pyd",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".json5",
    ".xml",
    ".xsl",
    ".xslt",
    ".svg",
    ".csv",
    ".tsv",
    ".rst",
    ".rest",
    ".ini",
    ".cfg",
    ".conf",
    ".config",
    ".log",
    ".log.1",
    ".log.2",
    ".bat",
    ".cmd",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".sql",
    ".mysql",
    ".pgsql",
    ".sqlite",
    ".php",
    ".phtml",
    ".php3",
    ".php4",
    ".php5",
    ".phps",
    ".rb",
    ".rbw",
    ".rake",
    ".gemspec",
    ".lua",
    ".luac",
    ".pl",
    ".pm",
    ".t",
    ".pod",
    ".go",
    ".gop",
    ".java",
    ".class",
    ".jar",
    ".cs",
    ".csx",
    ".vb",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".hh",
    ".cxx",
    ".hxx",
    ".swift",
    ".kt",
    ".kts",
    ".r",
    ".rdata",
    ".rds",
    ".rda",
    ".m",
    ".mm",
    ".tex",
    ".ltx",
    ".latex",
    ".bib",
    ".asm",
    ".s",
    ".f",
    ".for",
    ".f90",
    ".f95",
    ".f03",
    ".f08",
    ".scala",
    ".sc",
    ".clj",
    ".cljs",
    ".cljc",
    ".edn",
    ".dart",
    ".groovy",
    ".gvy",
    ".gy",
    ".gsh",
    ".ps1",
    ".psm1",
    ".psd1",
    ".elm",
    ".erl",
    ".hrl",
    ".ex",
    ".exs",
    ".hs",
    ".lhs",
    ".ml",
    ".mli",
    ".rs",
    ".vim",
    ".vimrc",
    ".dockerfile",
    ".containerfile",
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    ".toml",
    ".editorconfig",
}


def clean_text(text: str) -> str:
    """Clean the input text."""
    return re.sub(r"[^\x00-\x7F]+", "", re.sub(r"\s+", " ", text)).strip()


def process_file(
    file_path: str,
    output_dir: str,
    single_file: bool,
    all_files: List[str],
    include_metadata: bool,
    include_toc: bool,
    toc_entries: Dict[str, str],
) -> Optional[str]:
    """Process a single text file."""
    logging.info(f"Processing file: {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
            text = file.read()

        if not text.strip():
            logging.warning(f"File is empty: {file_path}")
            return None

        title = Path(file_path).stem.replace("_", " ").replace("-", " ")
        cleaned_text = clean_text(text)
        markdown_text = format_as_markdown(
            cleaned_text,
            title,
            file_path,
            all_files,
            include_metadata,
            include_toc,
            toc_entries,
        )

        if not single_file:
            output_file = Path(output_dir) / f"{title}.md"
            output_file.write_text(markdown_text, encoding="utf-8")
            logging.info(f"Saved markdown to: {output_file}")

        return markdown_text
    except Exception as e:
        logging.error(f"Error processing file {file_path}: {e}")
        return None


def process_folder(
    folder_path: str,
    output_dir: str,
    single_file: bool,
    combined_content: List[str],
    all_files: List[str],
    include_metadata: bool,
    include_toc: bool,
    toc_entries: Dict[str, str],
    gitignore_patterns: List[str],
    is_verbose: bool = False,
):
    """Process all text files in a given folder and its subfolders, excluding files/directories listed in .gitignore."""
    logging.info(f"Processing folder: {folder_path}")
    for path in Path(folder_path).rglob("*"):
        if path.is_file():
            if path.suffix.lower() in TEXT_EXTENSIONS:
                if not should_exclude(
                    path.relative_to(folder_path), gitignore_patterns
                ):
                    all_files.append(str(path))
                    if is_verbose is True:
                        print("  - Processing file", str(path))
                    result = process_file(
                        str(path),
                        output_dir,
                        single_file,
                        all_files,
                        include_metadata,
                        include_toc,
                        toc_entries,
                    )
                    if result:
                        combined_content.append(result)
            elif path.suffix.lower() == ".zip":
                temp_extract_to = path.parent / f"temp_{path.name}"
                extract_zip(str(path), str(temp_extract_to))
                process_folder(
                    str(temp_extract_to),
                    output_dir,
                    single_file,
                    combined_content,
                    all_files,
                    include_metadata,
                    include_toc,
                    toc_entries,
                    gitignore_patterns,
                )
                shutil.rmtree(temp_extract_to, ignore_errors=True)


def extract_zip(zip_path: str, extract_to: str):
    """Extract a zip file to the specified directory."""
    logging.info(f"Extracting zip file: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_to)
        logging.info(f"Extracted to: {extract_to}")
    except Exception as e:
        logging.error(f"Error extracting zip file {zip_path}: {e}")


def clone_git_repo(repo_url: str, temp_folder: str, depth: Optional[int] = None):
    """Clone a GitHub repository to the specified directory."""
    logging.info(f"Cloning GitHub repository: {repo_url}")
    try:
        cmd = ["git", "clone"]
        if depth is not None:
            cmd.extend(["--depth", str(depth)])
        cmd.extend([repo_url, temp_folder])
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(result.stdout)
        logging.info(f"Cloned to: {temp_folder}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Error cloning GitHub repository {repo_url}: {e}")
        logging.error(e.stderr)


def should_exclude(path: Path, gitignore_patterns: List[str]) -> bool:
    """Check if the given path should be excluded based on .gitignore patterns."""
    if ".git" in path.parts:
        return True
    for pattern in gitignore_patterns:
        if pattern in path.parts:
            return True
    return False


def process_gitignore(filepath: str) -> List[str]:
    """Open a gitignore file to get a list of ignored paths"""
    with open(filepath, "r", encoding="utf-8") as gitignore_file:
        return [
            line.strip()
            for line in gitignore_file
            if line.strip() and not line.startswith("#")
        ]


def process_input(
    input_paths: List[str],
    output_path: str,
    temp_folder: str,
    single_file: bool,
    repo_depth: Optional[int],
    include_metadata: bool,
    include_toc: bool,
    is_verbose: bool = False,
    gitignore: Optional[str | None] = None,
    ignore_paths: Optional[List[str]] = [],
) -> str:
    """Process each item in the input paths: directories, text files, zip files, and GitHub repos."""
    combined_content = []
    all_files = []
    toc_entries: Dict[str, str] = {}
    output_dir = Path(output_path).parent if single_file else Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    global_ignore_patterns = [*ignore_paths]
    if gitignore is not None:
        global_ignore_patterns = [*ignore_paths, *process_gitignore(gitignore)]
    for item_path in input_paths:
        path = Path(item_path)
        if is_verbose is True:
            print("Processing", item_path)
        if path.is_dir():
            gitignore_patterns = global_ignore_patterns
            gitignore_path = Path(item_path) / ".gitignore"
            if gitignore_path.exists():
                gitignore_patterns = [
                    *global_ignore_patterns,
                    *process_gitignore(gitignore_path),
                ]
            process_folder(
                str(path),
                str(output_dir),
                single_file,
                combined_content,
                all_files,
                include_metadata,
                include_toc,
                toc_entries,
                gitignore_patterns,
                is_verbose,
            )
        elif path.suffix.lower() in TEXT_EXTENSIONS:
            all_files.append(str(path))
            result = process_file(
                str(path),
                str(output_dir),
                single_file,
                all_files,
                include_metadata,
                include_toc,
                toc_entries,
            )
            if result:
                combined_content.append(result)
        elif path.suffix.lower() == ".zip":
            extract_to = Path(temp_folder) / path.stem
            extract_zip(str(path), str(extract_to))
            process_folder(
                str(extract_to),
                str(output_dir),
                single_file,
                combined_content,
                all_files,
                include_metadata,
                include_toc,
                toc_entries,
                gitignore_patterns,
            )
            shutil.rmtree(extract_to, ignore_errors=True)
        elif item_path.startswith("https://github.com"):
            repo_name = Path(item_path).name.replace(".git", "")
            repo_temp_folder = Path(temp_folder) / repo_name
            clone_git_repo(item_path, str(repo_temp_folder), depth=repo_depth)
            process_folder(
                str(repo_temp_folder),
                str(output_dir),
                single_file,
                combined_content,
                all_files,
                include_metadata,
                include_toc,
                toc_entries,
                gitignore_patterns,
            )
            shutil.rmtree(repo_temp_folder, ignore_errors=True)

    if single_file and combined_content:
        output_file = Path(output_path)
        content = "\n---\n\n".join(combined_content)
        if include_toc:
            toc = generate_toc(toc_entries)
            content = toc + "\n---\n\n" + content
        output_file.write_text(content, encoding="utf-8")
        logging.info(f"Combined content saved to: {output_file}")
    elif single_file and not combined_content:
        logging.warning("No content was processed. Output file not created.")
    else:
        logging.info(f"Individual Markdown files saved in: {output_dir}")

    return str(output_dir if not single_file else Path(output_path).parent)
