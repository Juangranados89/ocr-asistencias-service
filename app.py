"""Flask app with an organized HTML/CSS interface to upload a ZIP, process PDFs with Google Vision OCR, and keep a running table of results.

Columns: Carpeta Raiz | SubCarpeta | Nombre Archivo | Estado | Resultado | Ruta del Archivo | Tamaño Archivo (kB)
Users can clear the table with a button. Data lives in memory for the life of the pod.
"""
import os
import io
import zipfile
import tempfile
import re
from pathlib import Path
from flask import Flask, request, redirect, url_for, render_template_string, flash

# pdf2image es un wrapper que necesita de la utilidad `poppler`.
# En un entorno de despliegue como Render, necesitarás asegurarte de que
# poppler esté instalado. Esto se puede hacer usualmente con el gestor de
# paquetes del sistema (ej. `apt-get install poppler-utils` en Debian/Ubuntu).
from pdf2image import convert_from_path
from google.cloud import vision

# ─── 1. CONFIGURACIÓN Y CREDENCIALES ────────────────────────────────────────

# Configuración de credenciales de Google Cloud.
# Este bloque permite que la aplicación funcione en entornos de despliegue
# donde las credenciales se pasan como una variable de entorno JSON.
if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    cred_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if cred_json_str:
        # Crea un archivo temporal para las credenciales
        creds_path = Path(tempfile.gettempdir()) / "gcp_creds.json"
        with open(creds_path, "w") as f:
            f.write(cred_json_str)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)
    else:
        # Si no se encuentran las credenciales, la aplicación no puede funcionar.
        print("ERROR: Credenciales de Google Vision no encontradas.")
        print("Por favor, defina GOOGLE_APPLICATION_CREDENTIALS o GOOGLE_CREDENTIALS_JSON.")
        # En un entorno real, podrías querer que la app falle aquí.
        # raise RuntimeError("Se requieren credenciales de Google Vision")

# Inicializa el cliente de la API de Google Vision
try:
    vision_client = vision.ImageAnnotatorClient()
except Exception as e:
    print(f"Error al inicializar el cliente de Google Vision: {e}")
    vision_client = None


# Configuración de la aplicación Flask
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "una-llave-secreta-muy-segura")

# Almacenamiento en memoria para los resultados.
# Como se especifica, los datos solo persisten mientras el proceso del servidor esté activo.
REGISTROS: list[dict] = []

# ─── 2. PLANTILLA HTML CON TAILWIND CSS ─────────────────────────────────────

HTML_TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OCR Asistencias Cotema</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    /* Estilo para el indicador de carga */
    .loader {
      border: 5px solid #f3f3f3; /* Light grey */
      border-top: 5px solid #0f4c81; /* Blue */
      border-radius: 50%;
      width: 50px;
      height: 50px;
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }
    /* Ocultar el loader por defecto */
    #loader-container {
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(255, 255, 255, 0.8);
        z-index: 9999;
        justify-content: center;
        align-items: center;
    }
  </style>
</head>
<body class="bg-gray-100 text-gray-800 font-sans">

  <!-- Indicador de Carga -->
  <div id="loader-container">
    <div class="loader"></div>
    <p class="ml-4 text-lg font-semibold text-gray-700">Procesando, por favor espera...</p>
  </div>

  <header class="bg-slate-800 text-white shadow-md">
    <div class="container mx-auto px-6 py-4">
      <h1 class="text-2xl font-bold tracking-tight">Analizador de Asistencias OCR – Cotema</h1>
    </div>
  </header>

  <main class="container mx-auto px-6 py-8">
    
    <!-- Sección de Carga de Archivos -->
    <div class="bg-white p-6 rounded-lg shadow-lg mb-8">
      <h2 class="text-xl font-bold mb-4 border-b pb-2 text-slate-700">Cargar Archivo ZIP</h2>
      <form id="upload-form" method="post" enctype="multipart/form-data" action="{{ url_for('upload_file') }}">
        <div class="flex items-center space-x-4">
          <input type="file" name="file" accept=".zip" required class="block w-full text-sm text-slate-500
            file:mr-4 file:py-2 file:px-4
            file:rounded-full file:border-0
            file:text-sm file:font-semibold
            file:bg-slate-100 file:text-slate-700
            hover:file:bg-slate-200">
          <button class="btn-primary" type="submit">Procesar Archivo</button>
        </div>
      </form>
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          {% for category, message in messages %}
            <div class="mt-4 px-4 py-2 rounded-md font-medium {{ 'bg-red-100 text-red-700' if category == 'error' else 'bg-blue-100 text-blue-700' }}">
              {{ message }}
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}
    </div>

    <!-- Sección de Resultados -->
    <div class="bg-white p-6 rounded-lg shadow-lg">
      <div class="flex justify-between items-center mb-4 border-b pb-2">
        <h2 class="text-xl font-bold text-slate-700">Registros Procesados ({{ registros|length }})</h2>
        <form method="post" action="{{ url_for('clear_records') }}">
          <button class="btn-danger" type="submit" onclick="return confirm('¿Estás seguro de que deseas borrar todos los registros?');">
            Borrar Registros
          </button>
        </form>
      </div>
      <div class="overflow-x-auto" style="max-height: 65vh;">
        <table class="min-w-full bg-white text-sm">
          <thead class="bg-slate-200 sticky top-0">
            <tr>
              <th class="py-2 px-3 text-left font-semibold text-slate-600">Carpeta Raíz</th>
              <th class="py-2 px-3 text-left font-semibold text-slate-600">Subcarpeta</th>
              <th class="py-2 px-3 text-left font-semibold text-slate-600">Nombre Archivo</th>
              <th class="py-2 px-3 text-left font-semibold text-slate-600">Estado</th>
              <th class="py-2 px-3 text-left font-semibold text-slate-600">Resultado (Nombre — CC)</th>
              <th class="py-2 px-3 text-left font-semibold text-slate-600">Ruta Relativa</th>
              <th class="py-2 px-3 text-right font-semibold text-slate-600">Tamaño (kB)</th>
            </tr>
          </thead>
          <tbody class="text-gray-600">
            {% for r in registros %}
            <tr class="border-b border-gray-200 hover:bg-gray-50">
              <td class="py-2 px-3">{{ r.raiz }}</td>
              <td class="py-2 px-3">{{ r.sub }}</td>
              <td class="py-2 px-3 font-medium text-gray-700">{{ r.nombre }}</td>
              <td class="py-2 px-3">
                <span class="px-2 py-1 text-xs font-semibold rounded-full {{ 'bg-green-100 text-green-800' if r.estado == 'OK' else 'bg-red-100 text-red-800' }}">
                  {{ r.estado }}
                </span>
              </td>
              <td class="py-2 px-3">{{ r.resultado }}</td>
              <td class="py-2 px-3 text-xs text-gray-500">{{ r.ruta }}</td>
              <td class="py-2 px-3 text-right tabular-nums">{{ '%.1f'|format(r.size/1024) }}</td>
            </tr>
            {% else %}
            <tr>
              <td colspan="7" class="text-center py-8 text-gray-500">No hay registros para mostrar. Sube un archivo ZIP para comenzar.</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <style>
    .btn-primary {
        background-color: #0f4c81; color: white; padding: 0.6rem 1.5rem; border-radius: 9999px; font-weight: 600; transition: background-color 0.3s;
    }
    .btn-primary:hover { background-color: #0a3a66; }
    .btn-danger {
        background-color: #d9534f; color: white; padding: 0.5rem 1.2rem; border-radius: 9999px; font-weight: 600; transition: background-color 0.3s;
    }
    .btn-danger:hover { background-color: #c9302c; }
  </style>

  <script>
    // Muestra el indicador de carga al enviar el formulario
    document.getElementById('upload-form').addEventListener('submit', function() {
      document.getElementById('loader-container').style.display = 'flex';
    });
  </script>

</body>
</html>
"""

# ─── 3. LÓGICA DE OCR Y EXTRACCIÓN DE DATOS ───────────────────────────────────

# Expresión regular mejorada para capturar nombres y cédulas en la misma línea.
# Busca:
# - Un patrón similar a un nombre (2 a 4 palabras capitalizadas).
# - Seguido por cualquier caracter (no codicioso).
# - Y luego un número de 6 a 10 dígitos (la cédula).
# Esto es más flexible que buscar "CC:" explícitamente.
NAME_CC_PATTERN = re.compile(
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s?){1,3}).*?(\d{6,10})"
)

def extract_name_and_cc_from_text(text: str) -> str:
    """
    Busca en el texto extraído por OCR para encontrar el primer patrón
    que coincida con un nombre y una cédula.
    """
    for line in text.split('\n'):
        match = NAME_CC_PATTERN.search(line)
        if match:
            # Se encontró una coincidencia. Limpiamos el nombre y la cédula.
            name = match.group(1).strip()
            cc = match.group(2).strip()
            return f"{name} — {cc}"
    return "No reconocido"

def process_pdf_with_vision(pdf_path: Path) -> str:
    """
    Convierte cada página de un PDF a imagen, la envía a Google Vision
    para OCR y luego intenta extraer la información relevante.
    """
    if not vision_client:
        return "Error: Cliente de Vision no inicializado."
    
    full_text = ""
    try:
        # Convierte el PDF a una lista de imágenes (una por página)
        # Se requiere `poppler` instalado en el sistema.
        images = convert_from_path(pdf_path, dpi=300)
        
        for image in images:
            # Convierte la imagen a bytes en memoria
            with io.BytesIO() as output:
                image.save(output, format="PNG")
                content = output.getvalue()

            # Prepara y envía la solicitud a la API de Vision
            vision_image = vision.Image(content=content)
            response = vision_client.document_text_detection(image=vision_image)
            
            if response.error.message:
                print(f"Error de Vision API para {pdf_path.name}: {response.error.message}")
                continue # Intenta con la siguiente página si hay un error

            full_text += response.full_text_annotation.text + "\n"

        if not full_text:
            return "No se extrajo texto"

        # Intenta extraer nombre y CC del texto completo de todas las páginas
        return extract_name_and_cc_from_text(full_text)

    except Exception as e:
        # Captura errores de conversión de PDF o de la API
        print(f"Error procesando {pdf_path.name}: {e}")
        return f"Error de procesamiento: {e}"

# ─── 4. RUTAS DE LA APLICACIÓN FLASK ──────────────────────────────────────────

@app.route("/")
def index():
    """Renderiza la página principal con la tabla de registros."""
    # Ordena los registros para mostrar los más recientes primero
    sorted_records = sorted(REGISTROS, key=lambda r: r['ruta'], reverse=True)
    return render_template_string(HTML_TEMPLATE, registros=sorted_records)

@app.route("/upload", methods=["POST"])
def upload_file():
    """Maneja la carga del archivo ZIP y dispara el procesamiento."""
    if 'file' not in request.files:
        flash("No se encontró ninguna parte del archivo en la solicitud.", "error")
        return redirect(url_for('index'))

    file = request.files['file']
    if file.filename == '' or not file.filename.lower().endswith('.zip'):
        flash("Por favor, selecciona un archivo ZIP válido.", "error")
        return redirect(url_for('index'))

    # Usa un directorio temporal para extraer los archivos de forma segura
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = Path(temp_dir) / file.filename
        file.save(zip_path)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
        except zipfile.BadZipFile:
            flash("El archivo subido no es un ZIP válido.", "error")
            return redirect(url_for('index'))

        # Recorre los archivos extraídos y procesa los PDFs
        pdf_files_found = list(Path(temp_dir).rglob("*.pdf"))
        if not pdf_files_found:
            flash("No se encontraron archivos PDF dentro del ZIP.", "error")
            return redirect(url_for('index'))

        for pdf_path in pdf_files_found:
            relative_path = pdf_path.relative_to(temp_dir)
            path_parts = relative_path.parts
            
            # Determina la estructura de carpetas para la tabla
            root_folder = path_parts[0] if len(path_parts) > 1 else "(raíz)"
            sub_folder = path_parts[-2] if len(path_parts) > 1 else "(raíz)"
            
            # Procesa el PDF
            result_text = process_pdf_with_vision(pdf_path)
            status = "Error" if "Error" in result_text else "OK"
            
            # Añade el resultado al registro en memoria (usando un dict simple)
            REGISTROS.append({
                "raiz": root_folder,
                "sub": sub_folder,
                "nombre": pdf_path.name,
                "estado": status,
                "resultado": result_text,
                "ruta": str(relative_path),
                "size": pdf_path.stat().st_size
            })

    flash(f"Se procesaron {len(pdf_files_found)} archivo(s) PDF del ZIP.", "success")
    return redirect(url_for('index'))

@app.route("/clear", methods=["POST"])
def clear_records():
    """Limpia la lista de registros en memoria."""
    REGISTROS.clear()
    flash("Todos los registros han sido borrados.", "success")
    return redirect(url_for('index'))

# ─── 5. PUNTO DE ENTRADA ──────────────────────────────────────────────────────

if __name__ == "__main__":
    # La aplicación se ejecuta en el puerto definido por el entorno,
    # ideal para plataformas como Render.
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        debug=True # Desactiva el modo debug en producción
    )

