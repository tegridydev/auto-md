from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import logging
import tempfile
import uuid
import shutil
import threading
import queue
from pathlib import Path
from file_processor import process_input

app = Flask(__name__, 
    template_folder='templates',
    static_folder='static'
)
socketio = SocketIO(app)

class WebSocketHandler(logging.Handler):
    def emit(self, record):
        socketio.emit('log', self.format(record))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()
socket_handler = WebSocketHandler()
logger.addHandler(socket_handler)

class ProcessingJob:
    def __init__(self):
        self.temp_dir = Path(tempfile.gettempdir()) / f"automd_temp_{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.progress = 0
        self.status = "Ready"
        self.output_path = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    try:
        input_files = request.files.getlist('input_files')
        github_urls = request.form.getlist('github_urls[]')
        single_file = request.form.get('single_file') == 'true'
        repo_depth = None if request.form.get('repo_depth') == "Full" else int(request.form.get('repo_depth'))
        include_metadata = request.form.get('include_metadata') == 'true'
        include_toc = request.form.get('include_toc') == 'true'
        output_filename = request.form.get('output_filename', 'output.md')

        job = ProcessingJob()
        
        saved_paths = []
        for file in input_files:
            if file.filename:
                file_path = job.temp_dir / file.filename
                file.save(file_path)
                saved_paths.append(str(file_path))
        
        saved_paths.extend(github_urls)

        output_path = job.temp_dir / output_filename
        output_dir = process_input(
            saved_paths,
            str(output_path),
            str(job.temp_dir),
            single_file,
            repo_depth,
            include_metadata,
            include_toc
        )

        return jsonify({
            'status': 'success',
            'message': 'Processing complete',
            'output_path': output_dir
        })

    except Exception as e:
        logger.error(f"Processing error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/download')
def download():
    try:
        output_path = request.args.get('path')
        if not output_path:
            return "No output path specified", 400

        path = Path(output_path)
        if path.is_file():
            return send_file(path, as_attachment=True)
        elif path.is_dir():
            zip_path = path.parent / f"{path.name}.zip"
            shutil.make_archive(str(zip_path.with_suffix('')), 'zip', path)
            return send_file(zip_path, as_attachment=True)
        else:
            return "Output path not found", 404
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    socketio.run(app, debug=True)