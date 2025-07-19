FROM python:3.10-slim

# Instala Poppler
RUN apt-get update && \
    apt-get install -y poppler-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código de la app
COPY app.py .

# Puerto que usa Flask
EXPOSE 5000

# Arranque con Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
