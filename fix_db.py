import sqlite3

# conecta no banco
conn = sqlite3.connect("base_z_ready.db")
cur = conn.cursor()

print("🔍 Limpando duplicatas no banco...")

# Apaga duplicatas de SELB (mantém apenas o menor rowid)
cur.execute("""
DELETE FROM impressoras
WHERE rowid NOT IN (
    SELECT MIN(rowid)
    FROM impressoras
    GROUP BY Selb
)
""")

# Apaga duplicatas de IP (mantém apenas o menor rowid)
cur.execute("""
DELETE FROM impressoras
WHERE rowid NOT IN (
    SELECT MIN(rowid)
    FROM impressoras
    GROUP BY IP
)
""")

conn.commit()

print("✅ Duplicatas removidas.")

# cria índice único para SELB
try:
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_selb ON impressoras(Selb)")
    print("✅ Índice único criado para Selb")
except sqlite3.IntegrityError:
    print("⚠️ Ainda há duplicatas em Selb, verifique os dados.")

# cria índice único para IP
try:
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ip ON impressoras(IP)")
    print("✅ Índice único criado para IP")
except sqlite3.IntegrityError:
    print("⚠️ Ainda há duplicatas em IP, verifique os dados.")

conn.commit()
conn.close()

print("🎯 Banco corrigido com sucesso!")
