import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import logging
import tempfile
import uuid
import threading
import queue
from pathlib import Path
from file_processor import process_input


class QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))


class AutoMDApp:
    def __init__(self, master):
        self.master = master
        master.title("Auto MD")
        master.geometry("1000x800")
        master.resizable(True, True)

        self.temp_dir = Path(tempfile.gettempdir()) / f"automd_temp_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.log_queue = queue.Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(self.queue_handler)

        self.style = ttk.Style()
        self.apply_dark_theme()

        self.create_widgets()

    def apply_dark_theme(self):
        self.style.theme_use('clam')
        self.style.configure('.', background='#2E2E2E', foreground='white')
        self.style.configure('TButton', background='#4A4A4A', foreground='white')
        self.style.map('TButton', background=[('active', '#5A5A5A')])
        self.style.configure('TEntry', fieldbackground='#3E3E3E', foreground='white')
        self.style.configure('TCheckbutton', background='#2E2E2E', foreground='white')
        self.style.configure('TLabel', background='#2E2E2E', foreground='white')
        self.style.configure('TFrame', background='#2E2E2E')

    def create_widgets(self):
        main_frame = ttk.Frame(self.master, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        
        ttk.Label(main_frame, text="Input Files or GitHub Repos:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.input_files_entry = ttk.Entry(main_frame, width=80)
        self.input_files_entry.grid(row=0, column=1, columnspan=2, pady=5, padx=(0, 5))
        ttk.Button(main_frame, text="Browse", command=self.browse_input_files).grid(row=0, column=3, pady=5)

        
        ttk.Label(main_frame, text="Output:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.output_entry = ttk.Entry(main_frame, width=80)
        self.output_entry.grid(row=1, column=1, columnspan=2, pady=5, padx=(0, 5))
        ttk.Button(main_frame, text="Browse", command=self.browse_output).grid(row=1, column=3, pady=5)

        
        options_frame = ttk.LabelFrame(main_frame, text="Options", padding="10")
        options_frame.grid(row=2, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=10)

        self.single_file_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Output to single file", variable=self.single_file_var,
                        command=self.toggle_output_mode).grid(row=0, column=0, sticky=tk.W)

        ttk.Label(options_frame, text="Repository clone depth:").grid(row=0, column=1, sticky=tk.W, padx=(20, 5))
        self.repo_depth_var = tk.StringVar(value="Full")
        repo_depth_combo = ttk.Combobox(options_frame, textvariable=self.repo_depth_var,
                                        values=["Full", "1", "5", "10", "20", "50", "100"])
        repo_depth_combo.grid(row=0, column=2, sticky=tk.W)

        self.include_metadata_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Include metadata", variable=self.include_metadata_var).grid(row=1,
                                                                                                         column=0,
                                                                                                         sticky=tk.W)

        self.include_toc_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Include table of contents", variable=self.include_toc_var).grid(row=1,
                                                                                                             column=1,
                                                                                                             columnspan=2,
                                                                                                             sticky=tk.W)

        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=3, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=10)

        self.status_label = ttk.Label(main_frame, text="")
        self.status_label.grid(row=4, column=0, columnspan=4, pady=5)

        
        self.console_output = scrolledtext.ScrolledText(main_frame, height=20, bg='#1E1E1E', fg='white')
        self.console_output.grid(row=5, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        self.console_output.config(state=tk.DISABLED)

        
        ttk.Button(main_frame, text="Start Processing", command=self.start_processing).grid(row=6, column=1,
                                                                                            columnspan=2, pady=20)

        
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(5, weight=1)

        self.master.after(100, self.check_queue)

    def check_queue(self):
        while True:
            try:
                message = self.log_queue.get_nowait()
                self.console_output.config(state=tk.NORMAL)
                self.console_output.insert(tk.END, message + '\n')
                self.console_output.see(tk.END)
                self.console_output.config(state=tk.DISABLED)
            except queue.Empty:
                break
        self.master.after(100, self.check_queue)

    def browse_input_files(self):
        files_selected = filedialog.askopenfilenames(filetypes=[("All files", "*.*"), ("Zip files", "*.zip")])
        self.input_files_entry.delete(0, tk.END)
        self.input_files_entry.insert(0, " ".join(files_selected))
        if files_selected:
            output_name = Path(files_selected[0]).stem
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, output_name + (".md" if self.single_file_var.get() else ""))

    def browse_output(self):
        if self.single_file_var.get():
            file_selected = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown files", "*.md")])
        else:
            file_selected = filedialog.askdirectory()
        self.output_entry.delete(0, tk.END)
        self.output_entry.insert(0, file_selected)

    def toggle_output_mode(self):
        current_output = self.output_entry.get()
        if self.single_file_var.get():
            if not current_output.endswith('.md'):
                self.output_entry.delete(0, tk.END)
                self.output_entry.insert(0, current_output + '.md')
        else:
            if current_output.endswith('.md'):
                self.output_entry.delete(0, tk.END)
                self.output_entry.insert(0, Path(current_output).stem)

    def start_processing(self):
        input_files = self.input_files_entry.get().split()
        output_path = self.output_entry.get()
        single_file = self.single_file_var.get()
        repo_depth = None if self.repo_depth_var.get() == "Full" else int(self.repo_depth_var.get())
        include_metadata = self.include_metadata_var.get()
        include_toc = self.include_toc_var.get()

        if not input_files:
            messagebox.showerror("Error", "Please select input files or repositories.")
            return
        if not output_path:
            messagebox.showerror("Error", "Please specify an output path.")
            return

        self.status_label.config(text="Processing...")
        self.progress_var.set(0)
        self.master.update()

        def process_thread():
            try:
                output_dir = process_input(input_files, output_path, str(self.temp_dir), single_file, repo_depth,
                                           include_metadata, include_toc)
                self.master.after(0, lambda: self.progress_var.set(100))
                self.master.after(0, lambda: self.status_label.config(text="Processing complete!"))
                self.master.after(0, lambda: self.show_completion_dialog(output_dir))
            except Exception as e:
                self.master.after(0, lambda: messagebox.showerror("Error", f"An error occurred: {str(e)}"))
                self.master.after(0, lambda: self.status_label.config(text="Processing failed."))

        threading.Thread(target=process_thread, daemon=True).start()

    def show_completion_dialog(self, output_dir):
        result = messagebox.askquestion("Success", "Processing complete. Would you like to open the output folder?",
                                        icon='info')
        if result == 'yes':
            self.open_output_folder(output_dir)

    def open_output_folder(self, path):
        import os
        import platform
        import subprocess

        path = os.path.realpath(path)
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", path])
        else:  # Linux and other Unix-like
            subprocess.Popen(["xdg-open", path])


if __name__ == "__main__":
    root = tk.Tk()
    app = AutoMDApp(root)
    root.mainloop()