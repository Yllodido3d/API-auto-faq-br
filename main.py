from fastapi import FastAPI, HTTPException, Query, UploadFile, Request
from pydantic import BaseModel
import sqlite3
import os
import csv
from rapidfuzz import fuzz, process
from unidecode import unidecode
import time
from datetime import datetime

app = FastAPI(title="Respostas Prontas BR")

# ======================
# 1. Autenticação simples
# ======================
API_KEY = os.getenv("API_KEY", "123abc")


def validar_api_key(chave: str):
    if chave != API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida.")


# ======================
# 2. Estrutura do banco
# ======================
def inicializar_banco():
    conn = sqlite3.connect("respostas.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS respostas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pergunta TEXT,
            resposta TEXT,
            categoria TEXT
        )
    """)
    # Tabela pra controle de uso diário
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uso_api (
            ip TEXT,
            data TEXT,
            contador INTEGER,
            PRIMARY KEY (ip, data)
        )
    """)
    conn.commit()
    conn.close()


inicializar_banco()
start_time = time.time()


# ======================
# 3. Modelos Pydantic
# ======================
class Pergunta(BaseModel):
    pergunta: str


class NovaResposta(BaseModel):
    pergunta: str
    resposta: str
    categoria: str | None = None


# ======================
# 4. Controle de uso diário
# ======================
LIMITE_DIARIO = 20


def verificar_limite(ip: str):
    hoje = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("respostas.db")
    cur = conn.cursor()

    cur.execute("SELECT contador FROM uso_api WHERE ip=? AND data=?", (ip, hoje))
    row = cur.fetchone()

    if row:
        contador = row[0]
        if contador >= LIMITE_DIARIO:
            conn.close()
            raise HTTPException(status_code=429, detail="Limite diário de uso atingido (20 requisições por dia).")
        cur.execute("UPDATE uso_api SET contador=contador+1 WHERE ip=? AND data=?", (ip, hoje))
    else:
        cur.execute("INSERT INTO uso_api (ip, data, contador) VALUES (?, ?, ?)", (ip, hoje, 1))

    conn.commit()
    conn.close()


# ======================
# 5. Endpoint principal
# ======================
@app.post("/responder")
async def responder(pergunta: Pergunta, request: Request, api_key: str = Query(...)):
    validar_api_key(api_key)
    ip_cliente = request.client.host
    verificar_limite(ip_cliente)

    conn = sqlite3.connect("respostas.db")
    cur = conn.cursor()
    cur.execute("SELECT pergunta, resposta FROM respostas")
    todas = cur.fetchall()
    conn.close()

    if not todas:
        return {"erro": "banco vazio"}

    perguntas_db = [unidecode(p.lower()) for p, _ in todas]
    entrada = unidecode(pergunta.pergunta.lower())

    match, score, idx = process.extractOne(entrada, perguntas_db, scorer=fuzz.ratio)
    if score >= 70:
        resposta = todas[idx][1]
        return {"resposta": resposta, "confiança": f"{score:.1f}%"}

    return {"erro": "não sei"}


# ======================
# 6. Endpoint de listagem
# ======================
@app.get("/categorias")
async def listar_categorias(api_key: str = Query(...)):
    validar_api_key(api_key)
    conn = sqlite3.connect("respostas.db")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT categoria FROM respostas WHERE categoria IS NOT NULL")
    categorias = [row[0] for row in cur.fetchall()]
    conn.close()
    return {"categorias": categorias}


@app.get("/perguntas/{cat}")
async def listar_perguntas(cat: str, api_key: str = Query(...)):
    validar_api_key(api_key)
    conn = sqlite3.connect("respostas.db")
    cur = conn.cursor()
    cur.execute("SELECT pergunta FROM respostas WHERE categoria=?", (cat,))
    perguntas = [row[0] for row in cur.fetchall()]
    conn.close()
    return {"categoria": cat, "perguntas": perguntas}


# ======================
# 7. Adicionar manualmente
# ======================
@app.post("/add")
async def adicionar_resposta(item: NovaResposta, api_key: str = Query(...)):
    validar_api_key(api_key)
    conn = sqlite3.connect("respostas.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO respostas (pergunta, resposta, categoria) VALUES (?, ?, ?)",
        (item.pergunta, item.resposta, item.categoria)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "adicionado": item}


# ======================
# 8. Importar CSV
# ======================
@app.post("/importar_csv")
async def importar_csv(arquivo: UploadFile, api_key: str = Query(...)):
    validar_api_key(api_key)
    conteudo = await arquivo.read()
    linhas = conteudo.decode("utf-8").splitlines()
    leitor = csv.reader(linhas)

    conn = sqlite3.connect("respostas.db")
    cur = conn.cursor()
    count = 0
    for linha in leitor:
        if len(linha) >= 2:
            pergunta, resposta, *categoria = linha
            cat = categoria[0] if categoria else None
            cur.execute(
                "INSERT INTO respostas (pergunta, resposta, categoria) VALUES (?, ?, ?)",
                (pergunta.strip(), resposta.strip(), cat)
            )
            count += 1
    conn.commit()
    conn.close()
    return {"status": "ok", "adicionados": count}


# ======================
# 9. Status da API
# ======================
@app.get("/status")
async def status():
    uptime = round(time.time() - start_time, 1)
    conn = sqlite3.connect("respostas.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM respostas")
    total = cur.fetchone()[0]
    conn.close()

    return {
        "status": "online",
        "versao": "1.2",
        "total_respostas": total,
        "uptime_segundos": uptime
    }
