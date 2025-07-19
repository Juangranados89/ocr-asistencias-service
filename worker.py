"""
import os
import io
import zipfile
import tempfile
import re
from pathlib import Path
import redis
from rq import Worker, Queue, Connection
from pdf2image import convert_from_path
from google.cloud import vision

# Importar las funciones de la base de datos
from database import add_record

# Configuración de credenciales de Google Cloud
if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    cred_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if cred_json_str:
        creds_path = Path(tempfile.gettempdir()) / "gcp_creds.json"
        with open(creds_path, "w") as f:
            f.write(cred_json_str)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)

# Inicialización del cliente de Vision
vision_client = vision.ImageAnnotatorClient()

# Configuración de la conexión a Redis
listen = ['default']
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
conn = redis.from_url(redis_url)

# Lógica de extracción (idéntica a la de app.py)
def extraer_nombre_cc(texto: str) -> list[str]:
    resultados = []
    CC_NUM_RE = re.compile(r'(\d{6,10})')
    IGNORE_KEYWORDS = ["CARGO", "FIRMA", "COMPANY", "CEDULA", "APELLIDOS", "SIGNATURE", "TITLE", "JOB", "LISTADO"]
    lineas = [line.strip() for line in texto.split("\n") if line.strip()]
    for linea in lineas:
        matches = list(CC_NUM_RE.finditer(linea))
        if matches:
            match = matches[-1]
            cc = match.group(1)
            potential_name = linea[:match.start()].strip()
            potential_name = re.sub(r"^\d+\s*[.-]?\s*", "", potential_name)
            potential_name = re.sub(r"[^\w\sÁÉÍÓÚÑáéíóúñ'-]", "", potential_name).strip()
            if (len(potential_name.split()) >= 2 and not any(keyword in potential_name.upper() for keyword in IGNORE_KEYWORDS)):
                resultados.append(f"{potential_name} — {cc}")
    return resultados

def procesar_pdf(path: Path) -> str:
    todos_los_resultados = []
    try:
        pages = convert_from_path(path, dpi=150)
        for img in pages:
            with io.BytesIO() as buf:
                img.save(buf, format="PNG")
                content = buf.getvalue()
            resp = vision_client.document_text_detection(image=vision.Image(content=content))
            if resp.error.message:
                print(f"Error de Vision API para {path.name}: {resp.error.message}")
                continue
            resultados_pagina = extraer_nombre_cc(resp.full_text_annotation.text)
            if resultados_pagina:
                todos_los_resultados.extend(resultados_pagina)
        if not todos_los_resultados: return "No reconocido"
        return "; ".join(sorted(list(set(todos_los_resultados))))
    except Exception as e:
        return f"Error de conversión: {str(e).splitlines()[0]}"

# La función principal que ejecutará el worker
def process_zip_file(zip_path_str):
    zip_path = Path(zip_path_str)
    temp_dir = zip_path.parent
    
    print(f"Iniciando procesamiento para: {zip_path.name}")
    
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(temp_dir)
    except Exception as e:
        print(f"Error al descomprimir {zip_path.name}: {e}")
        return

    pdf_files = sorted(list(Path(temp_dir).rglob("*.pdf")))
    for fp in pdf_files:
        rel = fp.relative_to(temp_dir)
        partes = rel.parts
        raiz = partes[0] if len(partes) > 1 else "(raíz)"
        sub = partes[-2] if len(partes) > 1 else "(raíz)"
        
        resultado = procesar_pdf(fp)
        
        estado = "OK"
        if "Error" in resultado: estado = "Error"
        elif "No reconocido" in resultado: estado = "Revisar"

        record = {
            "raiz": raiz, "sub": sub, "nombre": fp.name,
            "estado": estado, "resultado": resultado,
            "ruta": str(rel), "size": fp.stat().st_size
        }
        add_record(record)
        print(f"Registro añadido para: {fp.name}")
    
    # Limpiar el archivo ZIP después de procesar
    os.remove(zip_path)
    print(f"Procesamiento completado para: {zip_path.name}")


if __name__ == '__main__':
    with Connection(conn):
        worker = Worker(map(Queue, listen))
        worker.work()
"""
