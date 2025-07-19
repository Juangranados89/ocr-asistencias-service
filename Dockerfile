FROM python:3.10-slim

# Instala Poppler para pdf2image
RUN apt-get update && \
    apt-get install -y poppler-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código de la app
COPY app.py .

# Buen hábito: exponer el puerto interno (Render usará la var $PORT)
EXPOSE 5000

# Arranque con Gunicorn
#  - $PORT: puerto asignado por Render
#  - --timeout 300  (5 min)
#  - --workers 2 --threads 2  (paralelismo básico)
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "--timeout", "300", "--workers", "2", "--threads", "2", "app:app"]
