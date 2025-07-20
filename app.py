# app.py (v4 - Corregido para Render)
import os
import sqlite3
from pathlib import Path
from flask import Flask, request, redirect, url_for, render_template_string, flash, jsonify
import redis
from rq import Queue
from werkzeug.utils import secure_filename

# --- Configuración ---
app = Flask(__name__)  # <--- CORRECCIÓN: Renombrada la variable a 'app'
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret-key")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/registros.db")
UPLOAD_FOLDER = Path(os.environ.get("UPLOAD_FOLDER", "/data/uploads"))
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
redis_conn = redis.from_url(redis_url)
q = Queue(connection=redis_conn)

# --- Funciones de Base de Datos ---
def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- Plantilla HTML (sin cambios) ---
HTML_TEMPLATE = """
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>OCR Asistencias Cotema</title><script src="https://cdn.tailwindcss.com"></script><style>.loader-container{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background-color:rgba(255,255,255,0.85);z-index:9999;justify-content:center;align-items:center;flex-direction:column}.loader{border:6px solid #f3f3f3;border-top:6px solid #0f4c81;border-radius:50%;width:60px;height:60px;animation:spin 1.2s linear infinite}@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}.btn-primary{background-color:#0f4c81;color:#fff;padding:.6rem 1.5rem;border-radius:9999px;font-weight:600;transition:background-color .3s;white-space:nowrap}.btn-primary:hover{background-color:#0a3a66}.btn-danger{background-color:#d9534f;color:#fff;padding:.5rem 1.2rem;border-radius:9999px;font-weight:600;transition:background-color .3s;white-space:nowrap}.btn-danger:hover{background-color:#c9302c}</style></head><body class="bg-gray-100 text-gray-800 font-sans"><div id="loader" class="loader-container"><div class="loader"></div><p class="mt-4 text-lg font-semibold text-slate-700">Procesando...</p><p class="text-sm text-slate-500">Los resultados aparecerán automáticamente.</p></div><header class="bg-slate-800 text-white shadow-md"><div class="container mx-auto px-6 py-4"><h1 class="text-2xl font-bold tracking-tight">Analizador de Asistencias OCR – Cotema</h1></div></header><main class="container mx-auto px-6 py-8"><div class="bg-white p-6 rounded-lg shadow-lg mb-8"><h2 class="text-xl font-bold mb-4 border-b pb-2 text-slate-700">Cargar Archivo ZIP</h2><form id="upload-form" method="post" enctype="multipart/form-data" action="{{ url_for('upload') }}"><div class="flex items-center space-x-4"><input type="file" name="file" accept=".zip" required class="block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 cursor-pointer"><button class="btn-primary" type="submit">Procesar Archivo</button></div></form>{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="mt-4 px-4 py-2 rounded-md font-medium {{ 'bg-red-100 text-red-700' if category == 'error' else 'bg-blue-100 text-blue-700' }}">{{ message }}</div>{% endfor %}{% endif %}{% endwith %}</div><div class="bg-white p-6 rounded-lg shadow-lg"><div class="flex justify-between items-center mb-4 border-b pb-2"><h2 class="text-xl font-bold text-slate-700">Registros Procesados (<span id="record-count">0</span>)</h2><form method="post" action="{{ url_for('clear') }}"><button class="btn-danger" type="submit" onclick="return confirm('¿Borrar todos los registros?');">Borrar Registros</button></form></div><div class="overflow-x-auto" style="max-height: 65vh;"><table class="min-w-full bg-white text-sm"><thead class="bg-slate-200 sticky top-0 z-10"><tr><th class="py-2 px-3 text-left font-semibold text-slate-600">Carpeta Raíz</th><th class="py-2 px-3 text-left font-semibold text-slate-600">Subcarpeta</th><th class="py-2 px-3 text-left font-semibold text-slate-600">Nombre Archivo</th><th class="py-2 px-3 text-left font-semibold text-slate-600">Estado</th><th class="py-2 px-3 text-left font-semibold text-slate-600">Resultado (Nombre — CC)</th><th class="py-2 px-3 text-left font-semibold text-slate-600">Ruta</th><th class="py-2 px-3 text-right font-semibold text-slate-600">Tamaño (kB)</th></tr></thead><tbody id="results-table-body" class="text-gray-600"><tr><td colspan="7" class="text-center py-8 text-gray-500">Cargando registros...</td></tr></tbody></table></div></div></main><script>document.getElementById('upload-form').addEventListener('submit',function(){document.getElementById('loader').style.display='flex'});function updateTable(records){const tbody=document.getElementById('results-table-body');const countSpan=document.getElementById('record-count');tbody.innerHTML='';countSpan.textContent=records.length;if(records.length===0){tbody.innerHTML='<tr><td colspan="7" class="text-center py-8 text-gray-500">No hay registros para mostrar.</td></tr>';return}records.forEach(r=>{const statusColor=r.estado==='OK'?'bg-green-100 text-green-800':(r.estado==='Revisar'?'bg-yellow-100 text-yellow-800':'bg-red-100 text-red-800');const sizeKb=(r.size/1024).toFixed(1);const row=`<tr class="border-b border-gray-200 hover:bg-gray-50"><td class="py-2 px-3">${r.raiz}</td><td class="py-2 px-3">${r.sub}</td><td class="py-2 px-3 font-medium text-gray-700">${r.nombre}</td><td class="py-2 px-3"><span class="px-2 py-1 text-xs font-semibold rounded-full ${statusColor}">${r.estado}</span></td><td class="py-2 px-3">${r.resultado}</td><td class="py-2 px-3 text-xs text-gray-500">${r.ruta}</td><td class="py-2 px-3 text-right tabular-nums">${sizeKb}</td></tr>`;tbody.innerHTML+=row})}function fetchResults(){fetch("{{ url_for('get_results') }}").then(response=>response.json()).then(data=>{updateTable(data)}).catch(error=>console.error('Error fetching results:',error))}document.addEventListener('DOMContentLoaded',function(){fetchResults();setInterval(fetchResults,5000)});</script></body></html>
"""

# --- Rutas de la Aplicación ---
@app.route("/")  # <--- CORRECCIÓN
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/results") # <--- CORRECCIÓN
def get_results():
    try:
        conn = get_db_connection()
        records = conn.execute('SELECT * FROM registros ORDER BY id DESC').fetchall()
        conn.close()
        return jsonify([dict(row) for row in records])
    except Exception as e:
        print(f"Error al obtener resultados: {e}")
        return jsonify([])

@app.route("/upload", methods=["POST"]) # <--- CORRECCIÓN
def upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".zip"):
        flash("Debes subir un archivo .zip", "error")
        return redirect(url_for('index'))
    filename = secure_filename(f.filename)
    zip_path = UPLOAD_FOLDER / filename
    f.save(zip_path)
    q.enqueue('worker.process_zip_file', str(zip_path))
    flash(f"Archivo '{filename}' recibido. El procesamiento ha comenzado en segundo plano.", "success")
    return redirect(url_for('index'))

@app.route("/clear", methods=["POST"]) # <--- CORRECCIÓN
def clear():
    conn = get_db_connection()
    conn.execute('DELETE FROM registros')
    conn.commit()
    conn.close()
    flash("Registros borrados exitosamente.")
    return redirect(url_for('index'))

# --- Punto de Entrada ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
