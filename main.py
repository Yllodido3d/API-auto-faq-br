from fastapi import FastAPI, HTTPException, Query, UploadFile, Request
from pydantic import BaseModel
import sqlite3
import os
import csv
from rapidfuzz import fuzz, process
from unidecode import unidecode
import time
from datetime import datetime
from fastapi.responses import JSONResponse

app = FastAPI(title="Auto Answer API – Optimized")

API_KEY = os.getenv("API_KEY", "123abc")
DAILY_LIMIT = 20

start_time = time.time()


# ======================================================
# 1. AUTH
# ======================================================
def validate_api_key(key: str):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")


# ======================================================
# 2. DATABASE
# ======================================================
def init_database():
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            answer TEXT,
            question_norm TEXT,
            category TEXT
        )
    """)

    # Usage limit table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_usage (
            ip TEXT,
            date TEXT,
            counter INTEGER,
            PRIMARY KEY (ip, date)
        )
    """)

    conn.commit()
    conn.close()


init_database()


# ======================================================
# 3. MEMORY CACHE
# ======================================================
CACHE = {
    "data": [],            # raw (question, answer)
    "norm_questions": [],  # normalized questions
}

def load_cache():
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute("SELECT question, answer, question_norm FROM answers")
    rows = cur.fetchall()
    conn.close()

    CACHE["data"] = [(r[0], r[1]) for r in rows]
    CACHE["norm_questions"] = [r[2] for r in rows]

load_cache()  # load once on startup


# ======================================================
# 4. MODELS
# ======================================================
class Question(BaseModel):
    question: str

class NewAnswer(BaseModel):
    question: str
    answer: str
    category: str | None = None


# ======================================================
# 5. DAILY RATE LIMIT
# ======================================================
def check_usage_limit(ip: str):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()

    cur.execute("SELECT counter FROM api_usage WHERE ip=? AND date=?", (ip, today))
    row = cur.fetchone()

    if row:
        counter = row[0]
        if counter >= DAILY_LIMIT:
            conn.close()
            raise HTTPException(status_code=429, detail="Daily usage limit reached.")
        cur.execute("UPDATE api_usage SET counter=counter+1 WHERE ip=? AND date=?", (ip, today))
    else:
        cur.execute("INSERT INTO api_usage (ip, date, counter) VALUES (?, ?, ?)", (ip, today, 1))

    conn.commit()
    conn.close()


# ======================================================
# 6. ANSWER ENDPOINT (FAST)
# ======================================================
@app.post("/answer")
async def answer_question(q: Question, request: Request, api_key: str = Query(...)):
    validate_api_key(api_key)

    client_ip = request.client.host
    check_usage_limit(client_ip)

    if not CACHE["data"]:
        return {"error": "empty database"}

    input_norm = unidecode(q.question.lower())

    match, score, idx = process.extractOne(
        input_norm,
        CACHE["norm_questions"],
        scorer=fuzz.ratio
    )

    if score >= 70:
        return {
            "answer": CACHE["data"][idx][1],
            "confidence": f"{score:.1f}%"
        }

    return {"error": "I don't know"}


# ======================================================
# 7. CATEGORY & LISTING
# ======================================================
@app.get("/categories")
async def list_categories(api_key: str = Query(...)):
    validate_api_key(api_key)
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM answers WHERE category IS NOT NULL")
    rows = cur.fetchall()
    conn.close()
    return {"categories": [r[0] for r in rows]}


@app.get("/questions/{cat}")
async def list_questions(cat: str, api_key: str = Query(...)):
    validate_api_key(api_key)
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute("SELECT question FROM answers WHERE category=?", (cat,))
    rows = cur.fetchall()
    conn.close()
    return {"category": cat, "questions": [r[0] for r in rows]}


# ======================================================
# 8. INSERT NEW ANSWER (updates cache)
# ======================================================
@app.post("/add")
async def add_answer(item: NewAnswer, api_key: str = Query(...)):
    validate_api_key(api_key)

    q_norm = unidecode(item.question.lower())

    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO answers (question, answer, question_norm, category) VALUES (?, ?, ?, ?)",
        (item.question, item.answer, q_norm, item.category)
    )
    conn.commit()
    conn.close()

    load_cache()  # refresh cache

    return {"status": "ok", "added": item}


# ======================================================
# 9. IMPORT CSV (secure version + updates cache)
# ======================================================
@app.post("/import_csv")
async def import_csv(file: UploadFile, api_key: str = Query(...)):
    validate_api_key(api_key)

    # -----------------------
    # 1. File size limit
    # -----------------------
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)

    MAX_FILE_SIZE = 2_000_000  # ~2 MB
    if size > MAX_FILE_SIZE:
        raise HTTPException(400, detail="CSV file too large. Max allowed is 2 MB.")

    # -----------------------
    # 2. Read file
    # -----------------------
    content = await file.read()
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise HTTPException(400, detail="Invalid file encoding. File must be UTF-8.")

    reader = csv.reader(lines)

    # -----------------------
    # 3. Max number of rows
    # -----------------------
    rows = list(reader)
    MAX_ROWS = 500
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, detail="CSV contains too many rows. Max allowed is 500.")

    # -----------------------
    # 4. Validate fields
    # -----------------------
    for row in rows:
        if len(row) < 2:
            raise HTTPException(400, detail="Each row must contain at least question and answer.")

        q = row[0].strip()
        a = row[1].strip()
        c = row[2].strip() if len(row) >= 3 else None

        if len(q) > 500:
            raise HTTPException(400, detail="Question too long. Max length is 500 characters.")

        if len(a) > 2000:
            raise HTTPException(400, detail="Answer too long. Max length is 2000 characters.")

        if c and len(c) > 100:
            raise HTTPException(400, detail="Category too long. Max length is 100 characters.")

    # -----------------------
    # 5. Insert into database
    # -----------------------
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()

    count = 0
    for row in rows:
        q = row[0].strip()
        a = row[1].strip()
        c = row[2].strip() if len(row) >= 3 else None

        q_norm = unidecode(q.lower())

        cur.execute(
            "INSERT INTO answers (question, answer, question_norm, category) VALUES (?, ?, ?, ?)",
            (q, a, q_norm, c)
        )
        count += 1

    conn.commit()
    conn.close()

    # -----------------------
    # 6. Update in-memory cache
    # -----------------------
    load_cache()

    return {"status": "ok", "added": count}



# ======================================================
# 10. STATUS & HEALTH
# ======================================================
@app.get("/status")
async def status(api_key: str = Query(None)):
    if api_key:
        validate_api_key(api_key)

    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM answers")
    total = cur.fetchone()[0]
    conn.close()

    return {
        "status": "up",
        "version": "1.3-optimized",
        "total_answers": total,
        "uptime_seconds": round(time.time() - start_time, 1)
    }


@app.get("/health")
@app.head("/health")
async def health_check(request: Request):
    return JSONResponse({"status": "up"})

