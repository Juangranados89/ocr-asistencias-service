# Dockerfile (v3 - Con inicialización de DB en el build)

FROM python:3.10-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Instala dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN addgroup --system app && adduser --system --group app

# Copia e instala las dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código de la aplicación
COPY . .

# IMPORTANTE: Establece el path de la base de datos para el script de inicialización
# Asegúrate de que el directorio /data exista antes de ejecutar el script
RUN mkdir -p /data && chown -R app:app /data
ENV DATABASE_PATH=/data/registros.db

# Ejecuta el script de inicialización de la base de datos
RUN python init_db.py

# Cambia al usuario no privilegiado para la ejecución
USER app

# El CMD se define en render.yaml
