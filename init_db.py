# init_db.py
import sqlite3
import os
from pathlib import Path

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/registros.db")

# Asegurarse de que el directorio de datos existe
Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

print(f"Inicializando la base de datos en: {DATABASE_PATH}")

try:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raiz TEXT NOT NULL,
            sub TEXT NOT NULL,
            nombre TEXT NOT NULL,
            estado TEXT NOT NULL,
            resultado TEXT,
            ruta TEXT NOT NULL,
            size REAL NOT NULL,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    conn.close()
    print("Base de datos inicializada correctamente.")
except Exception as e:
    print(f"Error al inicializar la base de datos: {e}")
    # Salir con un código de error para que el build de Render falle si esto no funciona
    exit(1)
