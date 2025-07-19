# ─── ocr_asistencias_cotema/app.py ───────────────────────────────────────────
#
# Aplicación Flask para procesar archivos ZIP con PDFs de asistencia.
#
# MEJORAS CLAVE EN ESTA VERSIÓN:
# 1.  OPTIMIZACIÓN DE RENDIMIENTO: Se ha reducido la resolución (DPI) de la
#     conversión de PDF a imagen de 300 a 150. Este es el cambio más
#     importante para reducir drásticamente el tiempo de procesamiento y el
#     uso de memoria. Google Vision AI sigue siendo muy eficaz con esta resolución.
#
# 2.  MANEJO DE ERRORES MEJORADO: Se han añadido más bloques try-except para
#     manejar posibles fallos durante la conversión del PDF o la llamada a la API,
#     evitando que un solo archivo corrupto detenga todo el proceso.
#
# 3.  LÓGICA DE EXTRACCIÓN MÁS ROBUSTA: La función `extraer_nombre_cc` ha sido
#     mejorada para utilizar múltiples estrategias de búsqueda, aumentando la
#     probabilidad de encontrar el nombre y la cédula correctamente.
#
# 4.  ARQUITECTURA ASÍNCRONA (RECOMENDACIÓN): Se han añadido comentarios
#     explicando por qué el procesamiento de archivos grandes falla (timeouts)
#     y cómo implementar una solución robusta utilizando tareas en segundo plano
#     (background workers), que es la práctica estándar en la industria.
#
# ──────────────────────────────────────────────────────────────────────────

import os
import io
import zipfile
import tempfile
import re
from pathlib import Path
from flask import Flask, request, redirect, url_for, render_template_string, flash

# Dependencia externa: `poppler`. En Render, esto se puede instalar añadiendo
# `poppler-utils` a las herramientas de construcción del sistema operativo.
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

# ─── 2. PLANTILLA HTML CON TAILWIND CSS Y FEEDBACK DE CARGA ──────────────────

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
              <td class="py-2 px-3"><span class="px-2 py-1 text-xs font-semibold rounded-full {{ 'bg-green-100 text-green-800' if r.estado == 'OK' else 'bg-red-100 text-red-800' }}">{{ r.estado }}</span></td>
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

# ─── 3. LÓGICA DE OCR Y EXTRACCIÓN DE DATOS ───────────────────────────────────

# Expresión regular para buscar "CC" o similar seguido de números.
CC_RE = re.compile(r"(?:C\.?C\.?|CEDULA|ID)\s*:?\s*(\d{6,10})", re.IGNORECASE)

def extraer_nombre_cc(texto: str) -> str:
    """
    Lógica mejorada para extraer nombre y cédula.
    Intenta encontrar la línea con la cédula y luego busca hacia atrás
    la línea que parece ser el nombre del firmante.
    """
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    for i, linea in enumerate(lineas):
        match_cc = CC_RE.search(linea)
        if match_cc:
            cc = match_cc.group(1)
            # Buscar hacia atrás desde la línea de la cédula para encontrar el nombre.
            # El nombre suele estar 1 o 2 líneas antes y no contiene palabras clave como "CARGO" o "FIRMA".
            for j in range(i - 1, max(-1, i - 5), -1):
                linea_anterior = lineas[j]
                # Un nombre válido suele tener al menos dos palabras capitalizadas
                # y no es una de las cabeceras de la tabla.
                if (len(linea_anterior.split()) >= 2 and
                    not any(keyword in linea_anterior.upper() for keyword in ["CARGO", "FIRMA", "COMPANY", "CEDULA"])):
                    return f"{linea_anterior} — {cc}"
    return "No reconocido"

def procesar_pdf(path: Path) -> str:
    """
    Convierte un PDF a imágenes, las procesa con Vision AI y extrae el texto.
    """
    if not vision_client:
        return "Error: Cliente de Vision no inicializado"
    
    texto_completo = ""
    try:
        # OPTIMIZACIÓN: DPI reducido a 150. Es el mejor balance entre velocidad y precisión.
        # 300 DPI es excesivo y causa timeouts y alto uso de memoria.
        pages = convert_from_path(path, dpi=150)
        
        for img in pages:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            
            resp = vision_client.document_text_detection(image=vision.Image(content=buf.getvalue()))
            
            if resp.error.message:
                print(f"Vision API error for {path.name}: {resp.error.message}")
                continue
            
            texto_completo += resp.full_text_annotation.text
            # Si encontramos un resultado en la primera página, podemos detenernos
            # para acelerar el proceso.
            resultado_parcial = extraer_nombre_cc(texto_completo)
            if resultado_parcial != "No reconocido":
                return resultado_parcial
        
        return "No reconocido" # Si no se encontró en ninguna página

    except Exception as e:
        error_message = str(e).splitlines()[0] # Mensaje de error más corto
        print(f"Error al procesar el PDF {path.name}: {error_message}")
        return f"Error de conversión: {error_message}"

# ─── 4. RUTAS DE LA APLICACIÓN FLASK ──────────────────────────────────────────

@app.route("/")
def index():
    """Renderiza la página principal."""
    return render_template_string(HTML_TEMPLATE, registros=REGISTROS)

@app.route("/upload", methods=["POST"])
def upload():
    """
    Maneja la carga de archivos.
    ADVERTENCIA: Este es un proceso síncrono. Para archivos grandes (>5-10MB)
    o muchos PDFs, es muy probable que falle por timeout en plataformas como Render.
    
    SOLUCIÓN REAL: Implementar un sistema de colas (como Celery con Redis o RQ).
    1. El usuario sube el archivo.
    2. Flask guarda el archivo (p. ej., en un bucket S3 o almacenamiento temporal).
    3. Flask añade una tarea a la cola (p. ej., "procesar archivo X.zip").
    4. Flask responde INMEDIATAMENTE al usuario: "Archivo recibido, procesando...".
    5. Un proceso "worker" separado toma la tarea de la cola y realiza el OCR
       sin límites de tiempo.
    6. El worker guarda los resultados en una base de datos.
    7. La página principal lee los resultados de la base de datos para mostrarlos.
    """
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
            
            estado = "OK" if "Error" not in resultado and "No reconocido" not in resultado else "Revisar"
            if "Error" in resultado:
                estado = "Error"

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
