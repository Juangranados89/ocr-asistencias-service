# Dockerfile (versión final, usando la imagen oficial de Python)

# Usa la imagen oficial de Python. 'slim-bullseye' es una versión ligera y segura.
FROM python:3.10-slim-bullseye

# Configura el entorno de Python
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Instala las dependencias del sistema, incluyendo poppler-utils
# --no-install-recommends evita instalar paquetes innecesarios.
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Crea un directorio de trabajo y un usuario no privilegiado para mayor seguridad
WORKDIR /app
RUN addgroup --system app && adduser --system --group app

# Copia e instala las dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cambia al usuario no privilegiado
USER app

# Copia el resto del código de la aplicación
COPY . .

# El comando de inicio (CMD) se proporcionará desde el render.yaml
