from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
import uuid
import json
import os

app = FastAPI()

# CORS (NETLIFY FIX)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET = "SECRET_KEY"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DB_FILE = "db.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "chats": {}}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f)

class Register(BaseModel):
    username: str
    password: str

class Login(BaseModel):
    username: str
    password: str

class Chat(BaseModel):
    token: str
    message: str

@app.get("/")
def home():
    return {"status": "ok"}

@app.post("/register")
def register(data: Register):
    db = load_db()
    if data.username in db["users"]:
        raise HTTPException(400, "User exists")

    hashed = pwd_context.hash(data.password)
    db["users"][data.username] = {"password": hashed}
    save_db(db)
    return {"msg": "registered"}

@app.post("/login")
def login(data: Login):
    db = load_db()
    user = db["users"].get(data.username)

    if not user or not pwd_context.verify(data.password, user["password"]):
        raise HTTPException(401, "Invalid login")

    token = jwt.encode(
        {"sub": data.username, "exp": datetime.utcnow() + timedelta(days=1)},
        SECRET
    )

    return {"token": token}

@app.post("/chat")
def chat(data: Chat):
    db = load_db()

    try:
        payload = jwt.decode(data.token, SECRET, algorithms=["HS256"])
        username = payload["sub"]
    except:
        raise HTTPException(401, "Invalid token")

    reply = f"🤖: {data.message[::-1]}"  # demo AI

    chat_id = str(uuid.uuid4())

    db["chats"][chat_id] = {
        "user": username,
        "message": data.message,
        "reply": reply,
        "time": str(datetime.utcnow())
    }

    save_db(db)

    return {"reply": reply, "chat_id": chat_id}

@app.get("/history/{token}")
def history(token: str):
    db = load_db()

    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
        username = payload["sub"]
    except:
        raise HTTPException(401, "Invalid token")

    chats = [v for v in db["chats"].values() if v["user"] == username]

    return chats
