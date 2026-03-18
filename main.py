import os
import sqlite3
import secrets
import requests
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

DB_PATH = "app.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        share_token TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        role TEXT,
        content TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    username: str = ""
    chat_id: int | None = None
    message: str = ""
    image_base64: str | None = None

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/register")
def register(req: RegisterRequest):
    try:
        conn = get_conn()
        conn.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                     (req.username, req.password))
        conn.commit()
        conn.close()
        return {"success": True}
    except:
        return {"success": False}

@app.post("/login")
def login(req: LoginRequest):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=? AND password=?",
                (req.username, req.password))
    user = cur.fetchone()
    conn.close()

    if user:
        return {"success": True, "username": req.username}
    return {"success": False}

def web_search(q):
    if not q.lower().startswith("araştır"):
        return ""
    try:
        r = requests.get("https://api.duckduckgo.com/",
            params={"q": q, "format": "json"})
        return r.json().get("AbstractText", "")
    except:
        return ""

@app.post("/chat")
def chat(req: ChatRequest):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username=?", (req.username,))
    user = cur.fetchone()
    if not user:
        return {"reply": "Giriş yap"}

    chat_id = req.chat_id

    if not chat_id:
        cur.execute("INSERT INTO chats (user_id, title) VALUES (?, ?)",
                    (user["id"], "Yeni"))
        chat_id = cur.lastrowid

    web = web_search(req.message)

    messages = [
        {"role": "system", "content": "Sen zeki bir asistansın."}
    ]

    if web:
        messages.append({"role": "system", "content": web})

    messages.append({"role": "user", "content": req.message})

    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages
    )

    reply = res.choices[0].message.content

    cur.execute("INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                (chat_id, "user", req.message))
    cur.execute("INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                (chat_id, "assistant", reply))

    conn.commit()
    conn.close()

    return {"reply": reply, "chat_id": chat_id}
