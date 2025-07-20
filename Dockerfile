# Dockerfile (v4 - Corregido para dependencias de sistema en Render)

FROM python:3.10-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Instala dependencias del sistema operativo
# poppler-utils -> para pdf2image
# unzip, p7zip-full, tar -> herramientas que 'patool' necesita para instalarse
# build-essential -> herramientas de compilación por si alguna librería las requiere
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    unzip \
    p7zip-full \
    tar \
    build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Configura el directorio de trabajo y el usuario de la aplicación
WORKDIR /app
RUN addgroup --system app && adduser --system --group app

# Copia e instala las dependencias de Python
# Se copia primero para aprovechar el caché de Docker si no cambia
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código de la aplicación
COPY . .

# Crea los directorios de datos y asigna permisos
# Es importante que el usuario 'app' sea el propietario para poder escribir archivos
RUN mkdir -p /data/uploads && chown -R app:app /data
ENV DATABASE_PATH=/data/registros.db
ENV UPLOAD_FOLDER=/data/uploads

# Ejecuta el script de inicialización de la base de datos como root (antes de cambiar de usuario)
RUN python init_db.py

# Cambia al usuario no privilegiado para la ejecución
USER app

# El comando de inicio (CMD) se especifica en el archivo render.yaml
# (Ej: gunicorn app:app o python worker.py)
