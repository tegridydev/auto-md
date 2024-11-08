from datetime import datetime
from pathlib import Path
from typing import List, Dict

def format_as_markdown(text: str, title: str, file_path: str, all_files: List[str], include_metadata: bool, include_toc: bool, toc_entries: Dict[str, str]) -> str:
    parts = [f"# {title}\n"]

    if include_metadata:
        parts.extend([
            "## Metadata",
            f"- **Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **Source:** {get_source(file_path)}",
            ""
        ])

    if include_toc:
        toc_entries[title] = f"#{title.lower().replace(' ', '-')}"

    parts.extend([f"# {title}", "", text])

    return "\n".join(parts)

def get_source(file_path: str) -> str:
    if 'github.com' in file_path.lower():
        repo_parts = Path(file_path).parts
        return f"{repo_parts[-2]}/{repo_parts[-1]}"
    return Path(file_path).parent.name

def generate_toc(toc_entries: Dict[str, str]) -> str:
    toc = ["## Table of Contents"]
    for title, link in toc_entries.items():
        toc.append(f"- [{title}]({link})")
    return "\n".join(toc) + "\n"