from datetime import datetime
import sqlite3
from fastapi import FastAPI
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

import os

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

DB_PATH = "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
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
    message: str = ""
    history: list = []
    image_base64: str | None = None

@app.post("/register")
def register(req: RegisterRequest):
    username = req.username.strip()
    password = req.password.strip()

    if not username or not password:
        return {"success": False, "message": "Kullanıcı adı ve şifre boş olamaz."}

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, password)
        )
        conn.commit()
        conn.close()
        return {"success": True, "message": "Kayıt başarılı."}
    except sqlite3.IntegrityError:
        return {"success": False, "message": "Bu kullanıcı adı zaten var."}

@app.post("/login")
def login(req: LoginRequest):
    username = req.username.strip()
    password = req.password.strip()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM users WHERE username = ? AND password = ?",
        (username, password)
    )
    user = cur.fetchone()
    conn.close()

    if user:
        return {
            "success": True,
            "message": "Giriş başarılı.",
            "username": username
        }

    return {"success": False, "message": "Kullanıcı adı veya şifre yanlış."}

@app.post("/chat")
def chat(req: ChatRequest):
    now = datetime.now().strftime("%H:%M")

    messages = [
        {
            "role": "system",
            "content": f"""
You are a high-quality multilingual assistant.

Rules:
- Always reply in the user's language.
- If the user writes Turkish, reply in Turkish.
- If the user writes German, reply in German.
- If the user writes English, reply in English.
- Be natural, helpful, and clear.
- If an image is provided, analyze it carefully.
- If both text and image are provided, use both together.
- Keep answers concise unless the user asks for detail.
- Current local time is: {now}
- If the user asks the time, answer using that time.
"""
        }
    ]

    for msg in req.history:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            role = msg["role"]
            content = msg["content"]
            if role in ["user", "assistant", "system"] and isinstance(content, str):
                messages.append({"role": role, "content": content})

    if req.image_base64:
        text_part = req.message.strip() if req.message.strip() else "Bu görseli analiz et."
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": text_part},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": req.image_base64
                    }
                }
            ]
        })

        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=messages,
            temperature=0.2
        )
    else:
        messages.append({
            "role": "user",
            "content": req.message if req.message.strip() else "Merhaba"
        })

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.2
        )

    return {"reply": response.choices[0].message.content}