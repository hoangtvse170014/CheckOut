import sqlite3
conn = sqlite3.connect('data/people_counter.db')
cursor = conn.cursor()
cursor.execute("DELETE FROM alert_logs WHERE substr(alert_time, 1, 10) = '2026-01-08'")
conn.commit()
print(f'Deleted {cursor.rowcount} alerts')
conn.close()
