import os
import io
import zipfile
import tempfile
import re
import glob
from flask import Flask, request, send_file, jsonify
from pdf2image import convert_from_path
from google.cloud import vision
import pandas as pd

# ────────────────────────────────────────────────────────────
#  Credenciales de Google Vision
#  1) Si la ruta GOOGLE_APPLICATION_CREDENTIALS ya viene fija
#     (p. ej. Secret File en /etc/secrets/creds.json) → OK.
#  2) De lo contrario, busca GOOGLE_CREDENTIALS_JSON con el
#     contenido del JSON y lo vuelca a /tmp/creds.json.
# ────────────────────────────────────────────────────────────
if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    cred_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not cred_json:
        raise RuntimeError(
            "Falta credencial: define GOOGLE_APPLICATION_CREDENTIALS "
            "o GOOGLE_CREDENTIALS_JSON en Render."
        )
    creds_path = "/tmp/creds.json"
    with open(creds_path, "w") as f:
        f.write(cred_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path

# Cliente Vision listo
client = vision.ImageAnnotatorClient()

app = Flask(__name__)

# ────────────────────────────────────────────────────────────
#  Utilidad OCR → devuelve lista de dicts {nombre, cedula, archivo, pagina}
# ────────────────────────────────────────────────────────────
def procesar_pdf(pdf_path: str) -> list[dict]:
    resultados = []
    paginas = convert_from_path(pdf_path, dpi=300)
    for num, img in enumerate(paginas, start=1):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image = vision.Image(content=buf.getvalue())
        resp = client.document_text_detection(image=image)

        if resp.error.message:
            # Saltamos página con error silenciosamente
            continue

        texto = resp.full_text_annotation.text
        lineas = [ln.strip() for ln in texto.split("\n") if ln.strip()]
        i = 0
        while i < len(lineas) - 1:
            # Línea potencial de nombre seguida de línea con "CC"
            if (
                re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", lineas[i])
                and re.search(r"\b(cc|CC|C\.C)\b", lineas[i + 1], re.IGNORECASE)
            ):
                m = re.search(r"\d{6,}", lineas[i + 1])
                if m:
                    resultados.append(
                        {
                            "nombre": lineas[i],
                            "cedula": m.group(),
                            "archivo": os.path.basename(pdf_path),
                            "pagina": num,
                        }
                    )
                i += 2
            else:
                i += 1
    return resultados


# ────────────────────────────────────────────────────────────
#  Endpoint /upload   (POST multipart/form-data con un ZIP de PDFs)
#  Respuesta: Excel con las asistencias extraídas.
# ────────────────────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify(error="Debes subir un archivo ZIP con PDFs"), 400

    zip_file = request.files["file"]
    tmpdir = tempfile.mkdtemp()
    zip_path = os.path.join(tmpdir, "input.zip")
    zip_file.save(zip_path)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(tmpdir)

    resultados = []
    for pdf in glob.glob(os.path.join(tmpdir, "*.pdf")):
        resultados.extend(procesar_pdf(pdf))

    if not resultados:
        return jsonify(error="No se detectó ningún nombre/CC"), 422

    df = pd.DataFrame(resultados)
    out_buf = io.BytesIO()
    with pd.ExcelWriter(out_buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="asistencias")
    out_buf.seek(0)

    return send_file(
        out_buf,
        as_attachment=True,
        download_name="asistencias_extraidas.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ────────────────────────────────────────────────────────────
#  Arranque local (Render usará gunicorn)
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
