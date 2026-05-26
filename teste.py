import sqlite3, pandas as pd
conn = sqlite3.connect("Dados/base_z_ready.db")
df = pd.read_sql_query("SELECT Bloco, Setor, Selb, IP FROM impressoras", conn)
print(df)