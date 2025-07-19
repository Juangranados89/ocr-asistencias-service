"""
import sqlite3
import os

DATABASE_PATH = os.environ.get("DATABASE_PATH", "registros.db")

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with open('schema.sql', 'w') as f:
        f.write('''
            CREATE TABLE IF NOT EXISTS registros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raiz TEXT NOT NULL,
                sub TEXT NOT NULL,
                nombre TEXT NOT NULL,
                estado TEXT NOT NULL,
                resultado TEXT,
                ruta TEXT NOT NULL,
                size REAL NOT NULL
            );
        ''')
    with open('schema.sql', 'r') as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    os.remove('schema.sql')

def add_record(record_data):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO registros (raiz, sub, nombre, estado, resultado, ruta, size) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (record_data['raiz'], record_data['sub'], record_data['nombre'], record_data['estado'],
         record_data['resultado'], record_data['ruta'], record_data['size'])
    )
    conn.commit()
    conn.close()

def get_all_records():
    conn = get_db_connection()
    records = conn.execute('SELECT * FROM registros ORDER BY id DESC').fetchall()
    conn.close()
    return records

def clear_all_records():
    conn = get_db_connection()
    conn.execute('DELETE FROM registros')
    conn.commit()
    conn.close()
"""
