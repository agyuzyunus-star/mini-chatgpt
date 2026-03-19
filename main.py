import os
import re
import sqlite3
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://agyuzyunus-star.github.io",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=False,
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
    username: str = ""
    chat_id: int | None = None
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

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


@app.get("/messages/{chat_id}")
def get_messages(chat_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, role, content, created_at FROM messages WHERE chat_id = ? ORDER BY id ASC",
        (chat_id,)
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


@app.post("/chats/rename")
def rename_chat(req: RenameChatRequest):
    title = req.title.strip()
    if not title:
        return {"success": False, "message": "Başlık boş olamaz."}

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE chats SET title = ? WHERE id = ?", (title, req.chat_id))
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


def normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def detect_time_zone_from_message(message: str) -> tuple[str, str] | None:
    msg = normalize_text(message)

    zone_map = [
        (["türkiye", "turkiye", "istanbul", "ankara", "izmir"], "Europe/Istanbul", "Türkiye"),
        (["almanya", "germany", "augsburg", "berlin", "münih", "munich"], "Europe/Berlin", "Almanya"),
        (["londra", "london", "ingiltere", "uk"], "Europe/London", "Londra"),
        (["new york", "amerika", "usa", "abd"], "America/New_York", "New York"),
        (["tokyo", "japonya", "japan"], "Asia/Tokyo", "Tokyo"),
        (["paris", "fransa", "france"], "Europe/Paris", "Paris"),
    ]

    for keywords, tz, label in zone_map:
        if any(k in msg for k in keywords):
            return tz, label

    return None


def is_time_question(message: str) -> bool:
    msg = normalize_text(message)
    keywords = [
        "saat kaç", "saat kac", "kaç saat", "kac saat",
        "time", "what time", "uhr", "wie viel uhr"
    ]
    return any(k in msg for k in keywords)


def answer_time_question(message: str) -> str | None:
    if not is_time_question(message):
        return None

    zone_info = detect_time_zone_from_message(message)
    if not zone_info:
        zone_info = ("Europe/Berlin", "Almanya")

    tz_name, label = zone_info
    now = datetime.now(ZoneInfo(tz_name))
    return f"Şu an {label}'da saat {now.strftime('%H:%M')}."


def detect_weather_location(message: str) -> str | None:
    msg = normalize_text(message)

    known = {
        "augsburg": "Augsburg",
        "istanbul": "Istanbul",
        "ankara": "Ankara",
        "izmir": "Izmir",
        "berlin": "Berlin",
        "londra": "London",
        "london": "London",
        "münih": "Munich",
        "munich": "Munich",
    }

    for k, v in known.items():
        if k in msg:
            return v

    match = re.search(r"(?:weather in|hava durumu|hava nasıl|weather)\s+([a-zA-ZçğıöşüÇĞİÖŞÜ\s\-]+)", message, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return None


def is_weather_question(message: str) -> bool:
    msg = normalize_text(message)
    keys = [
        "hava", "weather", "sıcaklık", "sicaklik",
        "yağmur", "yagmur", "rüzgar", "ruzgar"
    ]
    return any(k in msg for k in keys)


def get_live_weather(location: str) -> str | None:
    try:
        url = f"https://wttr.in/{location}?format=j1"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        current = data["current_condition"][0]
        temp_c = current.get("temp_C", "?")
        feels = current.get("FeelsLikeC", "?")
        humidity = current.get("humidity", "?")
        desc = current.get("weatherDesc", [{"value": "Bilinmiyor"}])[0]["value"]

        return (
            f"{location} için güncel hava durumu: {desc}. "
            f"Sıcaklık {temp_c}°C, hissedilen {feels}°C, nem %{humidity}."
        )
    except Exception:
        return None


def maybe_get_web_context(message: str) -> str:
    msg = message.strip()
    if not msg:
        return ""

    trigger_words = [
        "araştır:", "arastir:", "search:", "web:",
        "google", "internetten", "haber", "güncel", "guncel"
    ]

    should_search = any(t in normalize_text(msg) for t in trigger_words) or is_weather_question(msg) or is_time_question(msg)
    if not should_search:
        return ""

    query = msg
    for prefix in ["araştır:", "arastir:", "search:", "web:"]:
        if normalize_text(query).startswith(prefix):
            query = query.split(":", 1)[1].strip()
            break

    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1"
            },
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        parts = []
        if data.get("Heading"):
            parts.append(f"Konu: {data['Heading']}")
        if data.get("AbstractText"):
            parts.append(f"Özet: {data['AbstractText']}")

        related = data.get("RelatedTopics", [])
        count = 0
        for item in related:
            if isinstance(item, dict) and item.get("Text"):
                parts.append("- " + item["Text"])
                count += 1
                if count >= 5:
                    break

        return "\n".join(parts[:8]).strip()
    except Exception:
        return ""


def save_messages(conn, chat_id: int, user_text: str, assistant_text: str):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
        (chat_id, "user", user_text)
    )
    cur.execute(
        "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
        (chat_id, "assistant", assistant_text)
    )
    conn.commit()


@app.post("/chat")
def chat(req: ChatRequest):
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY is missing.")

    username = req.username.strip()
    if not username:
        return {"reply": "Önce giriş yapmalısınız."}

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return {"reply": "Kullanıcı bulunamadı."}

    chat_id = req.chat_id

    if chat_id is None:
        cur.execute(
            "INSERT INTO chats (user_id, title) VALUES (?, ?)",
            (user["id"], "Yeni Sohbet")
        )
        chat_id = cur.lastrowid
    else:
        cur.execute("SELECT id, title FROM chats WHERE id = ?", (chat_id,))
        chat_row = cur.fetchone()
        if not chat_row:
            cur.execute(
                "INSERT INTO chats (user_id, title) VALUES (?, ?)",
                (user["id"], "Yeni Sohbet")
            )
            chat_id = cur.lastrowid

    user_message = req.message.strip() if req.message.strip() else "Merhaba"

    # 1) Saat sorularını direkt canlı saatle cevapla
    direct_time_answer = answer_time_question(user_message)
    if direct_time_answer and not req.image_base64:
        save_messages(conn, chat_id, user_message, direct_time_answer)

        cur.execute("SELECT title FROM chats WHERE id = ?", (chat_id,))
        row = cur.fetchone()
        current_title = row["title"] if row else "Yeni Sohbet"
        if current_title == "Yeni Sohbet" and req.message.strip():
            cur.execute(
                "UPDATE chats SET title = ? WHERE id = ?",
                (req.message.strip()[:25], chat_id)
            )
            conn.commit()

        conn.close()
        return {"reply": direct_time_answer, "chat_id": chat_id}

    # 2) Hava durumunu internetten çek
    if is_weather_question(user_message) and not req.image_base64:
        location = detect_weather_location(user_message) or "Augsburg"
        weather_answer = get_live_weather(location)
        if weather_answer:
            save_messages(conn, chat_id, user_message, weather_answer)

            cur.execute("SELECT title FROM chats WHERE id = ?", (chat_id,))
            row = cur.fetchone()
            current_title = row["title"] if row else "Yeni Sohbet"
            if current_title == "Yeni Sohbet" and req.message.strip():
                cur.execute(
                    "UPDATE chats SET title = ? WHERE id = ?",
                    (req.message.strip()[:25], chat_id)
                )
                conn.commit()

            conn.close()
            return {"reply": weather_answer, "chat_id": chat_id}

    # 3) Geçmiş mesajları topla
    cur.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC",
        (chat_id,)
    )
    history_rows = cur.fetchall()

    now_berlin = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%H:%M")
    now_istanbul = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%H:%M")
    now_london = datetime.now(ZoneInfo("Europe/London")).strftime("%H:%M")

    lang_instruction = build_language_instruction(req.chosen_language)
    web_context = maybe_get_web_context(user_message)

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
- For current time questions, use these reliable references:
  - Germany (Europe/Berlin): {now_berlin}
  - Turkey (Europe/Istanbul): {now_istanbul}
  - London (Europe/London): {now_london}
- If web research notes are available, use them.
- If you are unsure, say what is certain and what is uncertain.
"""
        }
    ]

    if web_context:
        messages.append({
            "role": "system",
            "content": f"Güncel web notları:\n{web_context}"
        })

    for row in history_rows:
        if row["role"] in ["user", "assistant", "system"]:
            messages.append({
                "role": row["role"],
                "content": row["content"]
            })

    try:
        display_user_message = user_message

        if req.image_base64:
            text_part = user_message if user_message else "Bu görseli analiz et."
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": text_part},
                    {
                        "type": "image_url",
                        "image_url": {"url": req.image_base64}
                    }
                ]
            })

            if not display_user_message:
                display_user_message = "[Görsel gönderildi]"

            response = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=messages,
                temperature=0.2
            )
        else:
            messages.append({"role": "user", "content": user_message})

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.2
            )

        reply = response.choices[0].message.content if response.choices else "Bir cevap alınamadı."

        save_messages(conn, chat_id, display_user_message, reply)

        cur.execute("SELECT title FROM chats WHERE id = ?", (chat_id,))
        row = cur.fetchone()
        current_title = row["title"] if row else "Yeni Sohbet"

        if current_title == "Yeni Sohbet" and req.message.strip():
            cur.execute(
                "UPDATE chats SET title = ? WHERE id = ?",
                (req.message.strip()[:25], chat_id)
            )
            conn.commit()

        conn.close()

        return {
            "reply": reply,
            "chat_id": chat_id
        }

    except Exception as e:
        conn.close()
        return {"reply": f"Hata oluştu: {str(e)}"}
