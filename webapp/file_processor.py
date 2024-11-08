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
    '.txt', '.md', '.markdown', '.mdown', '.mkdn', '.mkd', '.mdwn', '.mdtxt', '.mdtext', '.text',
    '.html', '.htm', '.xhtml', '.shtml', '.css', '.scss', '.sass', '.less',
    '.py', '.pyw', '.pyc', '.pyo', '.pyd', '.js', '.jsx', '.ts', '.tsx',
    '.yaml', '.yml', '.json', '.jsonl', '.json5', '.xml', '.xsl', '.xslt', '.svg',
    '.csv', '.tsv', '.rst', '.rest', '.ini', '.cfg', '.conf', '.config',
    '.log', '.log.1', '.log.2', '.bat', '.cmd', '.sh', '.bash', '.zsh', '.fish',
    '.sql', '.mysql', '.pgsql', '.sqlite', '.php', '.phtml', '.php3', '.php4', '.php5', '.phps',
    '.rb', '.rbw', '.rake', '.gemspec', '.lua', '.luac', '.pl', '.pm', '.t', '.pod',
    '.go', '.gop', '.java', '.class', '.jar', '.cs', '.csx', '.vb',
    '.c', '.h', '.cpp', '.hpp', '.cc', '.hh', '.cxx', '.hxx', '.swift', '.kt', '.kts',
    '.r', '.rdata', '.rds', '.rda', '.m', '.mm', '.tex', '.ltx', '.latex', '.bib',
    '.asm', '.s', '.f', '.for', '.f90', '.f95', '.f03', '.f08', '.scala', '.sc',
    '.clj', '.cljs', '.cljc', '.edn', '.dart', '.groovy', '.gvy', '.gy', '.gsh',
    '.ps1', '.psm1', '.psd1', '.elm', '.erl', '.hrl', '.ex', '.exs', '.hs', '.lhs',
    '.ml', '.mli', '.rs', '.vim', '.vimrc', '.dockerfile', '.containerfile',
    '.gitignore', '.gitattributes', '.gitmodules', '.toml', '.editorconfig'
}

def clean_text(text: str) -> str:
    return re.sub(r'[^\x00-\x7F]+', '', re.sub(r'\s+', ' ', text)).strip()

def process_file(file_path: str, output_dir: str, single_file: bool, all_files: List[str], include_metadata: bool,
                 include_toc: bool, toc_entries: Dict[str, str], logger_adapter) -> Optional[str]:
    logger_adapter.info(f"Processing file: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            text = file.read()

        if not text.strip():
            logger_adapter.warning(f"File is empty: {file_path}")
            return None

        title = Path(file_path).stem.replace('_', ' ').replace('-', ' ')
        cleaned_text = clean_text(text)
        markdown_text = format_as_markdown(cleaned_text, title, file_path, all_files, include_metadata, include_toc,
                                           toc_entries)

        if not single_file:
            output_file = Path(output_dir) / f"{title}.md"
            output_file.write_text(markdown_text, encoding='utf-8')
            logger_adapter.info(f"Saved markdown to: {output_file}")

        return markdown_text
    except Exception as e:
        logger_adapter.error(f"Error processing file {file_path}: {e}")
        return None

def process_folder(folder_path: str, output_dir: str, single_file: bool, combined_content: List[str],
                   all_files: List[str], include_metadata: bool, include_toc: bool, toc_entries: Dict[str, str],
                   logger_adapter):
    logger_adapter.info(f"Processing folder: {folder_path}")
    for path in Path(folder_path).rglob('*'):
        if path.is_file():
            if path.suffix.lower() in TEXT_EXTENSIONS:
                all_files.append(str(path))
                result = process_file(str(path), output_dir, single_file, all_files, include_metadata, include_toc,
                                      toc_entries, logger_adapter)
                if result:
                    combined_content.append(result)
            elif path.suffix.lower() == '.zip':
                temp_extract_to = path.parent / f"temp_{path.name}"
                extract_zip(str(path), str(temp_extract_to), logger_adapter)
                process_folder(str(temp_extract_to), output_dir, single_file, combined_content, all_files,
                               include_metadata, include_toc, toc_entries, logger_adapter)
                shutil.rmtree(temp_extract_to, ignore_errors=True)

def extract_zip(zip_path: str, extract_to: str, logger_adapter):
    logger_adapter.info(f"Extracting zip file: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        logger_adapter.info(f"Extracted to: {extract_to}")
    except Exception as e:
        logger_adapter.error(f"Error extracting zip file {zip_path}: {e}")

def clone_git_repo(repo_url: str, temp_folder: str, depth: Optional[int] = None, logger_adapter = None):
    logger_adapter.info(f"Cloning GitHub repository: {repo_url}")
    try:
        cmd = ["git", "clone"]
        if depth is not None:
            cmd.extend(["--depth", str(depth)])
        cmd.extend([repo_url, temp_folder])
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger_adapter.info(result.stdout)
        logger_adapter.info(f"Cloned to: {temp_folder}")
    except subprocess.CalledProcessError as e:
        logger_adapter.error(f"Error cloning GitHub repository {repo_url}: {e}")
        logger_adapter.error(e.stderr)

def process_input(input_paths: List[str], output_path: str, temp_folder: str, single_file: bool,
                  repo_depth: Optional[int], include_metadata: bool, include_toc: bool, logger_adapter) -> str:
    combined_content = []
    all_files = []
    toc_entries: Dict[str, str] = {}
    output_dir = Path(output_path).parent if single_file else Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    for item_path in input_paths:
        path = Path(item_path)
        if path.is_dir():
            process_folder(str(path), str(output_dir), single_file, combined_content, all_files, include_metadata,
                           include_toc, toc_entries, logger_adapter)
        elif path.suffix.lower() in TEXT_EXTENSIONS:
            all_files.append(str(path))
            result = process_file(str(path), str(output_dir), single_file, all_files, include_metadata, include_toc,
                                  toc_entries, logger_adapter)
            if result:
                combined_content.append(result)
        elif path.suffix.lower() == '.zip':
            extract_to = Path(temp_folder) / path.stem
            extract_zip(str(path), str(extract_to), logger_adapter)
            process_folder(str(extract_to), str(output_dir), single_file, combined_content, all_files, include_metadata,
                           include_toc, toc_entries, logger_adapter)
            shutil.rmtree(extract_to, ignore_errors=True)
        elif str(item_path).startswith("https://github.com"):
            repo_name = Path(item_path).name.replace('.git', '')
            repo_temp_folder = Path(temp_folder) / repo_name
            clone_git_repo(item_path, str(repo_temp_folder), depth=repo_depth, logger_adapter=logger_adapter)
            process_folder(str(repo_temp_folder), str(output_dir), single_file, combined_content, all_files,
                           include_metadata, include_toc, toc_entries, logger_adapter)
            shutil.rmtree(repo_temp_folder, ignore_errors=True)

    if single_file and combined_content:
        output_file = Path(output_path)
        content = "\n---\n\n".join(combined_content)
        if include_toc:
            toc = generate_toc(toc_entries)
            content = toc + "\n---\n\n" + content
        output_file.write_text(content, encoding='utf-8')
        logger_adapter.info(f"Combined content saved to: {output_file}")
    elif single_file and not combined_content:
        logger_adapter.warning("No content was processed. Output file not created.")
    else:
        logger_adapter.info(f"Individual Markdown files saved in: {output_dir}")

    return str(output_dir if not single_file else Path(output_path).parent)