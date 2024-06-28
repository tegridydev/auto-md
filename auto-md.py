import os
import re
import zipfile
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import stat
from datetime import datetime

# ~~~list of plain text file extensions to include~~~
TEXT_EXTENSIONS = [
    '.txt', '.md', '.html', '.css', '.py', '.js', '.yaml', '.yml',
    '.json', '.xml', '.csv', '.rst', '.ini', '.cfg', '.log', '.conf'
]

# ~~~list of file extensions to skip~~~
SKIP_EXTENSIONS = [
    '.exe', '.dll', '.bin', '.img', '.iso', '.tar', '.gz', '.zip',
    '.rar', '.7z', '.mp3', '.mp4', '.wav', '.flac', '.mov', '.avi',
    '.mkv', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.ico'
]

def clean_text(text):
    """
    Perform basic cleaning of the text.
    """
    
    text = re.sub(r'\s+', ' ', text)
    
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    return text.strip()

def format_as_markdown(text, title):
    """
    Format the cleaned text into Markdown structure.
    """
    lines = text.split('\n')
    formatted_text = f"# {title}\n\n"
    formatted_text += "## Metadata\n"
    formatted_text += f"- **Generated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    formatted_text += f"- **Source:** {title}\n\n"
    formatted_text += "## Table of Contents\n"
    for i, line in enumerate(lines):
        if line.strip():
            formatted_text += f"- [Section {i+1}](#section-{i+1})\n"
    formatted_text += "\n"
    for i, line in enumerate(lines):
        formatted_text += f"## Section {i+1}\n{line.strip()}\n\n"
    return formatted_text

def process_file(file_path, combined_content):
    """
    Process a single text file, clean, format, and add to combined content.
    """
    print(f"Processing file: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            text = file.read()
        title = os.path.basename(file_path).replace('_', ' ').replace('-', ' ').split('.')[0]
        cleaned_text = clean_text(text)
        markdown_text = format_as_markdown(cleaned_text, title)
        combined_content.append(markdown_text)
    except Exception as e:
        print(f"Error processing file {file_path}: {e}")

def process_folder(folder_path, combined_content):
    """
    Process all text files in a given folder (and its subfolders).
    """
    print(f"Processing folder: {folder_path}")
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            if any(file.endswith(ext) for ext in TEXT_EXTENSIONS):
                process_file(file_path, combined_content)
            elif file.endswith('.zip'):
                temp_extract_to = os.path.join(root, f"temp_{os.path.basename(file)}")
                extract_zip(file_path, temp_extract_to)
                process_folder(temp_extract_to, combined_content)
                shutil.rmtree(temp_extract_to)
            elif any(file.endswith(ext) for ext in SKIP_EXTENSIONS):
                print(f"Skipping file: {file_path}")

def extract_zip(zip_path, extract_to):
    """
    Extract a zip file to the specified directory.
    """
    print(f"Extracting zip file: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        print(f"Extracted to: {extract_to}")
    except Exception as e:
        print(f"Error extracting zip file {zip_path}: {e}")

def clone_git_repo(repo_url, temp_folder):
    """
    Clone a GitHub repository to the specified directory.
    """
    print(f"Cloning GitHub repository: {repo_url}")
    try:
        subprocess.run(["git", "clone", repo_url, temp_folder], check=True)
        print(f"Cloned to: {temp_folder}")
    except subprocess.CalledProcessError as e:
        print(f"Error cloning GitHub repository {repo_url}: {e}")

def on_rm_error(func, path, exc_info):
    """
    Error handler for removing read-only files.
    """
    os.chmod(path, stat.S_IWRITE)
    os.unlink(path)

def process_input(input_paths, output_file_path, temp_folder):
    """
    Process each item in the input paths: directories, text files, zip files, and GitHub repos.
    """
    combined_content = []

    for item_path in input_paths:
        if os.path.isdir(item_path):
            # Process directories
            print(f"Processing directory: {item_path}")
            process_folder(item_path, combined_content)

        elif any(item_path.endswith(ext) for ext in TEXT_EXTENSIONS):
            # Process text files
            process_file(item_path, combined_content)

        elif item_path.endswith('.zip'):
            
            extract_to = os.path.join(temp_folder, os.path.basename(item_path).replace('.zip', ''))
            extract_zip(item_path, extract_to)
            process_folder(extract_to, combined_content)
            shutil.rmtree(extract_to)  

        elif item_path.startswith("https://github.com"):
            
            repo_name = os.path.basename(item_path).replace('.git', '')
            repo_temp_folder = os.path.join(temp_folder, repo_name)
            clone_git_repo(item_path, repo_temp_folder)
            process_folder(repo_temp_folder, combined_content)
            shutil.rmtree(repo_temp_folder, onerror=on_rm_error)  

        elif any(item_path.endswith(ext) for ext in SKIP_EXTENSIONS):
            
            print(f"Skipping file: {item_path}")

    
    with open(output_file_path, 'w', encoding='utf-8') as output_file:
        output_file.write("\n".join(combined_content))
    print(f"Combined content saved to: {output_file_path}")

def browse_input_files():
    files_selected = filedialog.askopenfilenames(filetypes=[("All files", "*.*"), ("Zip files", "*.zip")])
    input_files_entry.delete(0, tk.END)
    input_files_entry.insert(0, files_selected)
    if files_selected:
        output_file_name = os.path.splitext(os.path.basename(files_selected[0]))[0] + ".md"
        output_file_entry.delete(0, tk.END)
        output_file_entry.insert(0, output_file_name)

def browse_output_file():
    file_selected = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown files", "*.md")])
    output_file_entry.delete(0, tk.END)
    output_file_entry.insert(0, file_selected)

def start_processing():
    input_files = input_files_entry.get().split()
    output_file_path = output_file_entry.get()
    temp_folder = 'temp'

    if not os.path.exists(temp_folder):
        os.makedirs(temp_folder)

    process_input(input_files, output_file_path, temp_folder)

    
    shutil.rmtree(temp_folder, onerror=on_rm_error)
    messagebox.showinfo("Success", f"Processing complete. Output saved to: {output_file_path}")


root = tk.Tk()
root.title("~auto~md~")

input_files_label = tk.Label(root, text="Input Files or GitHub Repos:")
input_files_label.grid(row=0, column=0, padx=10, pady=5)
input_files_entry = tk.Entry(root, width=50)
input_files_entry.grid(row=0, column=1, padx=10, pady=5)
browse_input_button = tk.Button(root, text="Browse", command=browse_input_files)
browse_input_button.grid(row=0, column=2, padx=10, pady=5)

output_file_label = tk.Label(root, text="Output File:")
output_file_label.grid(row=1, column=0, padx=10, pady=5)
output_file_entry = tk.Entry(root, width=50)
output_file_entry.grid(row=1, column=1, padx=10, pady=5)
browse_output_button = tk.Button(root, text="Browse", command=browse_output_file)
browse_output_button.grid(row=1, column=2, padx=10, pady=5)

start_button = tk.Button(root, text="Start Processing", command=start_processing)
start_button.grid(row=2, column=1, pady=20)

root.mainloop()
