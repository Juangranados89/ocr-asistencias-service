# Dockerfile (único para ambos servicios)
# Define el entorno base compartido para la aplicación web y el worker.

# Usa la imagen base de Python proporcionada por Render
FROM render/python:3.10.6

# Cambia al usuario root para instalar paquetes del sistema
USER root
# Instala poppler-utils (esencial para pdf2image)
RUN apt-get update && apt-get install -y poppler-utils
# Vuelve al usuario no privilegiado de Render
USER render

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo de dependencias e instálalas
# Esto se aprovecha del cache de Docker para acelerar builds futuros
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copia el resto del código de la aplicación al directorio de trabajo
COPY . .
