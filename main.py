from fastapi import FastAPI, HTTPException, Query, UploadFile, Request
from pydantic import BaseModel
import sqlite3
import os
import csv
from rapidfuzz import fuzz, process
from unidecode import unidecode
import time
from datetime import datetime

app = FastAPI(title="Auto Answer API")

# ======================
# 1. Simple Authentication
# ======================
API_KEY = os.getenv("API_KEY", "123abc")


def validate_api_key(key: str):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")


# ======================
# 2. Database Structure
# ======================
def init_database():
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            answer TEXT,
            category TEXT
        )
    """)
    # Table for daily usage control
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
start_time = time.time()


# ======================
# 3. Pydantic Models
# ======================
class Question(BaseModel):
    question: str


class NewAnswer(BaseModel):
    question: str
    answer: str
    category: str | None = None


# ======================
# 4. Daily Usage Control
# ======================
DAILY_LIMIT = 20


def check_usage_limit(ip: str):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT counter FROM api_usage WHERE ip=? AND date=?", (ip, today))
    row = cur.fetchone()

    if row:
        counter = row[0]
        if counter >= DAILY_LIMIT:
            conn.close()
            raise HTTPException(
                status_code=429, detail="Daily usage limit reached (20 requests per day)."
            )
        cur.execute(
            "UPDATE api_usage SET counter=counter+1 WHERE ip=? AND date=?", (
                ip, today)
        )
    else:
        cur.execute(
            "INSERT INTO api_usage (ip, date, counter) VALUES (?, ?, ?)", (ip, today, 1)
        )

    conn.commit()
    conn.close()


# ======================
# 5. Main Endpoint
# ======================
@app.post("/answer")
async def answer_question(q: Question, request: Request, api_key: str = Query(...)):
    validate_api_key(api_key)
    client_ip = request.client.host
    check_usage_limit(client_ip)

    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute("SELECT question, answer FROM answers")
    all_data = cur.fetchall()
    conn.close()

    if not all_data:
        return {"error": "empty database"}

    db_questions = [unidecode(q.lower()) for q, _ in all_data]
    input_q = unidecode(q.question.lower())

    match, score, idx = process.extractOne(
        input_q, db_questions, scorer=fuzz.ratio)
    if score >= 70:
        response = all_data[idx][1]
        return {"answer": response, "confidence": f"{score:.1f}%"}

    return {"error": "I don't know"}


# ======================
# 6. Listing Endpoints
# ======================
@app.get("/categories")
async def list_categories(api_key: str = Query(...)):
    validate_api_key(api_key)
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT category FROM answers WHERE category IS NOT NULL"
    )
    categories = [row[0] for row in cur.fetchall()]
    conn.close()
    return {"categories": categories}


@app.get("/questions/{cat}")
async def list_questions(cat: str, api_key: str = Query(...)):
    validate_api_key(api_key)
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute("SELECT question FROM answers WHERE category=?", (cat,))
    questions = [row[0] for row in cur.fetchall()]
    conn.close()
    return {"category": cat, "questions": questions}


# ======================
# 7. Add Manually
# ======================
@app.post("/add")
async def add_answer(item: NewAnswer, api_key: str = Query(...)):
    validate_api_key(api_key)
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO answers (question, answer, category) VALUES (?, ?, ?)",
        (item.question, item.answer, item.category)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "added": item}


# ======================
# 8. Import from CSV
# ======================
@app.post("/import_csv")
async def import_csv(file: UploadFile, api_key: str = Query(...)):
    validate_api_key(api_key)
    content = await file.read()
    lines = content.decode("utf-8").splitlines()
    reader = csv.reader(lines)

    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    count = 0
    for line in reader:
        if len(line) >= 2:
            question, answer, *category = line
            cat = category[0] if category else None
            cur.execute(
                "INSERT INTO answers (question, answer, category) VALUES (?, ?, ?)",
                (question.strip(), answer.strip(), cat)
            )
            count += 1
    conn.commit()
    conn.close()
    return {"status": "ok", "added": count}


# ======================
# 9. API Status
# ======================
@app.get("/status")
async def status():
    uptime = round(time.time() - start_time, 1)
    conn = sqlite3.connect("answers.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM answers")
    total = cur.fetchone()[0]
    conn.close()

    return {
        "status": "up",
        "version": "1.2",
        "total_answers": total,
        "uptime_seconds": uptime
    }

