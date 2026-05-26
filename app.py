import re
import os, io, subprocess, platform, datetime, sqlite3, threading
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from flask_socketio import SocketIO
import pandas as pd
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import secrets
# -------------------------------------------------
# Configuração do Flask
# -------------------------------------------------
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # necessário para sessões
socketio = SocketIO(app, cors_allowed_origins="*")

# Usuário e senha de teste
USER = "admin"
PASS = "123456"

# -------------------------------------------------
# Banco de dados
# -------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
DB_CANDIDATES = [os.path.join(HERE, "base_z_ready.db")]
for _p in DB_CANDIDATES:
    if os.path.exists(_p):
        DB_PATH = _p
        break
else:
    DB_PATH = DB_CANDIDATES[0]
    print(f"[AVISO] Banco não encontrado em {DB_PATH}. Crie-o antes de rodar.")

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def s(x):
    return "" if x is None else str(x).strip()

def ping_ok(ip: str) -> bool:
    try:
        param = "-n" if platform.system().lower() == "windows" else "-c"
        r = subprocess.run(["ping", param, "1", ip], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.returncode == 0
    except Exception:
        return False

def obter_aviso_zebra(ip: str) -> str:
    try:
        r = requests.get(f"http://{ip}", timeout=3)
        r.raise_for_status()
        texto = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True).upper()
        if "RIBBON" in texto:
            return "WARNING RIBBON IN"
        if "FITA" in texto:
            return "AVISO FITA INSTAL."
        if "PAUSA" in texto:
            return "EM PAUSA"
        if "OPERANDO" in texto or "READY" in texto or "PRONTA" in texto:
            return "OPERANDO"
        return "OPERANDO"
    except Exception:
        return "OPERANDO"
    
    import re

def obter_contador_zebra(ip: str) -> str:
    try:
        url = f"http://{ip}/config.html"
        r = requests.get(url, timeout=3)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        texto = soup.get_text(" ", strip=True).upper()

        # procura padrão: 172,821 IN NONRESET CNTR
        match = re.search(
    r'([\d,]+)\s+(?:IN|PG)?\s*(?:NONRESET\s+CNTR|CONT(?:AD)?\s+N[ÃA]O?\s+REINIC)',
    texto,
    re.IGNORECASE
)

        if match:
            contador = match.group(1).replace(",", "")
            return contador

        return "N/D"

    except Exception:
        return "N/D"

def aparar_historico_ultimos_5_dias():
    limite = datetime.datetime.now() - datetime.timedelta(days=5)
    for nome, lst in historico_status.items():
        historico_status[nome] = [item for item in lst if datetime.datetime.fromisoformat(item.get("ts", datetime.datetime.now().isoformat())) >= limite]

# -------------------------------------------------
# Carregar impressoras do DB
# -------------------------------------------------
def carregar_impressoras():
    if not os.path.exists(DB_PATH):
        print(f"[ERRO] DB não encontrado em {DB_PATH}")
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query("SELECT Bloco, Setor, Selb, IP FROM impressoras", conn)
    finally:
        conn.close()
    printers = []
    for r in df.to_dict(orient="records"):
        bloco, setor, selb, ip = s(r.get("Bloco")), s(r.get("Setor")), s(r.get("Selb")), s(r.get("IP"))
        if not ip:
            continue
        nome = f"ZEBRA - {bloco} - {setor} ({selb if selb else '?'})"
        printers.append({"nome": nome, "ip": ip, "bloco": bloco, "setor": setor, "selb": selb})
    return printers

# -------------------------------------------------
# Inicializa dados de impressoras
# -------------------------------------------------
impressoras_list = carregar_impressoras()
ips_para_monitorar = {p["nome"]: {"ip": p["ip"], "bloco": p["bloco"], "setor": p["setor"], "selb": p["selb"]} for p in impressoras_list}
historico_status = {nome: [] for nome in ips_para_monitorar}

# -------------------------------------------------
# Status das impressoras
# -------------------------------------------------
def get_status_snapshot():
    aparar_historico_ultimos_5_dias()
    status = {}
    def check_printer(nome, info):
        ip = info["ip"]
        try:
            online = ping_ok(ip)
            contador = obter_contador_zebra (ip)
            aviso = obter_aviso_zebra(ip) if online else "SEM CONEXÃO"
            atual = {"status": "Online" if online else "Offline", "aviso": aviso, "contador": str(contador)}
            ultimo = historico_status.get(nome, [])[-1] if historico_status.get(nome) else None
            if not ultimo or ultimo["status"] != atual["status"] or ultimo["aviso"] != atual["aviso"]:
                agora = datetime.datetime.now()
                historico_status.setdefault(nome, []).append({
                    "status": atual["status"],
                    "aviso": atual["aviso"],
                    "hora": agora.strftime("%d/%m %H:%M:%S"),
                    "ts": agora.isoformat(timespec="seconds")
                })
            status[nome] = atual
        except Exception:
            status[nome] = {"status": "Offline", "aviso": "SEM CONEXÃO"}
    with ThreadPoolExecutor(max_workers=20) as executor:
        for nome, info in ips_para_monitorar.items():
            executor.submit(check_printer, nome, info)
    return status

# -------------------------------------------------
# Monitoramento em background
# -------------------------------------------------
def monitorar():
    while True:
        try:
            status = get_status_snapshot()
            socketio.emit("atualizar_status", status)
        except Exception as e:
            print("Erro no monitoramento:", e)
        socketio.sleep(5)

# -------------------------------------------------
# Rotas de login/logout
# -------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()  # sempre limpa sessão ao abrir login
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == USER and password == PASS:
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            return render_template("Login.html", error="Usuário ou senha incorretos")
    return render_template("Login.html")

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

# -------------------------------------------------
# Rota principal protegida
# -------------------------------------------------
@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    cards = [{"nome": nome, **meta} for nome, meta in ips_para_monitorar.items()]
    return render_template("index.html", impressoras=cards)

# -------------------------------------------------
# Outras rotas existentes (status, histórico, download, CRUD, etc.)
# -------------------------------------------------
@app.route("/status")
def status_http():
    return jsonify(get_status_snapshot())

@app.route("/historico/<path:printer_name>")
def historico(printer_name):
    printer_name = s(printer_name)
    return jsonify(historico_status.get(printer_name, []))

@app.route("/download/relatorio", methods=["GET", "POST"])
def download_relatorio():
    snap = get_status_snapshot()
    nomes = None
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        nomes = [s(x) for x in data.get("nomes", []) if s(x)] if isinstance(data.get("nomes"), list) else None
    rows = [{"Nome": n, "Status": i["status"], "Aviso": i["aviso"], "Contador": i.get("contador", "N/D")} for n, i in snap.items() if nomes is None or n in nomes]
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Relatório", engine="openpyxl")
    buf.seek(0)
    return send_file(buf, download_name="relatorio_impressoras.xlsx", as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/download/historico_txt/<path:printer_name>")
def download_historico_txt(printer_name):
    name = s(printer_name)
    data = historico_status.get(name, [])
    txt = [f"Histórico - {name}"] + ([f"- {i.get('hora','')} - {i.get('status','')} ({i.get('aviso','')})" for i in data] if data else ["Sem registros."])
    return send_file(io.BytesIO("\n".join(txt).encode("utf-8")), download_name=f"{name.replace('/', '_')}_historico.txt", as_attachment=True)

@app.route("/alerts")
def alerts():
    snap = get_status_snapshot()
    whitelist = {"AVISO FITA INSTAL.", "WARNING RIBBON IN", "EM PAUSA", "PAUSA"}
    return jsonify([nome for nome, st in snap.items() if s(st.get("aviso")).upper() in whitelist])

@app.route("/add_printer", methods=["POST"])
def add_printer_route():
    data = request.get_json() or {}
    nome, ip, bloco, setor, selb = s(data.get("name")), s(data.get("ip")), s(data.get("bloco")), s(data.get("setor")), s(data.get("selb"))
    if not nome or not ip:
        return jsonify({"error": "Parâmetros inválidos"}), 400
    ips_para_monitorar[nome] = {"ip": ip, "bloco": bloco, "setor": setor, "selb": selb}
    historico_status[nome] = []
    socketio.emit("atualizar_status", get_status_snapshot())
    return jsonify({"ok": True}), 201

@app.route("/delete_printer", methods=["POST"])
def delete_printer():
    data = request.get_json() or {}
    name = s(data.get("name"))
    if name in ips_para_monitorar:
        ips_para_monitorar.pop(name, None)
        historico_status.pop(name, None)
        socketio.emit("atualizar_status", get_status_snapshot())
        return jsonify({"ok": True, "deleted": name}), 200
    return jsonify({"ok": False, "deleted": None}), 404

# -------------------------------------------------
# Inicialização
# -------------------------------------------------
if __name__ == "__main__":
    socketio.start_background_task(monitorar)
    socketio.run(app, host="0.0.0.0", port=5000)
