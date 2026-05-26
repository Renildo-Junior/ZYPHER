import pandas as pd
import sqlite3

# Carrega a planilha
df = pd.read_excel("BASE_Z.xlsx")  # ou pd.read_csv("base_z.csv")

# Cria o banco SQLite
conn = sqlite3.connect("base_z_ready.db")

# Exporta a planilha para a tabela "impressoras"
df.to_sql("impressoras", conn, if_exists="replace", index=False)

conn.commit()
conn.close()

print("Banco criado com sucesso: base_z_ready.db")
