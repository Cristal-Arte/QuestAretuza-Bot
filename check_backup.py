import sqlite3
import os

# Check the latest backup
backups = [f for f in os.listdir('backups') if f.startswith('questuza_backup_')]
backups.sort(reverse=True)
latest_backup = backups[0] if backups else None

if latest_backup:
    print(f"Latest backup: {latest_backup}")

    # Connect to backup and check tables
    backup_path = os.path.join('backups', latest_backup)
    conn = sqlite3.connect(backup_path)
    c = conn.cursor()
    c.execute('SELECT name FROM sqlite_master WHERE type="table"')
    backup_tables = [row[0] for row in c.fetchall()]
    print("Tables in latest backup:")
    for table in backup_tables:
        print(f"- {table}")

    # Check if custom_quests table exists in backup
    if 'custom_quests' in backup_tables:
        c.execute('SELECT COUNT(*) FROM custom_quests')
        count = c.fetchone()[0]
        print(f"Custom quests in backup: {count}")
    else:
        print("No custom_quests table in backup")

    conn.close()
else:
    print("No backups found")
