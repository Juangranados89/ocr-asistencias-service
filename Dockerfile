# ───────────────── Imagen base ─────────────────
FROM python:3.10-slim

# ── Dependencia del sistema: poppler-utils para pdf2image
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# ── Directorio de trabajo
WORKDIR /app

# ── Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código de la aplicación
COPY app.py .

# ── Exponer puerto interno (Render lo vincula externamente)
EXPOSE 5000

# ── Arranque con Gunicorn
#  • Escucha en 0.0.0.0:5000
#  • Timeout extendido a 300 s (5 min)
#  • 2 workers, 2 threads (ajusta según tu carga)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--timeout", "300", \
     "--workers", "2", "--threads", "2", \
     "app:app"]
