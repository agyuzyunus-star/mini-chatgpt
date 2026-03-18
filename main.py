from datetime import datetime
import os
import secrets
import sqlite3
import requests
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
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            share_token TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(chat_id) REFERENCES chats(id)
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


class CreateChatRequest(BaseModel):
    username: str


class RenameChatRequest(BaseModel):
    chat_id: int
    title: str


class DeleteChatRequest(BaseModel):
    chat_id: int


class ClearChatsRequest(BaseModel):
    username: str


class ShareChatRequest(BaseModel):
    chat_id: int


class ChatRequest(BaseModel):
    username: str
    chat_id: int
    message: str = ""
    image_base64: str | None = None
    chosen_language: str = "auto"


@app.get("/")
def root():
    return {"status": "ok", "message": "Mini ChatGPT backend is running."}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/register")
def register(req: RegisterRequest):
    username = req.username.strip()
    password = req.password.strip()

    if not username or not password:
        return {"success": False, "message": "Kullanıcı adı ve şifre boş olamaz."}

    if len(username) < 3:
        return {"success": False, "message": "Kullanıcı adı en az 3 karakter olmalı."}

    if len(password) < 4:
        return {"success": False, "message": "Şifre en az 4 karakter olmalı."}

    try:
        conn = get_conn()
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

    conn = get_conn()
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


@app.get("/profile/{username}")
def get_profile(username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, created_at FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return dict(user)


@app.post("/chats/create")
def create_chat(req: CreateChatRequest):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (req.username,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return {"success": False, "message": "Kullanıcı bulunamadı."}

    cur.execute(
        "INSERT INTO chats (user_id, title) VALUES (?, ?)",
        (user["id"], "Yeni Sohbet")
    )
    chat_id = cur.lastrowid

    cur.execute(
        "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
        (chat_id, "assistant", "Merhaba. Size nasıl yardımcı olabilirim?")
    )

    conn.commit()
    conn.close()

    return {"success": True, "chat_id": chat_id}


@app.get("/chats/{username}")
def get_chats(username: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return []

    cur.execute("""
        SELECT c.id, c.title, c.share_token,
               (SELECT content FROM messages m WHERE m.chat_id = c.id ORDER BY m.id DESC LIMIT 1) AS preview
        FROM chats c
        WHERE c.user_id = ?
        ORDER BY c.id DESC
    """, (user["id"],))

    chats = [dict(row) for row in cur.fetchall()]
    conn.close()
    return chats


@app.get("/messages/{chat_id}")
def get_messages(chat_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, role, content, created_at FROM messages WHERE chat_id = ? ORDER BY id ASC",
        (chat_id,)
    )
    messages = [dict(row) for row in cur.fetchall()]
    conn.close()
    return messages


@app.post("/chats/rename")
def rename_chat(req: RenameChatRequest):
    if not req.title.strip():
        return {"success": False, "message": "Başlık boş olamaz."}

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE chats SET title = ? WHERE id = ?", (req.title.strip(), req.chat_id))
    conn.commit()
    conn.close()
    return {"success": True}


@app.post("/chats/delete")
def delete_chat(req: DeleteChatRequest):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM messages WHERE chat_id = ?", (req.chat_id,))
    cur.execute("DELETE FROM chats WHERE id = ?", (req.chat_id,))
    conn.commit()
    conn.close()
    return {"success": True}


@app.post("/chats/clear")
def clear_chats(req: ClearChatsRequest):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (req.username,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return {"success": False, "message": "Kullanıcı bulunamadı."}

    cur.execute("SELECT id FROM chats WHERE user_id = ?", (user["id"],))
    chat_ids = [row["id"] for row in cur.fetchall()]

    for chat_id in chat_ids:
        cur.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))

    cur.execute("DELETE FROM chats WHERE user_id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return {"success": True}


@app.post("/chats/share")
def share_chat(req: ShareChatRequest):
    token = secrets.token_urlsafe(10)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE chats SET share_token = ? WHERE id = ?", (token, req.chat_id))
    conn.commit()
    conn.close()
    return {"success": True, "share_token": token}


@app.get("/shared/{share_token}")
def get_shared_chat(share_token: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, title FROM chats WHERE share_token = ?", (share_token,))
    chat = cur.fetchone()
    if not chat:
        conn.close()
        raise HTTPException(status_code=404, detail="Paylaşılan sohbet bulunamadı.")

    cur.execute(
        "SELECT role, content, created_at FROM messages WHERE chat_id = ? ORDER BY id ASC",
        (chat["id"],)
    )
    messages = [dict(row) for row in cur.fetchall()]
    conn.close()

    return {
        "title": chat["title"],
        "messages": messages
    }


def build_language_instruction(chosen_language: str) -> str:
    mapping = {
        "tr": "Always answer in Turkish.",
        "en": "Always answer in English.",
        "de": "Always answer in German.",
        "fr": "Always answer in French.",
        "es": "Always answer in Spanish.",
        "auto": "Detect the user's language and answer in that language."
    }
    return mapping.get(chosen_language, "Detect the user's language and answer in that language.")


def maybe_search_web(query: str) -> str:
    q = query.strip()
    if not q:
        return ""

    lowered = q.lower()
    should_search = lowered.startswith("araştır:") or lowered.startswith("search:") or lowered.startswith("web:")
    if not should_search:
        return ""

    clean_q = q.split(":", 1)[1].strip() if ":" in q else q

    try:
        ddg_url = "https://api.duckduckgo.com/"
        resp = requests.get(ddg_url, params={
            "q": clean_q,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1"
        }, timeout=15)
        data = resp.json()

        parts = []
        if data.get("AbstractText"):
            parts.append(f"Özet: {data['AbstractText']}")
        if data.get("Heading"):
            parts.append(f"Konu: {data['Heading']}")

        related = data.get("RelatedTopics", [])
        count = 0
        for item in related:
            if isinstance(item, dict):
                text = item.get("Text")
                if text:
                    parts.append(f"- {text}")
                    count += 1
                    if count >= 5:
                        break

        return "\n".join(parts[:6])
    except Exception:
        return ""


@app.post("/chat")
def chat(req: ChatRequest):
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY is missing.")

    now = datetime.now().strftime("%H:%M")
    lang_instruction = build_language_instruction(req.chosen_language)
    web_context = maybe_search_web(req.message)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (req.username,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return {"reply": "Kullanıcı bulunamadı."}

    cur.execute("SELECT id, title FROM chats WHERE id = ?", (req.chat_id,))
    chat = cur.fetchone()
    if not chat:
        conn.close()
        return {"reply": "Sohbet bulunamadı."}

    cur.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC",
        (req.chat_id,)
    )
    history_rows = cur.fetchall()

    messages = [
        {
            "role": "system",
            "content": f"""
You are a smart, high-quality, multilingual AI assistant.

Rules:
- {lang_instruction}
- Be natural, helpful, clear, and intelligent.
- Do not act random, weird, or nonsensical.
- Do not produce unrelated answers.
- If the user asks a simple question, answer directly.
- If the user asks for detailed help, explain clearly.
- Keep answers concise unless the user asks for more detail.
- If an image is provided, analyze it carefully.
- If both text and image are provided, use both together.
- If the user asks for time, current local time is {now}.
- If the user asks for code, return clean usable code.
- If you are unsure, say it briefly but still try to help.
"""
        }
    ]

    if web_context:
        messages.append({
            "role": "system",
            "content": f"Web araştırma özeti:\n{web_context}"
        })

    for row in history_rows:
        if row["role"] in ["user", "assistant", "system"]:
            messages.append({
                "role": row["role"],
                "content": row["content"]
            })

    try:
        if req.image_base64:
            text_part = req.message.strip() if req.message.strip() else "Analyze this image."
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
            user_message = req.message.strip() if req.message.strip() else "Hello"
            messages.append({
                "role": "user",
                "content": user_message
            })

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.2
            )

        reply = response.choices[0].message.content if response.choices else "Bir cevap alınamadı."

        cur.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (req.chat_id, "user", req.message if req.message.strip() else "[boş mesaj]")
        )
        cur.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (req.chat_id, "assistant", reply)
        )

        cur.execute("SELECT title FROM chats WHERE id = ?", (req.chat_id,))
        current_title = cur.fetchone()["title"]
        if current_title == "Yeni Sohbet" and req.message.strip():
            cur.execute(
                "UPDATE chats SET title = ? WHERE id = ?",
                (req.message.strip()[:25], req.chat_id)
            )

        conn.commit()
        conn.close()

        return {"reply": reply}

    except Exception as e:
        conn.close()
        return {"reply": f"Hata oluştu: {str(e)}"}
