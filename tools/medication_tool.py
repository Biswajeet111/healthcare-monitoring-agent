from utils.db import get_connection

def add_medication(name, dosage, time):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO medications (name, dosage, time) VALUES (?, ?, ?)",
        (name, dosage, time)
    )

    conn.commit()
    conn.close()

def get_medications():
    conn = get_connection()
    cursor = conn.cursor()

    data = cursor.execute(
        "SELECT name, dosage, time FROM medications"
    ).fetchall()

    conn.close()
    return data
