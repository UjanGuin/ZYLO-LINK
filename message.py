import os
import random
import string
import sqlite3
import datetime
import mimetypes
import eventlet
from werkzeug.utils import secure_filename

# Patch for async support ensures real-time performance
eventlet.monkey_patch()
from flask import Flask, render_template_string, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room

# Try importing OpenAI for Groq (Graceful fallback if not installed, though required for AI)
try:
    from openai import OpenAI
    AI_AVAILABLE = True
except ImportError:
    print("Warning: 'openai' library not found. AI features will not work.")
    AI_AVAILABLE = False

# ---------------------------
# Configuration & Setup
# ---------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'ultra-secret-premium-key-999'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max limit

# Ensure upload directory exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# SocketIO with cors allowed for all
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ---------------------------
# AI Configuration
# ---------------------------
GROQ_DEFAULT_KEY = "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"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
AI_MODEL = "llama-3.1-8b-instant"
AI_BOT_ID = "AI_ASSISTANT"
AI_BOT_NAME = "Assistant"
AI_AVATAR_URL = "https://img.icons8.com/fluency/96/bot.png" # Robotic profile pic

# ---------------------------
# Database Management (SQLite)
# ---------------------------
DB_FILE = 'ZYLO_chat.db'

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id TEXT PRIMARY KEY, username TEXT, password TEXT, avatar_url TEXT,
                      ai_usage INTEGER DEFAULT 0, groq_key TEXT)''')
        # Chats mapping
        c.execute('''CREATE TABLE IF NOT EXISTS chat_participants
                     (room_id TEXT, user_id TEXT, chat_name TEXT, 
                      PRIMARY KEY (room_id, user_id))''')
        # Messages table
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, 
                      sender_id TEXT, msg_type TEXT, content TEXT, filename TEXT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      status TEXT DEFAULT 'sent')''')
        
        # Migrations for existing DBs
        try:
            c.execute("SELECT status FROM messages LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE messages ADD COLUMN status TEXT DEFAULT 'sent'")
        
        try:
            c.execute("SELECT ai_usage FROM users LIMIT 1")
        except sqlite3.OperationalError:
            print("Migrating DB: Adding AI columns...")
            c.execute("ALTER TABLE users ADD COLUMN ai_usage INTEGER DEFAULT 0")
            c.execute("ALTER TABLE users ADD COLUMN groq_key TEXT")

        conn.commit()

init_db()

# ---------------------------
# Helper Functions
# ---------------------------
def generate_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

def get_unique_room_id(user1, user2):
    return "_".join(sorted([user1, user2]))

def get_ai_response(prompt, api_key):
    if not AI_AVAILABLE:
        return "Error: Server missing 'openai' library."
    try:
        client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant in a group chat. Keep answers concise."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1024
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Error: {str(e)}"

# ---------------------------
# HTML/CSS/JS Frontend (Embedded)
# ---------------------------
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>ZYLO^LINK</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.5.13/cropper.min.css">
    <style>
        :root {
            --glass-bg: rgba(255, 255, 255, 0.15);
            --glass-border: 1px solid rgba(255, 255, 255, 0.18);
            --glass-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
            --accent-color: #00f2ff;
            --accent-hover: #00c8d4;
            --danger-color: #ff4757;
            --text-color: #ffffff;
            --msg-sent-bg: rgba(0, 242, 255, 0.25);
            --msg-recv-bg: rgba(255, 255, 255, 0.1);
        }

        * { box-sizing: border-box; }

        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(45deg, #1a1a2e, #16213e, #0f3460);
            background-size: 400% 400%;
            animation: gradientBG 15s ease infinite;
            margin: 0;
            padding: 0;
            height: 100dvh;
            width: 100vw;
            overflow: hidden;
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
        }

        @keyframes gradientBG {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        /* --- Auth Screen --- */
        #auth-screen {
            position: absolute; width: 100%; height: 100%;
            background: rgba(0,0,0,0.4); backdrop-filter: blur(20px);
            z-index: 2000; display: flex; justify-content: center; align-items: center;
        }

        .auth-card {
            background: rgba(255, 255, 255, 0.1);
            padding: 40px; border-radius: 20px;
            border: var(--glass-border);
            box-shadow: var(--glass-shadow);
            text-align: center; width: 90%; max-width: 400px;
        }

        .glass-input {
            width: 100%; padding: 15px; margin: 10px 0;
            background: rgba(0,0,0,0.2); border: var(--glass-border);
            border-radius: 10px; color: white; outline: none;
            transition: 0.3s;
        }
        .glass-input:focus { border-color: var(--accent-color); background: rgba(0,0,0,0.4); }

        .glass-btn {
            width: 100%; padding: 15px; margin-top: 10px;
            background: var(--accent-color); border: none;
            border-radius: 10px; color: #000; font-weight: 600;
            cursor: pointer; transition: 0.3s;
        }
        .glass-btn:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0, 242, 255, 0.3); }

        /* --- Main App Container --- */
        #app-container {
            width: 95vw; height: 95dvh;
            background: var(--glass-bg);
            border: var(--glass-border);
            border-radius: 24px;
            backdrop-filter: blur(20px);
            box-shadow: var(--glass-shadow);
            display: flex; overflow: hidden;
            opacity: 0; transition: opacity 0.5s ease;
        }

        /* --- Sidebar --- */
        #sidebar {
            width: 320px; border-right: var(--glass-border);
            display: flex; flex-direction: column;
            background: rgba(0,0,0,0.2);
            transition: transform 0.3s ease;
            z-index: 10;
        }

        .profile-section {
            padding: 20px; text-align: center;
            border-bottom: var(--glass-border);
        }

        .avatar-container {
            width: 80px; height: 80px; margin: 0 auto 10px;
            border-radius: 50%; overflow: hidden;
            border: 2px solid var(--accent-color);
            position: relative; cursor: pointer;
        }
        
        .avatar-container img { width: 100%; height: 100%; object-fit: cover; }
        
        .avatar-overlay {
            position: absolute; top:0; left:0; width:100%; height:100%;
            background: rgba(0,0,0,0.5); opacity: 0;
            display: flex; justify-content: center; align-items: center;
            transition: 0.3s;
        }
        .avatar-container:hover .avatar-overlay { opacity: 1; }

        .user-id-pill {
            background: rgba(0,0,0,0.3); padding: 5px 12px;
            border-radius: 15px; font-size: 0.8rem;
            display: inline-flex; align-items: center; gap: 5px;
            cursor: pointer; margin-top: 5px;
        }
        .user-id-pill:active { background: var(--accent-color); color: black; }

        .chat-list {
            list-style: none; padding: 0; margin: 0;
            overflow-y: auto; flex: 1;
        }

        .chat-item {
            padding: 15px 20px; cursor: pointer;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            display: flex; align-items: center; gap: 15px;
            transition: 0.2s;
        }
        .chat-item:hover { background: rgba(255,255,255,0.05); }
        .chat-item.active { background: rgba(0, 242, 255, 0.1); border-left: 3px solid var(--accent-color); }

        .chat-avatar-small {
            width: 40px; height: 40px; border-radius: 50%;
            background: #333; overflow: hidden;
            display: flex; justify-content: center; align-items: center;
        }
        .chat-avatar-small img { width: 100%; height: 100%; object-fit: cover; }

        /* --- Chat Area --- */
        #chat-area {
            flex: 1; display: flex; flex-direction: column;
            position: relative; background: rgba(0,0,0,0.05);
            z-index: 5;
        }

        .chat-header {
            padding: 15px 20px; border-bottom: var(--glass-border);
            display: flex; align-items: center; gap: 15px;
            background: rgba(0,0,0,0.1);
            height: 70px;
        }

        .back-btn { display: none; font-size: 1.2rem; cursor: pointer; padding: 10px; }

        .header-actions {
            margin-left: auto;
            display: flex;
            gap: 15px;
            align-items: center;
        }

        .icon-btn {
            opacity: 0.6; cursor: pointer; transition: 0.2s;
            font-size: 1.1rem;
        }
        .icon-btn:hover { opacity: 1; color: var(--accent-color); }
        .icon-btn.delete:hover { color: var(--danger-color); }

        #messages {
            flex: 1; padding: 20px; overflow-y: auto;
            display: flex; flex-direction: column; gap: 15px;
            scroll-behavior: smooth;
        }

        .message {
            max-width: 75%; padding: 12px 16px; border-radius: 18px;
            position: relative; font-size: 0.95rem; line-height: 1.5;
            word-wrap: break-word; animation: popIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            display: flex; flex-direction: column;
        }
        
        .message-row {
            display: flex; gap: 10px; align-items: flex-end; margin-bottom: 5px;
        }
        .message-row.sent { flex-direction: row-reverse; }

        .message-row.system {
            justify-content: center;
            margin: 15px 0;
            width: 100%;
        }
        .message.system {
            background: transparent;
            border: none;
            color: rgba(255,255,255,0.5);
            font-size: 0.8rem;
            text-align: center;
            max-width: 100%;
            padding: 0;
            font-style: italic;
        }

        .msg-avatar {
            width: 30px; height: 30px; border-radius: 50%;
            overflow: hidden; flex-shrink: 0;
        }
        .msg-avatar img { width: 100%; height: 100%; object-fit: cover; }

        .message.sent {
            background: var(--msg-sent-bg);
            border-bottom-right-radius: 4px;
            margin-left: auto;
            border: 1px solid rgba(0, 242, 255, 0.2);
        }

        .message.received {
            background: var(--msg-recv-bg);
            border-bottom-left-radius: 4px;
            margin-right: auto;
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        /* AI Message Style */
        .message.ai-msg {
            border: 1px solid rgba(0, 242, 255, 0.6);
            box-shadow: 0 0 10px rgba(0, 242, 255, 0.2);
        }

        .msg-info {
            display: flex; align-items: center; justify-content: flex-end;
            gap: 5px; margin-top: 5px;
            font-size: 0.65rem; opacity: 0.7;
        }
        .ticks { font-size: 0.7rem; color: rgba(255,255,255,0.5); }
        .ticks.read { color: #00f2ff; }

        .msg-media {
            max-width: 100%; border-radius: 10px; margin-top: 8px;
            border: 1px solid rgba(255,255,255,0.2);
            max-height: 300px; object-fit: contain;
        }

        .file-card {
            display: flex; align-items: center; gap: 10px;
            background: rgba(0,0,0,0.2); padding: 10px;
            border-radius: 10px; margin-top: 5px;
            text-decoration: none; color: white;
            border: 1px solid rgba(255,255,255,0.1);
            transition: 0.2s;
        }
        .file-card:hover { background: rgba(0,0,0,0.4); }

        /* --- Input Area --- */
        .chat-input-area {
            padding: 15px; border-top: var(--glass-border);
            display: flex; flex-direction: column; gap: 10px;
            background: rgba(0,0,0,0.2);
            position: relative;
        }

        .input-row {
            display: flex; align-items: center; gap: 10px; width: 100%;
        }

        .circle-btn {
            width: 45px; height: 45px; border-radius: 50%;
            border: none; background: rgba(255,255,255,0.1);
            color: white; font-size: 1.1rem; cursor: pointer;
            display: flex; justify-content: center; align-items: center;
            transition: 0.2s; flex-shrink: 0;
        }
        .circle-btn:hover { background: rgba(255,255,255,0.2); color: var(--accent-color); }
        .circle-btn.send { background: var(--accent-color); color: #000; }
        .circle-btn.send:hover { background: var(--accent-hover); transform: scale(1.05); }

        #msg-input {
            flex: 1; padding: 12px 20px; border-radius: 25px;
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.2); color: white;
            outline: none; font-size: 1rem;
        }
        #msg-input:focus { border-color: var(--accent-color); background: rgba(0,0,0,0.3); }

        /* Mention Popup */
        #mention-popup {
            position: absolute;
            bottom: 80px; left: 60px;
            background: rgba(20, 20, 40, 0.95);
            backdrop-filter: blur(10px);
            border: 1px solid var(--accent-color);
            border-radius: 10px;
            width: 200px;
            max-height: 200px;
            overflow-y: auto;
            display: none;
            flex-direction: column;
            z-index: 100;
            box-shadow: 0 5px 15px rgba(0,0,0,0.5);
        }
        
        .mention-item {
            padding: 10px 15px;
            cursor: pointer;
            display: flex; align-items: center; gap: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            font-size: 0.9rem;
        }
        .mention-item:hover { background: rgba(0, 242, 255, 0.2); }
        .mention-item img { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; }
        .mention-item.assistant { color: var(--accent-color); font-weight: bold; }

        /* Attachment Preview Chip */
        .attachment-preview {
            display: none;
            align-items: center;
            gap: 10px;
            background: rgba(0, 242, 255, 0.15);
            padding: 8px 15px;
            border-radius: 15px;
            font-size: 0.9rem;
            width: fit-content;
            border: 1px solid var(--accent-color);
            animation: popIn 0.3s ease;
        }
        .attachment-preview i.fa-times {
            cursor: pointer; opacity: 0.7; transition: 0.2s;
        }
        .attachment-preview i.fa-times:hover { opacity: 1; color: var(--danger-color); }

        /* Progress Bar */
        .upload-progress-container {
            width: 100%; height: 4px; background: rgba(255,255,255,0.1);
            border-radius: 2px; overflow: hidden; display: none;
            margin-top: -5px; margin-bottom: 5px;
        }
        .upload-progress-bar { width: 0%; height: 100%; background: var(--accent-color); transition: width 0.2s; }

        @keyframes popIn { from { opacity: 0; transform: scale(0.9); } to { opacity: 1; transform: scale(1); } }

        @media (max-width: 768px) {
            #app-container { width: 100vw; height: 100dvh; border-radius: 0; border: none; }
            #sidebar { width: 100%; height: 100%; position: absolute; z-index: 20; background: linear-gradient(135deg, rgba(20, 20, 40, 0.95), rgba(30, 30, 60, 0.98)); backdrop-filter: blur(20px); }
            #sidebar.hidden { display: none; }
            #chat-area { width: 100%; height: 100%; position: absolute; z-index: 10; }
            #chat-area.hidden { display: none; }
            .back-btn { display: block; }
        }

        /* --- Dialogs --- */
        .dialog-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.8); z-index: 3000;
            display: none; justify-content: center; align-items: center;
            backdrop-filter: blur(5px);
        }
        .dialog-active { display: flex; }

        .cropper-container-box { max-height: 60vh; max-width: 90vw; overflow: hidden; background: #000; }
        #cropper-image { display: block; max-width: 100%; }

    </style>
</head>
<body>

    <!-- Auth -->
    <div id="auth-screen">
        <div class="auth-card">
            <h1 style="margin:0 0 10px 0; color:white;"><i class="fas fa-layer-group"></i> ZYLO LINK</h1>
            <p style="opacity:0.7; margin-bottom:30px;">Ultra Premium. Private. Secure.</p>
            <input type="text" id="login-name" class="glass-input" placeholder="Your Name" autocomplete="off">
            <input type="password" id="login-pass" class="glass-input" placeholder="Password">
            <button class="glass-btn" onclick="authenticate()">ENTER WORLD</button>
        </div>
    </div>

    <!-- New Chat Dialog -->
    <div id="new-chat-dialog" class="dialog-overlay">
        <div class="auth-card">
            <h3>Start Conversation</h3>
            <p>Enter the 10-character code:</p>
            <input type="text" id="target-id" class="glass-input" placeholder="e.g. X1Y2Z3A4B5" maxlength="10" style="text-transform:uppercase; text-align:center; letter-spacing: 2px;">
            <div style="display:flex; gap:10px;">
                <button class="glass-btn" style="background:rgba(255,255,255,0.2); color:white;" onclick="closeDialog('new-chat-dialog')">Cancel</button>
                <button class="glass-btn" onclick="startNewChat()">Connect</button>
            </div>
        </div>
    </div>

    <!-- Add Member Dialog -->
    <div id="add-member-dialog" class="dialog-overlay">
        <div class="auth-card">
            <h3>Add Member</h3>
            <p>Enter the ID to add to this chat:</p>
            <input type="text" id="add-member-id" class="glass-input" placeholder="e.g. X1Y2Z3A4B5" maxlength="10" style="text-transform:uppercase; text-align:center; letter-spacing: 2px;">
            <div style="display:flex; gap:10px;">
                <button class="glass-btn" style="background:rgba(255,255,255,0.2); color:white;" onclick="closeDialog('add-member-dialog')">Cancel</button>
                <button class="glass-btn" onclick="addMember()">Add User</button>
            </div>
        </div>
    </div>

    <!-- API Key Dialog -->
    <div id="api-key-dialog" class="dialog-overlay">
        <div class="auth-card">
            <h3><i class="fas fa-robot"></i> AI Limit Reached</h3>
            <p>You have used your 5 free AI messages.</p>
            <p style="font-size:0.8rem; opacity:0.8;">To continue using the assistant seamlessly, please enter your Groq API Key.</p>
            <a href="https://console.groq.com/keys" target="_blank" style="color:var(--accent-color); font-size:0.8rem; margin-bottom:10px; display:block;">Get API Key Here <i class="fas fa-external-link-alt"></i></a>
            <input type="text" id="groq-key-input" class="glass-input" placeholder="gsk_..." style="font-size:0.8rem;">
            <div style="display:flex; gap:10px;">
                <button class="glass-btn" style="background:rgba(255,255,255,0.2); color:white;" onclick="closeDialog('api-key-dialog')">Cancel</button>
                <button class="glass-btn" onclick="saveApiKey()">Save & Continue</button>
            </div>
        </div>
    </div>

    <!-- Cropper Dialog -->
    <div id="cropper-dialog" class="dialog-overlay">
        <div class="auth-card" style="width: 500px; max-width:95vw;">
            <h3>Adjust Profile Picture</h3>
            <div class="cropper-container-box">
                <img id="cropper-image" src="">
            </div>
            <div style="display:flex; gap:10px; margin-top:15px;">
                <button class="glass-btn" style="background:rgba(255,255,255,0.2); color:white;" onclick="cancelCrop()">Cancel</button>
                <button class="glass-btn" onclick="confirmCrop()">Set Avatar</button>
            </div>
        </div>
    </div>

    <!-- App Interface -->
    <div id="app-container">
        
        <!-- Sidebar -->
        <div id="sidebar">
            <div class="profile-section">
                <div class="avatar-container" onclick="document.getElementById('avatar-input').click()">
                    <img id="my-avatar" src="https://ui-avatars.com/api/?name=User&background=random" alt="Profile">
                    <div class="avatar-overlay"><i class="fas fa-camera"></i></div>
                </div>
                <input type="file" id="avatar-input" hidden accept="image/*" onchange="initCrop(this)">
                
                <h3 id="display-name" style="margin: 5px 0;">User</h3>
                <div class="user-id-pill" onclick="copyMyID()">
                    <span id="my-id-code">LOADING...</span> <i class="fas fa-copy"></i>
                </div>
            </div>

            <div style="padding: 15px; display:flex; justify-content:space-between; align-items:center; opacity:0.7; font-size:0.8rem;">
                <span>MESSAGES</span>
                <i class="fas fa-plus-circle" style="font-size:1.2rem; cursor:pointer;" onclick="openDialog('new-chat-dialog')"></i>
            </div>

            <ul id="chat-list" class="chat-list"></ul>
        </div>

        <!-- Chat Window -->
        <div id="chat-area">
            <div id="empty-state" style="height:100%; display:flex; flex-direction:column; justify-content:center; align-items:center; opacity:0.5;">
                <i class="fas fa-comments" style="font-size:4rem; margin-bottom:20px;"></i>
                <h2>Select a conversation</h2>
            </div>

            <div id="active-chat" style="display:none; flex-direction:column; height:100%;">
                <div class="chat-header">
                    <i class="fas fa-arrow-left back-btn" onclick="showSidebar()"></i>
                    <div class="chat-avatar-small">
                        <img id="current-chat-avatar" src="">
                    </div>
                    <div>
                        <div id="current-chat-name" style="font-weight:600;">Chat Name</div>
                        <div style="font-size:0.75rem; opacity:0.7; display:flex; align-items:center; gap:5px;">
                            <span id="connection-status" style="color:#00ff88;">Connected</span>
                        </div>
                    </div>
                    <div class="header-actions">
                        <i class="fas fa-user-plus icon-btn" title="Add Member" onclick="openDialog('add-member-dialog')"></i>
                        <i class="fas fa-pen icon-btn" title="Rename Chat" onclick="renameChat()"></i>
                        <i class="fas fa-trash icon-btn delete" title="Delete Chat" onclick="deleteChat()"></i>
                    </div>
                </div>

                <div id="messages"></div>

                <form id="msg-form" class="chat-input-area">
                    <!-- Progress Bar -->
                    <div id="upload-progress-container" class="upload-progress-container">
                        <div id="upload-progress-bar" class="upload-progress-bar"></div>
                    </div>

                    <!-- Attachment Preview -->
                    <div id="attachment-preview" class="attachment-preview">
                        <i class="fas fa-paperclip"></i>
                        <span id="attachment-name" style="max-width: 200px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;">filename.png</span>
                        <i class="fas fa-times" onclick="clearAttachment()"></i>
                    </div>

                    <!-- Mention Popup -->
                    <div id="mention-popup"></div>

                    <div class="input-row">
                        <input type="file" id="file-input" hidden>
                        <button type="button" class="circle-btn" onclick="document.getElementById('file-input').click()">
                            <i class="fas fa-paperclip"></i>
                        </button>
                        <input type="text" id="msg-input" placeholder="Type @ for Assistant..." autocomplete="off">
                        <button type="submit" class="circle-btn send">
                            <i class="fas fa-paper-plane"></i>
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Scripts -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.5.13/cropper.min.js"></script>
    <script>
        const socket = io({reconnection: true});
        let currentUser = null;
        let currentRoom = null;
        let roomAvatars = {}; 
        let currentRoomUsers = [];
        let pendingAttachment = null;
        let cropper = null;

        // --- AUTHENTICATION ---
        async function authenticate() {
            const name = document.getElementById('login-name').value;
            const pass = document.getElementById('login-pass').value;
            if(!name || !pass) return alert("Please fill in fields");

            try {
                const res = await fetch('/auth', {
                    method:'POST', 
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({name, pass})
                });
                const data = await res.json();
                
                if(data.success) {
                    currentUser = data.user;
                    setupUI();
                } else {
                    alert(data.message);
                }
            } catch(e) { console.error(e); }
        }

        function setupUI() {
            document.getElementById('auth-screen').style.display = 'none';
            document.getElementById('app-container').style.opacity = '1';
            
            document.getElementById('display-name').innerText = currentUser.name;
            document.getElementById('my-id-code').innerText = currentUser.id;
            
            const initialAvatar = currentUser.avatar ? 
                (currentUser.avatar + '?t=' + new Date().getTime()) : 
                `https://ui-avatars.com/api/?name=${currentUser.name}&background=random`;
            
            updateMyAvatar(initialAvatar);

            socket.emit('login', {user_id: currentUser.id});
            loadChats();
        }

        function updateMyAvatar(url) {
            document.getElementById('my-avatar').src = url;
        }

        // --- MENTION SYSTEM ---
        const msgInput = document.getElementById('msg-input');
        const mentionPopup = document.getElementById('mention-popup');
        
        msgInput.addEventListener('keyup', (e) => {
            const val = msgInput.value;
            const lastChar = val.slice(-1);
            
            if (lastChar === '@' || (val.includes('@') && !val.includes(' '))) {
                // Determine search query after @
                const parts = val.split('@');
                const query = parts[parts.length - 1].toLowerCase();
                showMentionPopup(query);
            } else {
                mentionPopup.style.display = 'none';
            }
        });

        function showMentionPopup(query) {
            mentionPopup.innerHTML = '';
            let hasMatch = false;

            // Add Assistant option
            if ('assistant'.includes(query)) {
                const div = document.createElement('div');
                div.className = 'mention-item assistant';
                div.innerHTML = `
                    <img src="https://img.icons8.com/fluency/96/bot.png">
                    <span>Assistant</span>
                `;
                div.onclick = () => insertMention('Assistant');
                mentionPopup.appendChild(div);
                hasMatch = true;
            }

            // Add Users
            currentRoomUsers.forEach(user => {
                if(user.id !== currentUser.id && user.name.toLowerCase().includes(query)) {
                    const div = document.createElement('div');
                    div.className = 'mention-item';
                    div.innerHTML = `
                        <img src="${user.avatar || 'https://ui-avatars.com/api/?name='+user.name}">
                        <span>${user.name}</span>
                    `;
                    div.onclick = () => insertMention(user.name);
                    mentionPopup.appendChild(div);
                    hasMatch = true;
                }
            });

            if (hasMatch) {
                mentionPopup.style.display = 'flex';
            } else {
                mentionPopup.style.display = 'none';
            }
        }

        function insertMention(name) {
            const val = msgInput.value;
            const lastAtIndex = val.lastIndexOf('@');
            const newVal = val.substring(0, lastAtIndex) + '@' + name + ' ';
            msgInput.value = newVal;
            mentionPopup.style.display = 'none';
            msgInput.focus();
        }

        // --- API KEY HANDLING ---
        socket.on('ai_limit_reached', () => {
            openDialog('api-key-dialog');
        });

        function saveApiKey() {
            const key = document.getElementById('groq-key-input').value.trim();
            if(!key) return alert("Please enter a valid key.");
            
            socket.emit('save_api_key', {user_id: currentUser.id, key: key});
            closeDialog('api-key-dialog');
            alert("Key saved! Please resend your message.");
        }

        // --- CROPPER & AVATAR UPLOAD ---
        function initCrop(input) {
            if (input.files && input.files[0]) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    const image = document.getElementById('cropper-image');
                    image.src = e.target.result;
                    document.getElementById('cropper-dialog').classList.add('dialog-active');
                    if(cropper) cropper.destroy();
                    cropper = new Cropper(image, { aspectRatio: 1, viewMode: 1, minContainerWidth: 300, minContainerHeight: 300 });
                }
                reader.readAsDataURL(input.files[0]);
            }
        }

        function cancelCrop() {
            document.getElementById('cropper-dialog').classList.remove('dialog-active');
            document.getElementById('avatar-input').value = '';
            if(cropper) cropper.destroy();
        }

        function confirmCrop() {
            if(!cropper) return;
            cropper.getCroppedCanvas({ width: 300, height: 300 }).toBlob((blob) => { uploadAvatarBlob(blob); });
            cancelCrop();
        }

        async function uploadAvatarBlob(blob) {
            const formData = new FormData();
            formData.append('file', blob, 'avatar.png');
            formData.append('user_id', currentUser.id);
            try {
                const res = await fetch('/upload_avatar', {method:'POST', body:formData});
                const data = await res.json();
                if(data.url) {
                    const newUrl = data.url + '?t=' + new Date().getTime();
                    currentUser.avatar = newUrl;
                    updateMyAvatar(newUrl);
                    socket.emit('avatar_update', { user_id: currentUser.id, avatar: newUrl });
                }
            } catch(e) { alert("Avatar upload failed"); }
        }

        // --- NAVIGATION ---
        function showChat(roomId) {
            if(window.innerWidth <= 768) {
                document.getElementById('sidebar').classList.add('hidden');
                document.getElementById('chat-area').classList.remove('hidden');
            }
        }
        function showSidebar() {
            if(window.innerWidth <= 768) {
                document.getElementById('sidebar').classList.remove('hidden');
                document.getElementById('chat-area').classList.add('hidden');
            }
            currentRoom = null; 
            document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
        }

        // --- CHAT LOGIC ---
        function openDialog(id) { document.getElementById(id).classList.add('dialog-active'); }
        function closeDialog(id) { document.getElementById(id).classList.remove('dialog-active'); }

        function copyMyID() {
            navigator.clipboard.writeText(currentUser.id);
            alert("ID Copied: " + currentUser.id);
        }

        async function startNewChat() {
            const targetId = document.getElementById('target-id').value.trim().toUpperCase();
            if(targetId === currentUser.id) return alert("Cannot chat with yourself.");
            socket.emit('create_chat', {my_id: currentUser.id, target_id: targetId});
            closeDialog('new-chat-dialog');
        }
        
        async function addMember() {
            const targetId = document.getElementById('add-member-id').value.trim().toUpperCase();
            if(!targetId) return;
            if(!currentRoom) return alert("No chat selected");
            socket.emit('add_member', { room_id: currentRoom, user_id: currentUser.id, target_id: targetId });
            closeDialog('add-member-dialog');
            document.getElementById('add-member-id').value = '';
        }

        // Socket Listeners
        socket.on('error', (data) => alert(data.message));
        socket.on('chat_added', () => loadChats());
        socket.on('chat_created', (data) => {
            if(data.success) {
                loadChats(); 
                enterRoom(data.room_id, data.chat_name, null);
            } else {
                alert(data.message);
            }
        });

        socket.on('chat_deleted', (data) => {
            loadChats();
            if (currentRoom === data.room_id) {
                showSidebar();
                document.getElementById('active-chat').style.display = 'none';
                document.getElementById('empty-state').style.display = 'flex';
            }
        });

        socket.on('user_avatar_updated', (data) => {
            document.querySelectorAll(`.msg-avatar-img-${data.user_id}`).forEach(img => img.src = data.avatar);
            loadChats();
        });

        socket.on('messages_read', (data) => {
            if(currentRoom === data.room_id) {
                document.querySelectorAll('.ticks').forEach(el => el.classList.add('read'));
            }
        });
        
        socket.on('room_users', (users) => {
            currentRoomUsers = users;
        });

        function loadChats() { socket.emit('get_chats', {user_id: currentUser.id}); }

        socket.on('chat_list', (chats) => {
            const list = document.getElementById('chat-list');
            list.innerHTML = '';
            if(chats.length === 0) {
                 list.innerHTML = '<li style="padding:20px; text-align:center; opacity:0.5;">No chats yet. Click + to start.</li>';
                 return;
            }
            chats.forEach(chat => {
                const li = document.createElement('li');
                li.className = `chat-item ${currentRoom === chat.room_id ? 'active' : ''}`;
                li.dataset.roomId = chat.room_id; 
                let avatarUrl = chat.other_avatar || `https://ui-avatars.com/api/?name=${chat.chat_name}&background=random`;
                if(chat.other_avatar && !avatarUrl.includes('?')) avatarUrl += '?t=' + new Date().getTime();
                roomAvatars[chat.room_id] = avatarUrl;

                li.innerHTML = `
                    <div class="chat-avatar-small"><img src="${avatarUrl}" id="avatar-room-${chat.room_id}"></div>
                    <div style="flex:1;">
                        <div style="font-weight:600;">${chat.chat_name}</div>
                        <div style="font-size:0.8rem; opacity:0.6;">Tap to chat</div>
                    </div>
                `;
                li.onclick = () => enterRoom(chat.room_id, chat.chat_name, avatarUrl);
                list.appendChild(li);
            });
        });

        function enterRoom(roomId, name, avatarUrl) {
            currentRoom = roomId;
            clearAttachment(); 
            document.getElementById('empty-state').style.display = 'none';
            document.getElementById('active-chat').style.display = 'flex';
            document.getElementById('current-chat-name').innerText = name;
            let finalAvatar = avatarUrl || roomAvatars[roomId] || `https://ui-avatars.com/api/?name=${name}`;
            document.getElementById('current-chat-avatar').src = finalAvatar;
            document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
            const activeItem = document.querySelector(`.chat-item[data-room-id="${roomId}"]`);
            if(activeItem) activeItem.classList.add('active');
            showChat(); 
            socket.emit('join_room', {room_id: roomId, user_id: currentUser.id});
        }

        socket.on('history', (messages) => {
            const container = document.getElementById('messages');
            container.innerHTML = '';
            messages.forEach(msg => appendMessage(msg));
            container.scrollTop = container.scrollHeight;
        });

        socket.on('message', (msg) => {
            if(currentRoom === msg.room_id) {
                appendMessage(msg);
                const container = document.getElementById('messages');
                container.scrollTop = container.scrollHeight;
                if(msg.sender_id !== currentUser.id) {
                    socket.emit('mark_read', {room_id: currentRoom, user_id: currentUser.id});
                }
            }
        });

        function appendMessage(msg) {
            const isMe = msg.sender_id === currentUser.id;
            const isAI = msg.sender_id === 'AI_ASSISTANT';
            const container = document.getElementById('messages');
            
            if(msg.type === 'system') {
                 const row = document.createElement('div');
                 row.className = 'message-row system';
                 row.innerHTML = `<div class="message system">${msg.content}</div>`;
                 container.appendChild(row);
                 return;
            }
            
            const row = document.createElement('div');
            row.className = `message-row ${isMe ? 'sent' : ''}`;
            
            let avatarSrc;
            if (isMe) {
                avatarSrc = currentUser.avatar || `https://ui-avatars.com/api/?name=${currentUser.name}`;
            } else if (isAI) {
                avatarSrc = "https://img.icons8.com/fluency/96/bot.png";
            } else {
                avatarSrc = roomAvatars[currentRoom] || `https://ui-avatars.com/api/?name=User`;
            }

            const avatarDiv = document.createElement('div');
            avatarDiv.className = 'msg-avatar';
            avatarDiv.innerHTML = `<img src="${avatarSrc}" class="msg-avatar-img-${msg.sender_id}">`;
            
            const msgBubble = document.createElement('div');
            msgBubble.className = `message ${isMe ? 'sent' : (isAI ? 'received ai-msg' : 'received')}`;
            
            let contentHtml = '';
            if (msg.type === 'text') {
                contentHtml = `<div>${escapeHtml(msg.content)}</div>`;
            } else if (msg.type.startsWith('image')) {
                contentHtml = `<img src="${msg.content}" class="msg-media" onclick="window.open(this.src)">`;
            } else {
                const fname = msg.filename || "Attachment";
                contentHtml = `
                    <a href="${msg.content}" target="_blank" class="file-card" download>
                        <i class="fas fa-file-alt" style="font-size:1.5rem;"></i>
                        <div><div style="font-weight:600;">${fname}</div></div>
                    </a>`;
            }
            
            const ticks = isMe ? `<span class="ticks ${msg.status === 'read' ? 'read' : ''}"><i class="fas fa-check-double"></i></span>` : '';
            msgBubble.innerHTML = contentHtml + `<div class="msg-info"><span>${msg.time}</span>${ticks}</div>`;
            
            row.appendChild(avatarDiv);
            row.appendChild(msgBubble);
            container.appendChild(row);
        }

        // --- SENDING LOGIC ---
        document.getElementById('msg-form').addEventListener('submit', (e) => {
            e.preventDefault();
            const input = document.getElementById('msg-input');
            const text = input.value.trim();
            if (!currentRoom) return;
            const attachmentToSend = pendingAttachment;
            pendingAttachment = null; 
            document.getElementById('attachment-preview').style.display = 'none';
            document.getElementById('file-input').value = '';

            if (attachmentToSend) {
                socket.emit('send_message', {
                    room_id: currentRoom, sender_id: currentUser.id,
                    type: attachmentToSend.type, content: attachmentToSend.url, filename: attachmentToSend.filename
                });
            }

            if(text) {
                setTimeout(() => {
                    socket.emit('send_message', {
                        room_id: currentRoom, sender_id: currentUser.id,
                        type: 'text', content: text
                    });
                }, attachmentToSend ? 150 : 0);
                input.value = '';
            }
            mentionPopup.style.display = 'none';
        });

        // --- FILE UPLOAD ---
        const fileInput = document.getElementById('file-input');
        fileInput.addEventListener('change', function() { if (this.files[0]) uploadFile(this.files[0]); });

        function uploadFile(file) {
            const formData = new FormData();
            formData.append('file', file);
            const xhr = new XMLHttpRequest();
            const progressBar = document.getElementById('upload-progress-bar');
            const progressContainer = document.getElementById('upload-progress-container');

            progressContainer.style.display = 'block';
            progressBar.style.width = '0%';

            xhr.open('POST', '/upload', true);
            xhr.upload.onprogress = function(e) { if (e.lengthComputable) progressBar.style.width = ((e.loaded / e.total) * 100) + '%'; };
            xhr.onload = function() {
                progressContainer.style.display = 'none';
                if (xhr.status === 200) {
                    const data = JSON.parse(xhr.responseText);
                    if (data.url) {
                        pendingAttachment = { url: data.url, type: data.type, filename: file.name };
                        showAttachmentPreview(file.name);
                    }
                } else alert('Upload failed.');
                fileInput.value = ''; 
            };
            xhr.send(formData);
        }

        function showAttachmentPreview(name) {
            document.getElementById('attachment-preview').style.display = 'flex';
            document.getElementById('attachment-name').innerText = name;
            document.getElementById('msg-input').focus();
        }

        function clearAttachment() {
            pendingAttachment = null;
            document.getElementById('attachment-preview').style.display = 'none';
            document.getElementById('file-input').value = '';
        }

        function renameChat() {
            const newName = prompt("Rename this chat:");
            if(newName && currentRoom) {
                socket.emit('rename_chat', {room_id: currentRoom, user_id: currentUser.id, new_name: newName});
                document.getElementById('current-chat-name').innerText = newName;
                setTimeout(loadChats, 500);
            }
        }

        function deleteChat() {
            if(!currentRoom) return;
            if(confirm("Delete chat?")) socket.emit('delete_chat', {room_id: currentRoom, user_id: currentUser.id});
        }

        function escapeHtml(text) {
            if (!text) return "";
            return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }
    </script>
</body>
</html>
"""

# ---------------------------
# Flask Routes
# ---------------------------
@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/auth', methods=['POST'])
def auth():
    data = request.json
    name = data.get('name')
    password = data.get('pass')
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (name, password))
        user = c.fetchone()
        
        if user:
            return jsonify({'success': True, 'user': {'id': user['user_id'], 'name': user['username'], 'avatar': user['avatar_url']}})
        else:
            new_id = generate_id()
            c.execute("INSERT INTO users (user_id, username, password) VALUES (?, ?, ?)", (new_id, name, password))
            conn.commit()
            return jsonify({'success': True, 'user': {'id': new_id, 'name': name, 'avatar': None}})

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'file' not in request.files: return jsonify({'error': 'No file'})
    file = request.files['file']
    user_id = request.form.get('user_id')
    
    if file and user_id:
        fname = secure_filename(f"avatar_{user_id}_{int(datetime.datetime.now().timestamp())}.png")
        path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        file.save(path)
        url = f"/uploads/{fname}"
        
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("UPDATE users SET avatar_url=? WHERE user_id=?", (url, user_id))
            
        return jsonify({'url': url})
    return jsonify({'error': 'Failed'})

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return jsonify({'error': 'No file'})
    file = request.files['file']
    
    if file:
        fname = secure_filename(f"{int(datetime.datetime.now().timestamp())}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        
        mime_type, _ = mimetypes.guess_type(fname)
        if not mime_type: mime_type = 'application/octet-stream'
        if fname.endswith('.py'): mime_type = 'text/x-python'
        
        return jsonify({'url': f"/uploads/{fname}", 'type': mime_type})
    return jsonify({'error': 'Failed'})

@app.route('/uploads/<filename>')
def serve_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ---------------------------
# SocketIO Logic
# ---------------------------
@socketio.on('login')
def on_login(data):
    join_room(data['user_id'])

@socketio.on('create_chat')
def on_create_chat(data):
    my_id = data['my_id']
    target_id = data['target_id']
    
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id=?", (target_id,))
        target = c.fetchone()
        
        if not target:
            emit('chat_created', {'success': False, 'message': 'User ID not found'})
            return

        room_id = get_unique_room_id(my_id, target_id)
        c.execute("SELECT username FROM users WHERE user_id=?", (my_id,))
        my_name = c.fetchone()[0]

        c.execute("INSERT OR IGNORE INTO chat_participants (room_id, user_id, chat_name) VALUES (?, ?, ?)", (room_id, my_id, target[0]))
        c.execute("INSERT OR IGNORE INTO chat_participants (room_id, user_id, chat_name) VALUES (?, ?, ?)", (room_id, target_id, my_name))
        conn.commit()
        
        emit('chat_created', {'success': True, 'room_id': room_id, 'chat_name': target[0]})

@socketio.on('add_member')
def on_add_member(data):
    room_id = data['room_id']
    target_id = data['target_id']
    requester_id = data['user_id']
    
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id=?", (target_id,))
        target_row = c.fetchone()
        if not target_row:
            emit('error', {'message': 'User not found'}) 
            return
        
        target_name = target_row[0]
        c.execute("SELECT 1 FROM chat_participants WHERE room_id=? AND user_id=?", (room_id, target_id))
        if c.fetchone():
            emit('error', {'message': 'User already in chat'})
            return

        c.execute("INSERT INTO chat_participants (room_id, user_id, chat_name) VALUES (?, ?, ?)", 
                  (room_id, target_id, "Group Chat"))
        
        c.execute("SELECT username FROM users WHERE user_id=?", (requester_id,))
        requester_name = c.fetchone()[0]
        sys_msg = f"{requester_name} added {target_name}"
        
        c.execute("INSERT INTO messages (room_id, sender_id, msg_type, content) VALUES (?, ?, ?, ?)",
                  (room_id, 'SYSTEM', 'system', sys_msg))
        conn.commit()

        now = datetime.datetime.now().strftime('%H:%M')
        emit('message', {'sender_id': 'SYSTEM', 'type': 'system', 'content': sys_msg, 'time': now, 'room_id': room_id}, room=room_id)
        emit('chat_added', {'room_id': room_id}, room=target_id)
        emit('success', {'message': 'Member added'})

@socketio.on('get_chats')
def on_get_chats(data):
    user_id = data['user_id']
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = '''
            SELECT cp.room_id, cp.chat_name, 
                   (SELECT u.avatar_url FROM chat_participants cp2 
                    JOIN users u ON cp2.user_id = u.user_id 
                    WHERE cp2.room_id = cp.room_id AND cp2.user_id != ? LIMIT 1) as other_avatar
            FROM chat_participants cp
            WHERE cp.user_id = ?
        '''
        c.execute(query, (user_id, user_id))
        chats = [{'room_id': r['room_id'], 'chat_name': r['chat_name'], 'other_avatar': r['other_avatar']} for r in c.fetchall()]
        emit('chat_list', chats)

def get_room_participants(room_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT u.user_id, u.username, u.avatar_url 
            FROM chat_participants cp
            JOIN users u ON cp.user_id = u.user_id
            WHERE cp.room_id = ?
        """, (room_id,))
        return [{'id': r[0], 'name': r[1], 'avatar': r[2]} for r in c.fetchall()]

@socketio.on('join_room')
def on_join(data):
    room_id = data['room_id']
    user_id = data['user_id']
    join_room(room_id)
    
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("UPDATE messages SET status='read' WHERE room_id=? AND sender_id!=?", (room_id, user_id))
        conn.commit()
        
        emit('messages_read', {'room_id': room_id}, room=room_id)
        
        # Send room participants for Mention logic
        users = get_room_participants(room_id)
        emit('room_users', users, room=user_id) # Only to joiner

        c.execute("SELECT sender_id, msg_type, content, filename, timestamp, status FROM messages WHERE room_id=? ORDER BY id ASC", (room_id,))
        msgs = []
        for r in c.fetchall():
            try:
                dt = datetime.datetime.strptime(r[4], '%Y-%m-%d %H:%M:%S')
                time_str = dt.strftime('%H:%M')
            except:
                time_str = r[4]
            msgs.append({'sender_id': r[0], 'type': r[1], 'content': r[2], 'filename': r[3], 'time': time_str, 'status': r[5]})
            
        emit('history', msgs)

@socketio.on('mark_read')
def on_mark_read(data):
    room_id = data['room_id']
    user_id = data['user_id']
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("UPDATE messages SET status='read' WHERE room_id=? AND sender_id!=?", (room_id, user_id))
        conn.commit()
    emit('messages_read', {'room_id': room_id}, room=room_id)

@socketio.on('save_api_key')
def on_save_key(data):
    user_id = data['user_id']
    key = data['key']
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE users SET groq_key=? WHERE user_id=?", (key, user_id))
        conn.commit()

@socketio.on('send_message')
def on_send(data):
    room_id = data['room_id']
    content = data['content']
    msg_type = data.get('type', 'text')
    fname = data.get('filename', '')
    sender_id = data['sender_id']
    
    if not room_id or not sender_id: return

    # Save User Message
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO messages (room_id, sender_id, msg_type, content, filename, status) VALUES (?, ?, ?, ?, ?, ?)", 
                  (room_id, sender_id, msg_type, content, fname, 'sent'))
        conn.commit()
    
    now = datetime.datetime.now().strftime('%H:%M')
    emit('message', {'sender_id': sender_id, 'type': msg_type, 'content': content, 'filename': fname, 'time': now, 'room_id': room_id, 'status': 'sent'}, room=room_id)

    # --- AI LOGIC ---
    if msg_type == 'text' and content.startswith('@Assistant'):
        prompt = content.replace('@Assistant', '').strip()
        
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT ai_usage, groq_key FROM users WHERE user_id=?", (sender_id,))
            row = c.fetchone()
            usage = row[0] if row[0] else 0
            user_key = row[1]
            
            # Determine which key to use
            active_key = GROQ_DEFAULT_KEY
            if usage >= 5:
                if not user_key:
                    emit('ai_limit_reached', room=sender_id)
                    return
                active_key = user_key
            
            # Increment Usage
            c.execute("UPDATE users SET ai_usage=? WHERE user_id=?", (usage + 1, sender_id))
            conn.commit()

            # Call AI
            eventlet.spawn(handle_ai_response, room_id, prompt, active_key)

def handle_ai_response(room_id, prompt, api_key):
    ai_reply = get_ai_response(prompt, api_key)
    
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO messages (room_id, sender_id, msg_type, content, filename, status) VALUES (?, ?, ?, ?, ?, ?)", 
                  (room_id, AI_BOT_ID, 'text', ai_reply, '', 'sent'))
        conn.commit()

    now = datetime.datetime.now().strftime('%H:%M')
    socketio.emit('message', {'sender_id': AI_BOT_ID, 'type': 'text', 'content': ai_reply, 'filename': '', 'time': now, 'room_id': room_id, 'status': 'sent'}, room=room_id)

@socketio.on('rename_chat')
def on_rename(data):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE chat_participants SET chat_name=? WHERE room_id=? AND user_id=?", 
                     (data['new_name'], data['room_id'], data['user_id']))

@socketio.on('delete_chat')
def on_delete_chat(data):
    room_id = data['room_id']
    user_id = data['user_id']
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM chat_participants WHERE room_id=? AND user_id=?", (room_id, user_id))
        conn.commit()
    emit('chat_deleted', {'room_id': room_id})

@socketio.on('avatar_update')
def on_avatar_update(data):
    emit('user_avatar_updated', data, broadcast=True)

if __name__ == "__main__":
    print("💎 ZYLO^LINK Ultimate Running...")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)

