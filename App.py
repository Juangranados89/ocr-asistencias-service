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

app = Flask(__name__)

# 1) Cargar credenciales de Vision desde variable de entorno
cred_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
if not cred_json:
    raise RuntimeError("Falta la variable GOOGLE_CREDENTIALS_JSON")
with open('/tmp/creds.json', 'w') as f:
    f.write(cred_json)
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/tmp/creds.json'

client = vision.ImageAnnotatorClient()

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify(error="No se subió ningún archivo"), 400
    f = request.files['file']
    tmpdir = tempfile.mkdtemp()
    zip_path = os.path.join(tmpdir, 'input.zip')
    f.save(zip_path)
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(tmpdir)

    resultados = []
    for pdf_path in glob.glob(tmpdir + '/*.pdf'):
        paginas = convert_from_path(pdf_path, dpi=300)
        for num, img in enumerate(paginas, start=1):
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            image = vision.Image(content=buf.getvalue())
            resp = client.document_text_detection(image=image)
            if resp.error.message:
                continue
            texto = resp.full_text_annotation.text
            lineas = [l.strip() for l in texto.split('\n') if l.strip()]
            i = 0
            while i < len(lineas)-1:
                if (re.search(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]', lineas[i]) and
                    re.search(r'(cc|C-C|CC)', lineas[i+1], re.IGNORECASE)):
                    m = re.search(r'(\d{6,})', lineas[i+1])
                    if m:
                        resultados.append({
                            'nombre': lineas[i],
                            'cedula': m.group(1),
                            'archivo': os.path.basename(pdf_path),
                            'pagina': num
                        })
                    i += 2
                else:
                    i += 1

    df = pd.DataFrame(resultados)
    out_buf = io.BytesIO()
    with pd.ExcelWriter(out_buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='asistencias')
    out_buf.seek(0)
    return send_file(
        out_buf,
        as_attachment=True,
        download_name='asistencias_extraidas.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
