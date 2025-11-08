import sqlite3

conn = sqlite3.connect('questuza.db')
c = conn.cursor()
c.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = [row[0] for row in c.fetchall()]
print("Tables in questuza.db:")
for table in tables:
    print(f"- {table}")
conn.close()
