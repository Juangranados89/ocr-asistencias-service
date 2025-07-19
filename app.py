"""Flask app with an organized HTML/CSS interface to upload a ZIP, process PDFs with Google Vision OCR, and keep a running table of results.

Columns: Carpeta Raiz | SubCarpeta | Nombre Archivo | Estado | Resultado | Ruta del Archivo | Tamaño Archivo (kB)
Users can clear the table with a button. Data lives in memory for the life of the pod.
"""
import os
import io
import zipfile
import tempfile
import re
import glob
from pathlib import Path
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash
from pdf2image import convert_from_path
from google.cloud import vision
import pandas as pd

# ─── CREDENCIALES ───────────────────────────────────────────────────────────
if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    cred_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if cred_json:
        path = "/tmp/creds.json"
        with open(path, "w") as f:
            f.write(cred_json)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    else:
        raise RuntimeError("Se requieren credenciales de Google Vision")

client = vision.ImageAnnotatorClient()

app = Flask(__name__)
app.secret_key = "ocr-asistencias-cotema"

REGISTROS: list[dict] = []  # Persistencia en memoria

# ─── HTML + CSS (material minimalista) ──────────────────────────────────────
HTML = """
<!doctype html>
<html lang=es>
<head>
  <meta charset=utf-8>
  <title>OCR Asistencias Cotema</title>
  <style>
    body{font-family:Arial, Helvetica, sans-serif;margin:0;padding:0;background:#f7f9fc;color:#222}
    header{background:#0f4c81;color:#fff;padding:1rem 2rem}
    h1{margin:0;font-size:1.4rem;letter-spacing:.5px}
    main{padding:2rem;max-width:1100px;margin:auto}
    .card{background:#fff;border-radius:8px;box-shadow:0 2px 6px rgba(0,0,0,.1);padding:1.5rem;margin-bottom:2rem}
    .btn{display:inline-block;padding:.5rem 1.2rem;border:none;border-radius:4px;font-weight:600;cursor:pointer;text-decoration:none}
    .btn-primary{background:#0f4c81;color:#fff}
    .btn-danger{background:#d9534f;color:#fff}
    table{width:100%;border-collapse:collapse;margin-top:1rem;font-size:.9rem}
    th,td{padding:.55rem .7rem;border:1px solid #ddd;text-align:left}
    th{background:#eceff4;font-weight:600}
    tbody tr:nth-child(even){background:#fafafa}
    .flash{color:#c00;font-weight:600;margin:.5rem 0}
  </style>
</head>
<body>
<header><h1>OCR Asistencias – Cotema</h1></header>
<main>
  <div class=card>
    <h2>Cargar ZIP</h2>
    <form method=post enctype=multipart/form-data action="{{ url_for('upload') }}">
      <input type=file name=file accept=.zip required>
      <button class="btn btn-primary" type=submit>Procesar</button>
    </form>
    {% for m in get_flashed_messages() %}<div class=flash>{{m}}</div>{% endfor %}
  </div>

  <div class=card>
    <h2>Registros procesados ({{ registros|length }})</h2>
    <form method=post action="{{ url_for('clear') }}" style="margin-bottom:1rem;">
      <button class="btn btn-danger" type=submit onclick="return confirm('¿Borrar todos los registros?');">Borrar registros</button>
    </form>
    <div style="overflow-x:auto;max-height:60vh;overflow-y:auto;">
      <table>
        <thead>
          <tr>
            <th>Carpeta Raíz</th><th>Subcarpeta</th><th>Nombre Archivo</th>
            <th>Estado</th><th>Resultado (Nombre — CC)</th>
            <th>Ruta</th><th>Tamaño (kB)</th>
          </tr>
        </thead>
        <tbody>
        {% for r in registros %}
          <tr>
            <td>{{r.raiz}}</td><td>{{r.sub}}</td><td>{{r.nombre}}</td>
            <td>{{r.estado}}</td><td>{{r.resultado}}</td>
            <td>{{r.ruta}}</td><td style="text-align:right;">{{ '%.1f'|format(r.size/1024) }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</main>
</body>
</html>
"""

# ─── OCR Helpers ───────────────────────────────────────────────────────────
NAME_CC_RE = re.compile(r"(?:^|\s)(cc|C\.?C\.?|C-C)\s*:?\s*(\d{6,})", re.IGNORECASE)

def extraer_nombre_cc(texto:str)->str:
    lineas=[l.strip() for l in texto.split("\n") if l.strip()]
    for i in range(len(lineas)-1):
        if NAME_CC_RE.search(lineas[i+1]):
            cc=NAME_CC_RE.search(lineas[i+1]).group(2)
            return f"{lineas[i]} — {cc}"
    return "No reconocido"

def procesar_pdf(path:Path)->str:
    try:
        pages=convert_from_path(path,dpi=300)
    except Exception as e:
        return f"Error conversión: {e}"
    for img in pages:
        buf=io.BytesIO();img.save(buf,format="PNG")
        resp=client.document_text_detection(image=vision.Image(content=buf.getvalue()))
        if resp.error.message: continue
        res=extraer_nombre_cc(resp.full_text_annotation.text)
        if res!="No reconocido": return res
    return "No reconocido"

# ─── Rutas ────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return render_template_string(HTML, registros=REGISTROS)

@app.post("/upload")
def upload():
    f=request.files.get("file")
    if not f or not f.filename.lower().endswith(".zip"):
        flash("Debes subir un ZIP");return redirect(url_for('index'))
    tmp=tempfile.mkdtemp(); zip_path=Path(tmp,"up.zip"); f.save(zip_path)
    with zipfile.ZipFile(zip_path) as z:z.extractall(tmp)
    contar=0
    for root,_,files in os.walk(tmp):
        for fn in files:
            if not fn.lower().endswith(".pdf"): continue
            contar+=1
            fp=Path(root,fn); rel=fp.relative_to(tmp)
            partes=rel.parts
            raiz=partes[0] if len(partes)>1 else "(raíz)"
            sub=partes[-2] if len(partes)>1 else "(raíz)"
            resultado=procesar_pdf(fp)
            REGISTROS.append(type('R',(),dict(
                raiz=raiz,sub=sub,nombre=fn,
                estado="OK" if "Error" not in resultado else "Error",
                resultado=resultado,ruta=str(rel),size=fp.stat().st_size))())
    flash(f"Procesados {contar} PDF(s)")
    return redirect(url_for('index'))

@app.post("/clear")
def clear():
    REGISTROS.clear(); flash("Registros borrados")
    return redirect(url_for('index'))

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=True)
