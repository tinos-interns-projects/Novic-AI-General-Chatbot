# streamlit_app.py — Novic-AI Chatbot with Modal Login + SQLite storage
import streamlit as st
import sqlite3
import json
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from rag_chain import ask, retrain
import os


def init_session_state():
    defaults = {
        "page": "start",
        "user": None,
        "selected_chat_id": None,
        "search_q": "",
        "upload_toggle": False,
        "uploaded_files": []
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session_state()


DB_PATH = "chat_app.db"
# ---------- DB Helpers ----------
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        )"""
    )
    conn.commit()
    return conn

conn = init_db()
cur = conn.cursor()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def authenticate_user(email: str, password: str) -> Optional[dict]:
    cur.execute("SELECT id,name,email,password_hash FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    if not row:
        return None
    stored_hash = row[3]
    if stored_hash == hash_password(password):
        return {"id": row[0], "name": row[1], "email": row[2]}
    return None


def create_user(name: str, email: str, password: str) -> Optional[str]:
    user_id = str(uuid.uuid4())
    pw = hash_password(password)
    try:
        cur.execute("INSERT INTO users (id,name,email,password_hash,created_at) VALUES (?,?,?,?,?)",
                    (user_id, name, email, pw, datetime.now().isoformat()))
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        return None


def create_chat(user_id: str, title: str = "New Chat") -> str:
    chat_id = str(uuid.uuid4())
    ts = datetime.now().isoformat()
    cur.execute("INSERT INTO chats (id,user_id,title,timestamp) VALUES (?,?,?,?)", (chat_id, user_id, title, ts))
    conn.commit()
    return chat_id


def get_messages(chat_id: str):
    cur.execute("SELECT role,content,timestamp FROM messages WHERE chat_id = ? ORDER BY timestamp ASC", (chat_id,))
    return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in cur.fetchall()]

if "page" not in st.session_state:
    st.session_state.page = "start"


def start_page():
    st.markdown("<h1 style='text-align:center'>Novic-AI</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center;color:gray'>AI Chat Assistant</p>",
        unsafe_allow_html=True
    )

    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([3,2,3])
    with col2:
        if st.button("Start", use_container_width=True):
            st.session_state.page = "auth"
            st.rerun()

def auth_choice_page():
    st.markdown("## Welcome to Novic-AI")
    st.markdown("Choose how you want to continue")

    st.markdown("<br>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔐 Login", use_container_width=True):
            st.session_state.page = "login"
            st.rerun()

    with col2:
        if st.button("📝 Sign Up", use_container_width=True):
            st.session_state.page = "signup"
            st.rerun()


def login_page():
    st.markdown("## Login")

    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")

    if submit:
        user = authenticate_user(email, password)
        if user:
            st.session_state.user = user
            st.session_state.page = "chat"
            st.rerun()
        else:
            st.error("Invalid credentials")
        
    st.markdown("Don't have an account?")
    if st.button("Create one"):
        st.session_state.page = "signup"
        st.rerun()



def signup_page():
    st.markdown("## Create Account")

    with st.form("signup_form"):
        name = st.text_input("Full Name")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm Password", type="password")

        submit = st.form_submit_button("Sign Up")

    if submit:
        if not name or not email or not password:
            st.error("All fields are required")
            return

        if password != confirm:
            st.error("Passwords do not match")
            return

        user_id = create_user(name, email, password)

        if not user_id:
            st.error("Email already registered")
            return

        # Auto-login after signup
        st.session_state.user = {
            "id": user_id,
            "name": name,
            "email": email
        }
        st.session_state.page = "chat"
        st.rerun()


def get_chats_for_user(user_id: str):
    cur.execute("SELECT id,title,timestamp FROM chats WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
    rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "timestamp": r[2]} for r in rows]


def delete_chat(chat_id: str):
    cur.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    cur.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()

def clear_all_chats_for_user(user_id: str):
    cur.execute("SELECT id FROM chats WHERE user_id = ?", (user_id,))
    ids = [r[0] for r in cur.fetchall()]
    for cid in ids:
        delete_chat(cid)


def rename_chat(chat_id: str, new_title: str):
    cur.execute("UPDATE chats SET title = ?, timestamp = ? WHERE id = ?", (new_title, datetime.now().isoformat(), chat_id))
    conn.commit()


def auto_rename_chat(chat_id):
    msgs = get_messages(chat_id)
    for m in msgs:
        if m["role"] == "user":
            rename_chat(chat_id, short_title_from_text(m["content"]))
            break


def add_message(chat_id: str, role: str, content: str):
    mid = str(uuid.uuid4())
    ts = datetime.now().isoformat()
    cur.execute("INSERT INTO messages (id,chat_id,role,content,timestamp) VALUES (?,?,?,?,?)", (mid, chat_id, role, content, ts))
    cur.execute("UPDATE chats SET timestamp = ? WHERE id = ?", (ts, chat_id))
    conn.commit()


def display_time_short(iso_ts):
    try:
        dt = datetime.fromisoformat(iso_ts)
        return dt.strftime("%b %d • %I:%M %p")
    except Exception:
        return iso_ts


def sidebar(user):
    with st.sidebar:

        # ---------- PROFILE CARD ----------
        st.markdown(f"### 👤 {user['name']}")
        st.caption(user["email"])
        st.divider()

        # ---------- SEARCH ----------
        st.text_input(
            "🔍 Search chats",
            key="search_q",
            placeholder="Search by title or content"
        )
        st.divider()

        # ---------- NEW CHAT ----------
        if st.button("➕ New Chat", key="new_chat_sidebar", use_container_width=True):
            st.session_state.selected_chat_id = create_chat(user["id"])
            st.rerun()

        st.divider()

        # ---------- CHAT LIST ----------
        chats = get_chats_for_user(user["id"])

        q = (st.session_state.search_q or "").lower().strip()
        if q:
            filtered = []
            for c in chats:
                if q in c["title"].lower():
                    filtered.append(c)
                    continue
                cur.execute(
                    "SELECT content FROM messages WHERE chat_id=?",
                    (c["id"],)
                )
                if q in " ".join(r[0] for r in cur.fetchall()).lower():
                    filtered.append(c)
            chats = filtered

        today = datetime.now().date()

        for chat in chats:
            c1, c2, c3 = st.columns([8, 1, 1])

            # Select chat
            with c1:
                if st.button(
                    chat["title"],
                    key=f"open_{chat['id']}",
                    use_container_width=True
                ):
                    st.session_state.selected_chat_id = chat["id"]
                    st.rerun()

                st.markdown(
                    f"<div style='font-size:11px;color:#64748b'>"
                    f"{display_time_short(chat['timestamp'])}</div>",
                    unsafe_allow_html=True
                )

            # Rename
            with c2:
                if st.button("✏️", key=f"rename_btn_{chat['id']}"):
                    st.session_state.rename_target = chat["id"]

            # Delete
            with c3:
                if st.button("🗑️", key=f"delete_btn_{chat['id']}"):
                    delete_chat(chat["id"])
                    if st.session_state.selected_chat_id == chat["id"]:
                        st.session_state.selected_chat_id = None
                    st.rerun()

        st.divider()

        if "rename_target" not in st.session_state:
            st.session_state.rename_target = None

        if st.session_state.rename_target:
            with st.sidebar.form("rename_chat_form"):
                new_title = st.text_input("New chat name")
                save = st.form_submit_button("Save")
                cancel = st.form_submit_button("Cancel")

            if save and new_title.strip():
                rename_chat(st.session_state.rename_target, new_title.strip())
                st.session_state.rename_target = None
                st.rerun()

            if cancel:
                st.session_state.rename_target = None
                st.rerun()


        # ---------- LOGOUT ----------
        if st.button("🚪 Logout", key="logout_sidebar", use_container_width=True):
            st.session_state.clear()
            st.session_state.page = "login"
            st.rerun()


        

# ---------- HANDLE CHAT MESSAGE ----------
def chat_page():
    user = st.session_state.user
    sidebar(user)

    st.markdown(f"### Novic-AI — Hello, **{user['name']}**")
    st.markdown("---")

    if "selected_chat_id" not in st.session_state:
        st.session_state.selected_chat_id = create_chat(user["id"])

    chat_id = st.session_state.selected_chat_id

    # If no chat selected, pick the most recent for user
    if not st.session_state.selected_chat_id:
        user_chats = get_chats_for_user(user["id"])
        if user_chats:
            st.session_state.selected_chat_id = user_chats[0]["id"]
        else:
            # create one
            st.session_state.selected_chat_id = create_chat(user["id"], "New Chat")

    current_chat_id = st.session_state.selected_chat_id

    # Fetch chat details and messages
    cur.execute("SELECT title,timestamp FROM chats WHERE id = ?", (current_chat_id,))
    row = cur.fetchone()
    if not row:
        st.info("No chat selected. Create a new chat from the sidebar.")
        st.stop()

    current_title, current_ts = row[0], row[1]
    st.markdown(f"### {current_title}")
    st.markdown(f"<div class='muted'>Last updated: {display_time_short(current_ts)}</div>", unsafe_allow_html=True)
    st.markdown("---")

    # Display chat history
    db_messages = get_messages(current_chat_id)
    for msg in db_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    st.markdown("")  # Space before input bar

    # Chat input
    prompt = st.chat_input("Message Novic-AI…")

    if prompt:
        add_message(current_chat_id, "user", prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                reply = ask(prompt)
                st.markdown(reply)

        add_message(current_chat_id, "assistant", reply)
        st.rerun()


# # Initialize session state variables
# if "messages" not in st.session_state:
#     st.session_state.messages = []

# if "history_memory" not in st.session_state:
#     st.session_state.history_memory = []

# if "user" not in st.session_state:
#     st.session_state.user = None

# if "selected_chat_id" not in st.session_state:
#     st.session_state.selected_chat_id = None




# ---------------- PAGE CONFIG ----------------
st.set_page_config(
    page_title="Novic-AI",
    layout="wide",
    initial_sidebar_state="collapsed"
)



if st.session_state.page == "start":
    start_page()
    st.stop()

if st.session_state.page == "auth":
    auth_choice_page()
    st.stop()

if st.session_state.page == "login":
    login_page()
    st.stop()

if st.session_state.page == "signup":
    signup_page()
    st.stop()


if st.session_state.page == "chat":
    if not st.session_state.user:
        st.session_state.page = "login"
        st.rerun()
    chat_page()
    st.stop()

# ---------- OPTIONAL CTA BELOW ----------
st.markdown("""
<br><br>
<center style="color:#64748b">Trusted by students, analysts, and developers</center>
""", unsafe_allow_html=True)


import pdfplumber

def extract_text_from_file(filepath):
    if filepath.endswith(".txt"):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    if filepath.endswith(".pdf"):
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text

    return ""

# ---------- CSS (glass UI small tweaks) ----------
st.markdown(
    """
    <style>
    .stApp { background: linear-gradient(135deg, rgba(248,249,250,0.95), rgba(240,248,255,0.95)); }
    .sidebar .block-container { background: rgba(255,255,255,0.55); border-radius: 12px; padding: 12px;}
    .chat-card { background: rgba(255,255,255,0.85); border-radius: 12px; padding: 12px; }
    .muted { color: #475569; font-size:12px; }
    </style>
    """,
    unsafe_allow_html=True,
)



# ---------- DB CRUD ----------



def get_user(user_id: str) -> Optional[dict]:
    cur.execute("SELECT id,name,email,created_at FROM users WHERE id = ?", (user_id,))
    r = cur.fetchone()
    if r:
        return {"id": r[0], "name": r[1], "email": r[2], "created_at": r[3]}
    return None


def export_chat_json(chat_id: str, filename: str):
    cur.execute("SELECT id,title,timestamp FROM chats WHERE id = ?", (chat_id,))
    chat = cur.fetchone()
    if not chat:
        return None
    messages = get_messages(chat_id)
    out = {"id": chat[0], "title": chat[1], "timestamp": chat[2], "messages": messages}
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return filename


# ---------- Session state init ----------
if "user" not in st.session_state:
    st.session_state.user = None

if "selected_chat_id" not in st.session_state:
    st.session_state.selected_chat_id = None

if "search_q" not in st.session_state:
    st.session_state.search_q = ""

# ---------- Helper functions ----------

def short_title_from_text(text: str, length=34):
    t = (text or "").strip()
    if not t:
        return "New Chat"
    return (t[:length] + "…") if len(t) > length else t


# if "upload_toggle" not in st.session_state:
#     st.session_state.upload_toggle = False


if st.session_state.page == "chat" and not st.session_state.user:
    st.session_state.page = "login"
    st.rerun()



