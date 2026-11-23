# Auto-MD

Auto-MD turns codebases and documents into one clean Markdown file or a RAG ready bundle. It processes your files on your machine and removes temporary job data on normal shutdown.

## Run it

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone or download this repository, then run:

```bash
uv run --locked automd.py
```

Auto-MD installs its locked Python environment, starts on `127.0.0.1`, chooses an available port, and opens your browser. Press `Ctrl-C` in the terminal to stop it and clear all job data.

Useful local-development options:

```bash
uv run --locked automd.py --no-browser
uv run --locked automd.py --port 8765
uv run --locked automd.py --log-level info
```

Docker, Node.js, Tesseract, Git, API keys, and cloud services are not required to run the app. Node.js is used only when changing the TypeScript frontend.

## Inputs

- Files and browser selected folders
- Public GitHub repositories, optionally at a specific ref
- Individual public HTTP(S) web pages
- ZIP and TAR archives, including safely bounded nested archives
- Code, text, Markdown, configuration, JSON/YAML/XML, CSV, and notebooks
- HTML, DOCX, PDF, and common image formats
- Scanned PDFs and images through local English capable OCR

Smart filtering respects `.gitignore` and `.automdignore` and removes common dependency, cache, build, and generated paths. Advanced settings allow force includes and additional git style excludes.
Selected files count towards the upload limit before filtering. For a large local project, select the relevant subfolders or upload a ZIP of the files you want to process.

## Outputs

Clean Markdown produces one `.md` file with provenance, stable anchors, a table of contents, and faithfully fenced source content.

RAG bundle produces a ZIP containing:

- the complete Markdown document;
- `chunks.jsonl` with stable IDs, source metadata, heading paths, hashes, and token estimates;
- `manifest.json` with settings, checksums, skips, warnings, and counts.

Chunking follows headings, paragraphs, pages, notebook cells, and code boundaries. Counts are deterministic estimates rather than model-specific token counts.

## Privacy and safety

- The server binds only to loopback and does not support public/LAN hosting.
- After installation, Auto-MD uses the network to fetch web and GitHub sources you add. It validates the destination of every redirect and connects directly, bypassing ambient proxy settings. URL queries and fragments are omitted from generated provenance.
- Upload and archive paths are validated before writes. Links, duplicate paths and filesystem name collisions are rejected. Archive expansion shares a single budget across the job.
- Conversion runs in a separate process with hard cancellation, deadlines and a Linux address-space limit. The worker runs as your user and has the same filesystem permissions as the app.
- Downloads use session-scoped artifact IDs. Files are served as attachments and the Markdown preview is plain text.
- OCR uses the models bundled with the installed RapidOCR dependency. There are no analytics, CDNs or AI APIs at runtime.

Defaults include a 512 MiB input budget, 100 MiB per uploaded file, 20,000 archive entries, 1 GiB of expanded data, 500 pages per PDF and 50 megapixels per image. A conversion can run for up to 15 minutes, with a three minute limit between progress updates. Uploaded inputs are cleared as soon as the job ends. The app retains up to four jobs per session, including jobs in progress. If the app is force quit, temporary `automd-*` directories can remain in the system temp directory.

## Development

Backend:

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest --cov=automd
uv audit --locked
```

Frontend:

```bash
cd frontend
npm ci
npm run check
npm run build
npm audit
```

## Supported platforms

Auto-MD targets Python 3.11.5 through 3.14 on Windows, macOS and Linux systems supported by its OCR and PDF wheels. Frontend development uses Node.js 24. Browser support targets current Chrome, Edge, Firefox and Safari releases.

## License

[MIT](LICENSE)

