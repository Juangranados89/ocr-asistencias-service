# ─── ocr_asistencias_cotema/app.py ───────────────────────────────────────────
#
# Aplicación Flask para procesar archivos ZIP con PDFs de asistencia.
#
# MEJORAS CLAVE EN ESTA VERSIÓN (v4):
# 1.  LÓGICA DE EXTRACCIÓN DE DATOS REFORZADA: Se ha reescrito por completo la
#     función `extraer_nombre_cc` basándose en los nuevos archivos de ejemplo.
#     La nueva estrategia es más robusta:
#       a. Primero, busca un número de cédula válido (6-10 dígitos) en cada línea.
#       b. Si lo encuentra, analiza el texto ANTERIOR en la misma línea.
#       c. Limpia y valida ese texto para asegurarse de que parece un nombre
#          (p. ej., tiene al menos dos palabras y no es un encabezado de tabla).
#     Este enfoque es mucho más flexible y preciso que el anterior.
#
# 2.  OPTIMIZACIÓN DE PROCESAMIENTO: Se mantiene la reducción de DPI a 150 para
#     un rendimiento óptimo y se añade una optimización: si se encuentra un
#     resultado válido en la primera página del PDF, el proceso se detiene y
#     devuelve ese resultado, evitando procesar páginas innecesarias.
#
# 3.  MEJORA DE ESTADO EN LA TABLA: El estado ahora es más descriptivo.
#     - "OK": Si se encontró un nombre y cédula.
#     - "Revisar": Si el OCR funcionó pero no se reconoció un patrón válido.
#     - "Error": Si hubo un fallo técnico al procesar el archivo.
#
# 4.  INTERFAZ DE USUARIO PULIDA: Pequeños ajustes en la tabla de resultados
#     para mejorar la legibilidad y la presentación de los datos.
#
# ──────────────────────────────────────────────────────────────────────────

import os
import io
import zipfile
import tempfile
import re
from pathlib import Path
from flask import Flask, request, redirect, url_for, render_template_string, flash

# Dependencia externa: `poppler`. Necesario para pdf2image.
# En Render: ir a Environment > Dockerfile y añadir `RUN apt-get update && apt-get install -y poppler-utils`
from pdf2image import convert_from_path
from google.cloud import vision

# ─── 1. CONFIGURACIÓN Y CREDENCIALES ────────────────────────────────────────

# Configuración segura de credenciales de Google Cloud
if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    cred_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if cred_json_str:
        creds_path = Path(tempfile.gettempdir()) / "gcp_creds.json"
        with open(creds_path, "w") as f:
            f.write(cred_json_str)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)
    else:
        print("ADVERTENCIA: Credenciales de Google Vision no encontradas. La API de OCR fallará.")

# Inicialización del cliente de la API de Google Vision
try:
    vision_client = vision.ImageAnnotatorClient()
except Exception as e:
    print(f"Error al inicializar el cliente de Google Vision: {e}")
    vision_client = None

# Configuración de la aplicación Flask
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "una-llave-secreta-muy-segura")

# Almacenamiento en memoria para los resultados
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
    .loader-container {
      display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
      background-color: rgba(255, 255, 255, 0.85); z-index: 9999;
      justify-content: center; align-items: center; flex-direction: column;
    }
    .loader {
      border: 6px solid #f3f3f3; border-top: 6px solid #0f4c81;
      border-radius: 50%; width: 60px; height: 60px;
      animation: spin 1.2s linear infinite;
    }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
  </style>
</head>
<body class="bg-gray-100 text-gray-800 font-sans">
  <div id="loader" class="loader-container">
    <div class="loader"></div>
    <p class="mt-4 text-lg font-semibold text-slate-700">Procesando, por favor espera...</p>
    <p class="text-sm text-slate-500">Esto puede tardar varios minutos para archivos grandes.</p>
  </div>
  <header class="bg-slate-800 text-white shadow-md">
    <div class="container mx-auto px-6 py-4">
      <h1 class="text-2xl font-bold tracking-tight">Analizador de Asistencias OCR – Cotema</h1>
    </div>
  </header>
  <main class="container mx-auto px-6 py-8">
    <div class="bg-white p-6 rounded-lg shadow-lg mb-8">
      <h2 class="text-xl font-bold mb-4 border-b pb-2 text-slate-700">Cargar Archivo ZIP</h2>
      <form id="upload-form" method="post" enctype="multipart/form-data" action="{{ url_for('upload') }}">
        <div class="flex items-center space-x-4">
          <input type="file" name="file" accept=".zip" required class="block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 cursor-pointer">
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
    <div class="bg-white p-6 rounded-lg shadow-lg">
      <div class="flex justify-between items-center mb-4 border-b pb-2">
        <h2 class="text-xl font-bold text-slate-700">Registros Procesados ({{ registros|length }})</h2>
        <form method="post" action="{{ url_for('clear') }}">
          <button class="btn-danger" type="submit" onclick="return confirm('¿Estás seguro de que deseas borrar todos los registros?');">Borrar Registros</button>
        </form>
      </div>
      <div class="overflow-x-auto" style="max-height: 65vh;">
        <table class="min-w-full bg-white text-sm">
          <thead class="bg-slate-200 sticky top-0 z-10">
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
              <td class="py-2 px-3">{{ r.raiz }}</td><td class="py-2 px-3">{{ r.sub }}</td>
              <td class="py-2 px-3 font-medium text-gray-700">{{ r.nombre }}</td>
              <td class="py-2 px-3">
                <span class="px-2 py-1 text-xs font-semibold rounded-full 
                  {% if r.estado == 'OK' %}bg-green-100 text-green-800
                  {% elif r.estado == 'Revisar' %}bg-yellow-100 text-yellow-800
                  {% else %}bg-red-100 text-red-800{% endif %}">
                  {{ r.estado }}
                </span>
              </td>
              <td class="py-2 px-3">{{ r.resultado }}</td><td class="py-2 px-3 text-xs text-gray-500">{{ r.ruta }}</td>
              <td class="py-2 px-3 text-right tabular-nums">{{ '%.1f'|format(r.size/1024) }}</td>
            </tr>
            {% else %}
            <tr><td colspan="7" class="text-center py-8 text-gray-500">No hay registros para mostrar.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </main>
  <style>
    .btn-primary { background-color: #0f4c81; color: white; padding: 0.6rem 1.5rem; border-radius: 9999px; font-weight: 600; transition: background-color 0.3s; white-space: nowrap; }
    .btn-primary:hover { background-color: #0a3a66; }
    .btn-danger { background-color: #d9534f; color: white; padding: 0.5rem 1.2rem; border-radius: 9999px; font-weight: 600; transition: background-color 0.3s; white-space: nowrap; }
    .btn-danger:hover { background-color: #c9302c; }
  </style>
  <script>
    document.getElementById('upload-form').addEventListener('submit', function() {
      document.getElementById('loader').style.display = 'flex';
    });
  </script>
</body>
</html>
"""

# ─── 3. LÓGICA DE OCR Y EXTRACCIÓN DE DATOS (MEJORADA) ───────────────────────

def extraer_nombre_cc(texto: str) -> str:
    """
    Lógica mejorada para extraer nombre y cédula del texto de OCR.
    Busca primero la cédula y luego infiere el nombre a partir del texto precedente.
    """
    # Regex para encontrar un número de 6 a 10 dígitos (potencial cédula)
    CC_NUM_RE = re.compile(r'(\d{6,10})')
    # Palabras clave a ignorar para no confundir encabezados con nombres
    IGNORE_KEYWORDS = [
        "CARGO", "FIRMA", "COMPANY", "CEDULA", "APELLIDOS", "SIGNATURE",
        "TITLE", "JOB", "LISTADO", "ASISTENCIA", "FECHA", "PROYECTO"
    ]

    lineas = [line.strip() for line in texto.split("\n") if line.strip()]

    for linea in lineas:
        # Busca todas las posibles cédulas en la línea
        matches = list(CC_NUM_RE.finditer(linea))
        if matches:
            # Usualmente, la cédula es el último número largo en la línea
            match = matches[-1]
            cc = match.group(1)
            
            # El texto antes de la cédula es el candidato a nombre
            potential_name = linea[:match.start()].strip()
            
            # Limpieza del candidato:
            # 1. Eliminar números de lista al inicio (ej. "1. Juan Perez")
            potential_name = re.sub(r"^\d+\s*[.-]?\s*", "", potential_name)
            # 2. Eliminar caracteres no alfanuméricos que no sean parte de un nombre
            potential_name = re.sub(r"[^\w\sÁÉÍÓÚÑáéíóúñ'-]", "", potential_name).strip()

            # Validación final del nombre:
            # - Debe tener al menos dos palabras.
            # - No debe contener palabras clave de encabezados.
            if (len(potential_name.split()) >= 2 and
                not any(keyword in potential_name.upper() for keyword in IGNORE_KEYWORDS)):
                return f"{potential_name} — {cc}"
                
    return "No reconocido"

def procesar_pdf(path: Path) -> str:
    """
    Convierte un PDF a imágenes, las procesa con Vision AI y extrae la información.
    """
    if not vision_client:
        return "Error: Cliente de Vision no inicializado"
    
    try:
        # OPTIMIZACIÓN: DPI 150 es el mejor balance entre velocidad y precisión.
        pages = convert_from_path(path, dpi=150)
        
        texto_completo = ""
        for img in pages:
            with io.BytesIO() as buf:
                img.save(buf, format="PNG")
                content = buf.getvalue()

            resp = vision_client.document_text_detection(image=vision.Image(content=content))
            
            if resp.error.message:
                print(f"Error de Vision API para {path.name}: {resp.error.message}")
                continue
            
            texto_pagina = resp.full_text_annotation.text
            texto_completo += texto_pagina + "\n"
            
            # OPTIMIZACIÓN: Si encontramos un resultado en la primera página, lo devolvemos
            # para no procesar el resto del documento innecesariamente.
            resultado_parcial = extraer_nombre_cc(texto_pagina)
            if resultado_parcial != "No reconocido":
                return resultado_parcial
        
        # Si no se encontró en la primera página, intentar con el texto completo
        return extraer_nombre_cc(texto_completo) if texto_completo else "No se extrajo texto"

    except Exception as e:
        error_message = str(e).splitlines()[0]
        print(f"Error al procesar el PDF {path.name}: {error_message}")
        return f"Error de conversión: {error_message}"

# ─── 4. RUTAS DE LA APLICACIÓN FLASK ──────────────────────────────────────────

@app.route("/")
def index():
    """Renderiza la página principal con la tabla de registros."""
    return render_template_string(HTML_TEMPLATE, registros=REGISTROS)

@app.route("/upload", methods=["POST"])
def upload():
    """Maneja la carga del archivo ZIP y el procesamiento síncrono."""
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".zip"):
        flash("Debes subir un archivo .zip", "error")
        return redirect(url_for('index'))

    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "upload.zip"
        f.save(zip_path)
        
        try:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(tmp_dir)
        except zipfile.BadZipFile:
            flash("El archivo subido no es un ZIP válido.", "error")
            return redirect(url_for('index'))

        pdf_files = sorted(list(Path(tmp_dir).rglob("*.pdf")))
        if not pdf_files:
            flash("El ZIP no contenía archivos PDF.", "error")
            return redirect(url_for('index'))

        for fp in pdf_files:
            rel = fp.relative_to(tmp_dir)
            partes = rel.parts
            raiz = partes[0] if len(partes) > 1 else "(raíz)"
            sub = partes[-2] if len(partes) > 1 else "(raíz)"
            
            resultado = procesar_pdf(fp)
            
            estado = "OK"
            if "Error" in resultado:
                estado = "Error"
            elif "No reconocido" in resultado:
                estado = "Revisar"

            REGISTROS.append({
                "raiz": raiz, "sub": sub, "nombre": fp.name,
                "estado": estado, "resultado": resultado,
                "ruta": str(rel), "size": fp.stat().st_size
            })

    flash(f"Procesados {len(pdf_files)} PDF(s) del archivo ZIP.", "success")
    return redirect(url_for('index'))

@app.route("/clear", methods=["POST"])
def clear():
    """Limpia los registros en memoria."""
    REGISTROS.clear()
    flash("Registros borrados exitosamente.")
    return redirect(url_for('index'))

# ─── 5. PUNTO DE ENTRADA ──────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
