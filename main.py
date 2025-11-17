import discord
from discord.ext import commands, tasks
import sqlite3
import datetime
from typing import Dict
import re
import os
from flask import Flask, request, jsonify
import logging
import nacl.signing
import nacl.exceptions
from threading import Thread
from quest_system import (
    init_quest_tables, get_all_quests, get_quests_by_type, get_quest_by_id,
    check_and_complete_quests, claim_quest_reward, update_daily_stats,
    update_weekly_stats, QuestType, get_user_quest_progress, reset_daily_quests,
    reset_weekly_quests
)
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO

# Bot version - Update this when making changes
VERSION = "3.0.0"

# Flask app for uptime monitoring
app = Flask('')


@app.route('/')
def home():
    return "Questuza is running!"


@app.route('/welcome')
def welcome():
    logging.info(f"Request received: {request.method} {request.path}")
    return jsonify({'message': 'Welcome to the Flask API Service!'})


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    server = Thread(target=run)
    server.daemon = True
    server.start()


# Start the Flask server
keep_alive()

# Bot configuration
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='%', intents=intents, help_command=None)

# Spam protection settings
SPAM_CHANNEL_ID = 1158615333289086997  # channel where spam is allowed (very reduced XP)
# Track last message per (guild, channel) to detect consecutive duplicates
LAST_USER_MESSAGE = {}  # key: (guild_id, channel_id) -> {'author_id': int, 'content': str}

# Database setup with proper table creation and versioning
def backup_database():
    """Create a backup of the database"""
    from datetime import datetime
    import shutil
    import os

    # Create backups directory if it doesn't exist
    if not os.path.exists('backups'):
        os.makedirs('backups')

    # Create backup with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f'backups/questuza_backup_{timestamp}.db'

    # Copy the database file
    if os.path.exists('questuza.db'):
        shutil.copy2('questuza.db', backup_path)
        print(f"✅ Database backed up to {backup_path}")


def init_db():
    """Initialize database with version control and optimizations"""
    conn = sqlite3.connect('questuza.db', check_same_thread=False)
    c = conn.cursor()

    # Create version tracking table
    c.execute('''CREATE TABLE IF NOT EXISTS db_version 
                 (version INTEGER PRIMARY KEY, 
                  updated_at TEXT)''')

    # Check current version
    c.execute('''SELECT version FROM db_version 
                 ORDER BY version DESC LIMIT 1''')
    result = c.fetchone()
    current_version = result[0] if result else 0

    # Create backup before any schema changes
    backup_database()

    # Create tables if they don't exist (version 1)
    if current_version < 1:
        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER, guild_id INTEGER,
                  unique_words INTEGER DEFAULT 0, vc_seconds INTEGER DEFAULT 0,
                  level INTEGER DEFAULT 0, xp INTEGER DEFAULT 0,
                  messages_sent INTEGER DEFAULT 0, images_sent INTEGER DEFAULT 0,
                  channels_used INTEGER DEFAULT 0, lifetime_words INTEGER DEFAULT 0,
                  quests_completed INTEGER DEFAULT 0, custom_color TEXT DEFAULT "#5865F2",
                  banner_url TEXT, last_trivia_win TEXT, xp_multiplier REAL DEFAULT 1.0,
                  multiplier_expires TEXT, created_at TEXT, autoclaim_enabled INTEGER DEFAULT 0,
                  daily_quests_completed INTEGER DEFAULT 0, weekly_quests_completed INTEGER DEFAULT 0,
                  last_daily_reset TEXT, last_weekly_reset TEXT,
                  PRIMARY KEY (user_id, guild_id))''')

    # User channels table for tracking unique channels
    c.execute('''CREATE TABLE IF NOT EXISTS user_channels
                 (user_id INTEGER, guild_id INTEGER, channel_id INTEGER,
                  PRIMARY KEY (user_id, guild_id, channel_id))''')

    # Quests progress table
    c.execute('''CREATE TABLE IF NOT EXISTS quests_progress
                 (user_id INTEGER, guild_id INTEGER, quest_id TEXT,
                  progress INTEGER DEFAULT 0, completed INTEGER DEFAULT 0,
                  started_at TEXT, completed_at TEXT,
                  PRIMARY KEY (user_id, guild_id, quest_id))''')

    # Active voice sessions - SIMPLIFIED version
    c.execute('''CREATE TABLE IF NOT EXISTS voice_sessions
                 (user_id INTEGER, guild_id INTEGER, channel_id INTEGER,
                  join_time TEXT, leave_time TEXT,
                  PRIMARY KEY (user_id, guild_id, channel_id))''')

    # Guild settings
    c.execute('''CREATE TABLE IF NOT EXISTS guild_settings
                 (guild_id INTEGER PRIMARY KEY, trivia_channel INTEGER,
                  active_trivia TEXT, trivia_answer TEXT, trivia_expires TEXT)'''
              )

    # Version 2: Add performance indexes
    if current_version < 2:
        print("📊 Adding database indexes for performance...")
        
        # Indexes for users table - frequently queried columns
        c.execute('''CREATE INDEX IF NOT EXISTS idx_users_guild 
                     ON users(guild_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_users_level 
                     ON users(guild_id, level DESC)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_users_xp 
                     ON users(guild_id, xp DESC)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_users_words 
                     ON users(guild_id, unique_words DESC)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_users_vc 
                     ON users(guild_id, vc_seconds DESC)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_users_quests 
                     ON users(guild_id, quests_completed DESC)''')
        
        # Indexes for voice sessions - active session queries
        c.execute('''CREATE INDEX IF NOT EXISTS idx_voice_sessions_active 
                     ON voice_sessions(user_id, guild_id, leave_time)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_voice_sessions_cleanup 
                     ON voice_sessions(leave_time, join_time)''')
        
        # Indexes for quests progress
        c.execute('''CREATE INDEX IF NOT EXISTS idx_quests_user 
                     ON quests_progress(user_id, guild_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_quests_completed 
                     ON quests_progress(user_id, guild_id, completed)''')
        
        print("✅ Database indexes created successfully")

    # Version 3: Enable WAL mode for better concurrent access
    if current_version < 3:
        print("🔧 Enabling WAL mode for better performance...")
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=NORMAL')
        c.execute('PRAGMA cache_size=-64000')  # 64MB cache
        c.execute('PRAGMA temp_store=MEMORY')
        print("✅ Database optimization settings applied")

    # Version 4: Add 'claimed' column to quests_progress if missing
    if current_version < 4:
        print("🔧 Adding 'claimed' column to quests_progress table...")
        try:
            c.execute('ALTER TABLE quests_progress ADD COLUMN claimed INTEGER DEFAULT 0')
            print("✅ Successfully added 'claimed' column")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("✅ 'claimed' column already exists, skipping...")
            else:
                raise

    # Version 5: Add auto-claim and quest streak tracking columns
    if current_version < 5:
        print("🔧 Adding auto-claim and quest streak columns...")
        columns_to_add = [
            ('autoclaim_enabled', 'INTEGER DEFAULT 0'),
            ('daily_quests_completed', 'INTEGER DEFAULT 0'),
            ('weekly_quests_completed', 'INTEGER DEFAULT 0'),
            ('last_daily_reset', 'TEXT'),
            ('last_weekly_reset', 'TEXT')
        ]

        for col_name, col_type in columns_to_add:
            try:
                c.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_type}')
                print(f"✅ Added column: {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    print(f"✅ Column {col_name} already exists, skipping...")
                else:
                    raise

    # Version 6: Add trivia system tables and columns
    if current_version < 6:
        print("🎯 Adding trivia system tables and columns...")

        # Add trivia_channel to guild_settings
        try:
            c.execute('ALTER TABLE guild_settings ADD COLUMN trivia_channel INTEGER')
            print("✅ Added trivia_channel column to guild_settings")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("✅ trivia_channel column already exists, skipping...")
            else:
                raise

        # Create trivia_questions table
        c.execute('''CREATE TABLE IF NOT EXISTS trivia_questions
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      question TEXT NOT NULL,
                      answer TEXT NOT NULL,
                      category TEXT DEFAULT 'general',
                      difficulty TEXT DEFAULT 'medium',
                      created_at TEXT)''')
        print("✅ Created trivia_questions table")

        # Create trivia_sessions table
        c.execute('''CREATE TABLE IF NOT EXISTS trivia_sessions
                     (guild_id INTEGER PRIMARY KEY,
                      question_id INTEGER,
                      started_at TEXT,
                      expires_at TEXT,
                      answered_by INTEGER)''')
        print("✅ Created trivia_sessions table")

        # Add trivia_win column to users table
        try:
            c.execute('ALTER TABLE users ADD COLUMN trivia_wins INTEGER DEFAULT 0')
            print("✅ Added trivia_wins column to users")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("✅ trivia_wins column already exists, skipping...")
            else:
                raise

        # Insert sample trivia questions
        sample_questions = [
            ("What is the capital of France?", "paris", "geography", "easy"),
            ("What programming language is this bot written in?", "python", "technology", "easy"),
            ("What year was Discord founded?", "2015", "technology", "medium"),
            ("What is the largest planet in our solar system?", "jupiter", "science", "easy"),
            ("Who painted the Mona Lisa?", "da vinci", "art", "medium"),
            ("What is the chemical symbol for gold?", "au", "science", "medium"),
            ("What is the fastest land animal?", "cheetah", "animals", "easy"),
            ("What is the longest river in the world?", "nile", "geography", "medium"),
            ("What is the square root of 144?", "12", "math", "easy"),
            ("What is the largest ocean on Earth?", "pacific", "geography", "easy"),
            ("Who wrote 'Romeo and Juliet'?", "shakespeare", "literature", "medium"),
            ("What is the currency of Japan?", "yen", "economics", "easy"),
            ("What is the hardest natural substance on Earth?", "diamond", "science", "medium"),
            ("What is the smallest country in the world?", "vatican city", "geography", "hard"),
            ("What is the most spoken language in the world?", "mandarin", "language", "medium")
        ]

        for question, answer, category, difficulty in sample_questions:
            c.execute('''INSERT INTO trivia_questions (question, answer, category, difficulty, created_at)
                         VALUES (?, ?, ?, ?, ?)''',
                      (question, answer, category, difficulty, datetime.datetime.now().isoformat()))

        print("✅ Added sample trivia questions")

    # Version 7: Add profile card fields (about_me and background_url)
    if current_version < 7:
        print("🎨 Adding profile card fields...")
        columns_to_add = [
            ('about_me', 'TEXT'),
            ('background_url', 'TEXT')
        ]

        for col_name, col_type in columns_to_add:
            try:
                c.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_type}')
                print(f"✅ Added column: {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    print(f"✅ Column {col_name} already exists, skipping...")
                else:
                    raise

    # Version 8: Add profile card background color (separate from embed color)
    if current_version < 8:
        print("🎨 Adding profile card background color field...")
        try:
            c.execute('ALTER TABLE users ADD COLUMN profile_card_bg_color TEXT')
            print("✅ Added column: profile_card_bg_color")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("✅ Column profile_card_bg_color already exists, skipping...")
            else:
                raise

    # Version 9: Add profile card customization fields
    if current_version < 9:
        print("🎨 Adding profile card customization fields...")
        columns_to_add = [
            ('banner_brightness', 'REAL DEFAULT 0.0'),  # 0-100% darkness
            ('card_padding', 'REAL DEFAULT 1.2'),  # Multiplier for padding (default 3x = 1.2 inches)
            ('card_font_size', 'REAL DEFAULT 33.0'),  # Font size multiplier
            ('custom_pfp_url', 'TEXT'),  # Custom profile picture URL
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                c.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_type}')
                print(f"✅ Added column: {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    print(f"✅ Column {col_name} already exists, skipping...")
                else:
                    raise

    # Insert/update version info
    version_to_set = 9 if current_version < 9 else (8 if current_version < 8 else 7 if current_version < 7 else current_version)
    c.execute(
        '''INSERT OR REPLACE INTO db_version (version, updated_at)
                 VALUES (?, ?)''', (version_to_set, datetime.datetime.now().isoformat()))

    conn.commit()
    conn.close()
    print("✅ Database initialized/updated successfully")


# Initialize database with safety checks
try:
    init_db()
    init_quest_tables()
    print("✅ Quest system initialized")
except Exception as e:
    print(f"❌ Database initialization error: {e}")
    # Try to restore from most recent backup
    import os
    import glob

    backup_files = glob.glob('backups/questuza_backup_*.db')
    if backup_files:
        latest_backup = max(backup_files, key=os.path.getctime)
        try:
            import shutil
            shutil.copy2(latest_backup, 'questuza.db')
            print(f"✅ Restored from backup: {latest_backup}")
            init_db()  # Try initialization again
        except Exception as restore_error:
            print(f"❌ Backup restoration failed: {restore_error}")
    else:
        print("❌ No backup files found")


# Leveling configuration
class LevelSystem:

    @staticmethod
    def get_level_requirements(level: int) -> Dict:
        requirements = {
            1: {
                "words": 50,
                "vc_minutes": 1,
                "messages": 10,
                "quests": 0
            },
            2: {
                "words": 100,
                "vc_minutes": 2,
                "messages": 20,
                "quests": 0
            },
            3: {
                "words": 200,
                "vc_minutes": 4,
                "messages": 30,
                "quests": 0
            },
            4: {
                "words": 400,
                "vc_minutes": 6,
                "messages": 40,
                "quests": 0
            },
            5: {
                "words": 700,
                "vc_minutes": 8,
                "messages": 50,
                "quests": 0
            },
            6: {
                "words": 1100,
                "vc_minutes": 10,
                "messages": 60,
                "quests": 0
            },
            7: {
                "words": 1600,
                "vc_minutes": 12,
                "messages": 70,
                "quests": 0
            },
            8: {
                "words": 2200,
                "vc_minutes": 15,
                "messages": 80,
                "quests": 0
            },
            9: {
                "words": 2900,
                "vc_minutes": 18,
                "messages": 90,
                "quests": 0
            },
            10: {
                "words": 3700,
                "vc_minutes": 20,
                "messages": 100,
                "quests": 0
            },
            11: {
                "words": 4000,
                "vc_minutes": 22,
                "messages": 120,
                "quests": 1
            },
            12: {
                "words": 4300,
                "vc_minutes": 24,
                "messages": 140,
                "quests": 1
            },
            13: {
                "words": 4600,
                "vc_minutes": 26,
                "messages": 160,
                "quests": 1
            },
            14: {
                "words": 4900,
                "vc_minutes": 28,
                "messages": 180,
                "quests": 1
            },
            15: {
                "words": 5200,
                "vc_minutes": 30,
                "messages": 200,
                "quests": 2
            },
            16: {
                "words": 5500,
                "vc_minutes": 32,
                "messages": 220,
                "quests": 2
            },
            17: {
                "words": 5800,
                "vc_minutes": 34,
                "messages": 240,
                "quests": 2
            },
            18: {
                "words": 6100,
                "vc_minutes": 36,
                "messages": 260,
                "quests": 2
            },
            19: {
                "words": 6400,
                "vc_minutes": 38,
                "messages": 280,
                "quests": 3
            },
            20: {
                "words": 6700,
                "vc_minutes": 40,
                "messages": 300,
                "quests": 3
            },
            100: {
                "words": 50000,
                "vc_minutes": 300,
                "messages": 5000,
                "quests": 20
            }
        }

        if level in requirements:
            return requirements[level]
        else:
            base_words = 6700 + (level - 20) * 500
            base_vc = 40 + (level - 20) * 3
            base_messages = 300 + (level - 20) * 50
            base_quests = max(3, min(20, 3 + (level - 20) // 5))

            return {
                "words": base_words,
                "vc_minutes": base_vc,
                "messages": base_messages,
                "quests": base_quests
            }


# Utility functions
def get_db_connection():
    conn = sqlite3.connect('questuza.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_user_data(user_id: int, guild_id: int) -> Dict:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT * FROM users WHERE user_id = ? AND guild_id = ?''',
              (user_id, guild_id))
    result = c.fetchone()
    conn.close()

    if result:
        return dict(result)
    return None


def update_user_data(user_data: Dict):
    conn = get_db_connection()
    c = conn.cursor()

    # Check if user exists
    c.execute('''SELECT 1 FROM users WHERE user_id = ? AND guild_id = ?''',
              (user_data['user_id'], user_data['guild_id']))
    exists = c.fetchone()

    if exists:
        c.execute(
            '''UPDATE users SET 
                     unique_words = ?, vc_seconds = ?, level = ?, xp = ?,
                     messages_sent = ?, images_sent = ?, channels_used = ?,
                     lifetime_words = ?, quests_completed = ?, custom_color = ?,
                     banner_url = ?, last_trivia_win = ?, xp_multiplier = ?,
                     multiplier_expires = ?, autoclaim_enabled = ?, 
                     daily_quests_completed = ?, weekly_quests_completed = ?,
                     last_daily_reset = ?, last_weekly_reset = ?
                     WHERE user_id = ? AND guild_id = ?''',
            (user_data['unique_words'], user_data['vc_seconds'],
             user_data['level'], user_data['xp'], user_data['messages_sent'],
             user_data['images_sent'], user_data['channels_used'],
             user_data['lifetime_words'], user_data['quests_completed'],
             user_data['custom_color'], user_data['banner_url'],
             user_data['last_trivia_win'], user_data['xp_multiplier'],
             user_data['multiplier_expires'], 
             user_data.get('autoclaim_enabled', 0),
             user_data.get('daily_quests_completed', 0),
             user_data.get('weekly_quests_completed', 0),
             user_data.get('last_daily_reset'),
             user_data.get('last_weekly_reset'),
             user_data['user_id'], user_data['guild_id']))
    else:
        c.execute(
            '''INSERT INTO users 
                     (user_id, guild_id, unique_words, vc_seconds, level, xp, 
                      messages_sent, images_sent, channels_used, lifetime_words,
                      quests_completed, custom_color, banner_url, last_trivia_win,
                      xp_multiplier, multiplier_expires, created_at, autoclaim_enabled,
                      daily_quests_completed, weekly_quests_completed, 
                      last_daily_reset, last_weekly_reset)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (user_data['user_id'], user_data['guild_id'],
             user_data['unique_words'], user_data['vc_seconds'],
             user_data['level'], user_data['xp'], user_data['messages_sent'],
             user_data['images_sent'], user_data['channels_used'],
             user_data['lifetime_words'], user_data['quests_completed'],
             user_data['custom_color'], user_data['banner_url'],
             user_data['last_trivia_win'], user_data['xp_multiplier'],
             user_data['multiplier_expires'],
             user_data.get('created_at', datetime.datetime.now().isoformat()),
             user_data.get('autoclaim_enabled', 0),
             user_data.get('daily_quests_completed', 0),
             user_data.get('weekly_quests_completed', 0),
             user_data.get('last_daily_reset'),
             user_data.get('last_weekly_reset')))

    conn.commit()
    conn.close()


def get_user_rank(user_id: int, guild_id: int) -> int:
    """Get user's rank in the overall leaderboard"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get all users ordered by level DESC, xp DESC
    c.execute('''SELECT user_id FROM users 
                 WHERE guild_id = ? 
                 ORDER BY level DESC, xp DESC''',
              (guild_id,))
    results = c.fetchall()
    conn.close()
    
    # Find the rank (1-indexed)
    for rank, (uid,) in enumerate(results, 1):
        if uid == user_id:
            return rank
    
    return 0  # User not found in leaderboard


def count_unique_words(text: str) -> int:
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'<@!?\d+>', '', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    words = re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())
    return len(set(words))


def create_default_user(user_id: int, guild_id: int) -> Dict:
    return {
        'user_id': user_id,
        'guild_id': guild_id,
        'unique_words': 0,
        'vc_seconds': 0,
        'level': 0,
        'xp': 0,
        'messages_sent': 0,
        'images_sent': 0,
        'channels_used': 0,
        'lifetime_words': 0,
        'quests_completed': 0,
        'custom_color': '#5865F2',
        'banner_url': None,
        'last_trivia_win': None,
        'xp_multiplier': 1.0,
        'multiplier_expires': None,
        'created_at': datetime.datetime.now().isoformat(),
        'autoclaim_enabled': 0,
        'daily_quests_completed': 0,
        'weekly_quests_completed': 0,
        'last_daily_reset': None,
        'last_weekly_reset': None
    }


# Global variables for uptime monitoring
disconnect_time = None
reconnect_attempts = 0
max_reconnect_attempts = 5
base_reconnect_delay = 5  # seconds

# Bot events
@bot.event
async def on_ready():
    print(f'🚀 Questuza v{VERSION} is online! Logged in as {bot.user.name}')
    print(f'📊 Connected to {len(bot.guilds)} guilds')
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="your quests | %help"))

    # Handle offline VC tracking - catch up on missed time
    await handle_offline_vc_tracking()

    # Start the background tasks
    if not check_voice_sessions.is_running():
        check_voice_sessions.start()
    if not send_keep_alive.is_running():
        send_keep_alive.start()
        print("💚 Keep-alive task started - sending messages every 2 minutes")
    if not schedule_trivia_questions.is_running():
        schedule_trivia_questions.start()
        print("🎯 Trivia auto-scheduler started - checking every 2 hours")


@bot.event
async def on_disconnect():
    """Handle bot disconnection with logging and recovery preparation"""
    global disconnect_time, reconnect_attempts
    disconnect_time = datetime.datetime.now()
    reconnect_attempts = 0

    print(f"⚠️  Bot disconnected at {disconnect_time}")
    print("🔄 Preparing for automatic reconnection...")

    # Log disconnection to all guilds (if possible)
    for guild in bot.guilds:
        try:
            # Try to find a suitable channel to log disconnection
            log_channel = None
            if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                log_channel = guild.system_channel
            else:
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        log_channel = ch
                        break

            if log_channel:
                embed = discord.Embed(
                    title="🔌 Bot Disconnected",
                    description="Questuza has been disconnected and is attempting to reconnect automatically.",
                    color=discord.Color.orange(),
                    timestamp=disconnect_time
                )
                embed.set_footer(text="Automatic recovery in progress...")
                await log_channel.send(embed=embed)
        except Exception as e:
            print(f"❌ Failed to send disconnect notification to {guild.name}: {e}")


@bot.event
async def on_resumed():
    """Handle successful reconnection with recovery notifications"""
    global disconnect_time, reconnect_attempts

    if disconnect_time:
        downtime = datetime.datetime.now() - disconnect_time
        downtime_seconds = int(downtime.total_seconds())

        print(f"✅ Bot reconnected successfully after {downtime_seconds}s downtime")
        print(f"🔄 Reconnection attempts used: {reconnect_attempts}")

        # Reset reconnection variables
        disconnect_time = None
        reconnect_attempts = 0

        # Send recovery notifications to guilds
        for guild in bot.guilds:
            try:
                # Find suitable channel for recovery notification
                notify_channel = None
                if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                    notify_channel = guild.system_channel
                else:
                    for ch in guild.text_channels:
                        if ch.permissions_for(guild.me).send_messages:
                            notify_channel = ch
                            break

                if notify_channel:
                    embed = discord.Embed(
                        title="🔄 Bot Reconnected",
                        description="Questuza has successfully reconnected and recovered all systems!",
                        color=discord.Color.green(),
                        timestamp=datetime.datetime.now()
                    )

                    # Format downtime nicely
                    if downtime_seconds < 60:
                        downtime_str = f"{downtime_seconds} seconds"
                    elif downtime_seconds < 3600:
                        minutes = downtime_seconds // 60
                        seconds = downtime_seconds % 60
                        downtime_str = f"{minutes}m {seconds}s"
                    else:
                        hours = downtime_seconds // 3600
                        minutes = (downtime_seconds % 3600) // 60
                        downtime_str = f"{hours}h {minutes}m"

                    embed.add_field(
                        name="Downtime",
                        value=downtime_str,
                        inline=True
                    )
                    embed.add_field(
                        name="Status",
                        value="✅ All systems operational",
                        inline=True
                    )
                    embed.set_footer(text="Quest tracking and XP systems have been restored")

                    await notify_channel.send(embed=embed)
            except Exception as e:
                print(f"❌ Failed to send recovery notification to {guild.name}: {e}")

        # Handle offline VC tracking after reconnection
        try:
            await handle_offline_vc_tracking()
            print("✅ Offline VC tracking catch-up completed after reconnection")
        except Exception as e:
            print(f"❌ Error during VC catch-up after reconnection: {e}")

    # Update bot status
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="your quests | %help"))


@bot.event
async def on_connect():
    """Handle initial connection and reconnection attempts"""
    global reconnect_attempts

    if reconnect_attempts > 0:
        print(f"🔗 Reconnection attempt #{reconnect_attempts} successful")
        reconnect_attempts = 0


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Check for wrong prefix usage - only for commands that closely match bot commands
    content = message.content.strip()
    wrong_prefixes = ['$', '!', '/', '.', '>', '<', '?']

    # Only check for typos if the message looks like it could be a command
    if len(content) > 1 and len(content) < 50:  # Reasonable command length
        for prefix in wrong_prefixes:
            if content.startswith(prefix):
                # Extract the command part
                command_part = content[1:].split()[0] if len(content) > 1 else ""
                similar_cmd = get_similar_command(command_part)

                # Only suggest if it's a very close match (not just any random word)
                if similar_cmd and len(command_part) >= 3:  # Minimum 3 characters for suggestion
                    embed = discord.Embed(
                        title="🤔 Wrong Prefix Detected",
                        description=f"Hey there! It looks like you tried to use a command, but used the wrong prefix.",
                        color=discord.Color.orange()
                    )
                    embed.add_field(
                        name="You typed:",
                        value=f"`{content[:50]}`",
                        inline=False
                    )
                    embed.add_field(
                        name="Did you mean:",
                        value=f"`%{similar_cmd}`",
                        inline=False
                    )
                    embed.set_footer(text="💡 Tip: All Questuza commands start with %")
                    await message.channel.send(embed=embed)
                    return

    # Continue with normal message processing
    if content.startswith('%'):
        return await bot.process_commands(message)

    user_data = get_user_data(message.author.id, message.guild.id)
    if not user_data:
        user_data = create_default_user(message.author.id, message.guild.id)

    # Prepare cleaned words list (counts total words, not just unique)
    txt = re.sub(r'http\S+', '', message.content or '')
    txt = re.sub(r'<@!?\d+>', '', txt)
    txt = re.sub(r'[^\w\s]', ' ', txt)
    words_list = re.findall(r'\b[a-zA-Z]{2,}\b', txt.lower())
    total_words = len(words_list)

    # Only consider messages with at least 2 words
    if total_words >= 2:
        # XP counts use first 50 words only
        xp_word_count = min(50, total_words)
        unique_words = len(set(words_list))

        # Normalize content for duplicate detection
        normalized = ' '.join((message.content or '').split()).strip().lower()
        key = (message.guild.id if message.guild else None, message.channel.id)
        last = LAST_USER_MESSAGE.get(key)
        is_consecutive_duplicate = last and last.get('author_id') == message.author.id and last.get('content') == normalized

        # Update last message record for this channel
        LAST_USER_MESSAGE[key] = {'author_id': message.author.id, 'content': normalized}

        # If it's a consecutive duplicate outside spam channel => punish (deduct XP by removing equivalent lifetime words)
        if is_consecutive_duplicate and message.channel.id != SPAM_CHANNEL_ID:
            # Deduct the XP equivalent by subtracting lifetime words (10 XP per word -> 1 word = 10 XP)
            user_data['lifetime_words'] = user_data.get('lifetime_words', 0) - xp_word_count
            # Still count the message as a message for stats
            user_data['messages_sent'] += 1
        else:
            # Normal or spam-channel message: update stats
            user_data['messages_sent'] += 1
            # Keep unique words tracking (used by quests)
            user_data['unique_words'] += unique_words

            # If this is the spam channel, award heavily reduced XP: 1 XP per 100 words (so add to xp directly)
            if message.channel.id == SPAM_CHANNEL_ID:
                spam_xp = xp_word_count // 100  # integer division: 1 XP per 100 words
                if spam_xp:
                    user_data['xp'] = user_data.get('xp', 0) + spam_xp
            else:
                # For regular channels, add xp via lifetime_words (10 XP per word)
                user_data['lifetime_words'] = user_data.get('lifetime_words', 0) + xp_word_count

        # Track channel usage
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            '''SELECT 1 FROM user_channels 
                     WHERE user_id = ? AND guild_id = ? AND channel_id = ?''',
            (message.author.id, message.guild.id if message.guild else None, message.channel.id))
        if not c.fetchone():
            c.execute(
                '''INSERT INTO user_channels (user_id, guild_id, channel_id)
                         VALUES (?, ?, ?)''',
                (message.author.id, message.guild.id if message.guild else None, message.channel.id))
            user_data['channels_used'] += 1
        conn.commit()
        conn.close()

    if message.attachments:
        image_count = len([
            att for att in message.attachments
            if att.content_type and 'image' in att.content_type
        ])
        if image_count > 0:
            user_data['images_sent'] += image_count

    update_user_data(user_data)
    
    # Update daily and weekly quest stats
    is_reply = 1 if message.reference else 0
    # Use unique_words for quest progress reporting, but cap for XP was applied above
    words_count = len(set(re.findall(r'\b[a-zA-Z]{2,}\b', re.sub(r'http\S+', '', message.content or '').lower()))) if message.content else 0

    # Track unique channels for daily stats - check if this is a new channel for today
    conn = get_db_connection()
    today = datetime.date.today().isoformat()
    c = conn.cursor()

    # Check if this channel was already used today in daily_channels table
    c.execute('''SELECT 1 FROM daily_channels
                 WHERE user_id = ? AND guild_id = ? AND date = ? AND channel_id = ?''',
              (message.author.id, message.guild.id, today, message.channel.id))
    channel_already_used_today = c.fetchone() is not None

    # If this is a new channel for today, insert it into daily_channels
    if not channel_already_used_today:
        c.execute('''INSERT INTO daily_channels (user_id, guild_id, date, channel_id)
                     VALUES (?, ?, ?, ?)''',
                  (message.author.id, message.guild.id, today, message.channel.id))

    # Only increment daily channels if this is a new channel for today
    daily_channels_increment = 1 if not channel_already_used_today else 0

    conn.commit()
    conn.close()

    update_daily_stats(message.author.id, message.guild.id,
                      messages=1, words=words_count, replies=is_reply, channels=daily_channels_increment)
    update_weekly_stats(message.author.id, message.guild.id,
                       messages=1, words=words_count)
    
    # Check for expired unclaimed quests and auto-collect at 10%
    from quest_system import collect_expired_quests
    expired_quests = collect_expired_quests(message.author.id, message.guild.id)
    if expired_quests:
        total_expired_xp = sum(xp for _, xp in expired_quests)
        user_data['xp'] += total_expired_xp
        update_user_data(user_data)
        
        # NO MESSAGE SENT - Silent collection
    
    # Check for completed quests
    completed = check_and_complete_quests(message.author.id, message.guild.id, user_data)
    if completed:
        # Quest announcement channel ID
        QUEST_ANNOUNCEMENT_CHANNEL_ID = 1158615333289086997
        announcement_channel = bot.get_channel(QUEST_ANNOUNCEMENT_CHANNEL_ID)
        
        # Check if user has autoclaim enabled
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''SELECT autoclaim_enabled FROM users WHERE user_id = ? AND guild_id = ?''',
                  (message.author.id, message.guild.id))
        result = c.fetchone()
        autoclaim_enabled = result[0] if result and result[0] else 0
        conn.close()
        
        for quest in completed:
            # Handle auto-claim if enabled
            if autoclaim_enabled:
                reduced_xp = int(quest.xp_reward * 0.6)  # 40% fee = 60% received
                user_data['xp'] += reduced_xp
                user_data['quests_completed'] += 1
                
                # Track daily/weekly quest completion for multipliers
                from quest_system import QuestType
                if quest.quest_type == QuestType.DAILY:
                    user_data['daily_quests_completed'] = user_data.get('daily_quests_completed', 0) + 1
                elif quest.quest_type == QuestType.WEEKLY:
                    user_data['weekly_quests_completed'] = user_data.get('weekly_quests_completed', 0) + 1
                
                update_user_data(user_data)
                claim_quest_reward(message.author.id, message.guild.id, quest.quest_id)
                
                embed = discord.Embed(
                    title=f"{quest.emoji} Quest Auto-Claimed!",
                    description=f"{message.author.mention} completed **{quest.name}**!\n{quest.description}",
                    color=discord.Color.gold()
                )
                embed.add_field(name="XP Received (60%)", value=f"+{reduced_xp:,} XP", inline=True)
                embed.add_field(name="Fee (40%)", value=f"-{quest.xp_reward - reduced_xp:,} XP", inline=True)
                embed.set_footer(text=f"Auto-claimed • Use %autoclaim off to disable and claim full rewards manually")
            else:
                embed = discord.Embed(
                    title=f"{quest.emoji} Quest Completed!",
                    description=f"{message.author.mention} completed **{quest.name}**!\n{quest.description}",
                    color=discord.Color.gold()
                )
                embed.add_field(name="Reward", value=f"+{quest.xp_reward:,} XP", inline=True)
                embed.add_field(name="Quest Type", value=quest.quest_type.value.title(), inline=True)
                embed.set_footer(text=f"Use %claim {quest.quest_id} to claim your reward!")
            
            # Try to send to announcement channel, fallback to current channel
            try:
                if announcement_channel:
                    await announcement_channel.send(embed=embed)
                else:
                    await message.channel.send(embed=embed)
            except:
                try:
                    await message.channel.send(embed=embed)
                except:
                    pass
    
    await check_level_up(message.author, message.guild)
    await bot.process_commands(message)


# SIMPLIFIED VC TRACKING - FIXED VERSION WITH 5-HOUR CAP
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    conn = get_db_connection()

    # User joined VC
    if before.channel is None and after.channel is not None:
        print(f"🎧 {member} joined VC: {after.channel.name}")
        # Remove any existing session for this user (cleanup)
        conn.execute(
            '''DELETE FROM voice_sessions
                       WHERE user_id = ? AND guild_id = ?''',
            (member.id, member.guild.id))
        # Create new session
        conn.execute(
            '''INSERT INTO voice_sessions
                       (user_id, guild_id, channel_id, join_time, leave_time)
                       VALUES (?, ?, ?, ?, ?)''',
            (member.id, member.guild.id, after.channel.id,
             datetime.datetime.now().isoformat(), None))

    # User left VC
    elif before.channel is not None and after.channel is None:
        print(f"🎧 {member} left VC: {before.channel.name}")
        # Find the active session
        result = conn.execute(
            '''SELECT join_time FROM voice_sessions
                               WHERE user_id = ? AND guild_id = ? AND leave_time IS NULL''',
            (member.id, member.guild.id)).fetchone()

        if result:
            join_time = result[0]
            join_dt = datetime.datetime.fromisoformat(join_time)
            session_duration = max(0, (datetime.datetime.now() -
                                       join_dt).total_seconds())

            # Apply 5-hour cap (18000 seconds) to individual sessions
            capped_duration = min(session_duration, 18000)  # 5 hours max

            if session_duration > 18000:
                print(f"⏱️ Capped VC session for {member} from {int(session_duration)}s to 5 hours (18000s)")

            # Update user VC time
            user_data = get_user_data(member.id, member.guild.id)
            if not user_data:
                user_data = create_default_user(member.id, member.guild.id)

            user_data['vc_seconds'] += int(capped_duration)
            update_user_data(user_data)
            print(f"⏱️ Added {int(capped_duration)}s VC time to {member}")

            # Update quest stats for VC time
            vc_minutes = int(capped_duration) // 60
            if vc_minutes > 0:
                update_daily_stats(member.id, member.guild.id, vc_minutes=vc_minutes)
                update_weekly_stats(member.id, member.guild.id, vc_minutes=vc_minutes)

            # Mark session as completed
            conn.execute(
                '''UPDATE voice_sessions SET leave_time = ?
                         WHERE user_id = ? AND guild_id = ? AND leave_time IS NULL''',
                (datetime.datetime.now().isoformat(), member.id,
                 member.guild.id))

    conn.commit()
    conn.close()


# Optimized background task with indexed queries
@tasks.loop(minutes=5)
async def check_voice_sessions():
    """Clean up VC sessions where users might have left without proper tracking"""
    try:
        conn = get_db_connection()

        # Find sessions older than 1 hour without leave time
        # Uses idx_voice_sessions_cleanup index
        cutoff = (datetime.datetime.now() -
                  datetime.timedelta(hours=1)).isoformat()
        orphaned_sessions = conn.execute(
            '''SELECT user_id, guild_id, join_time 
                                          FROM voice_sessions 
                                          WHERE leave_time IS NULL AND join_time < ?''',
            (cutoff, )).fetchall()

        if orphaned_sessions:
            # Batch process sessions for efficiency
            for session in orphaned_sessions:
                user_id, guild_id, join_time = session
                join_dt = datetime.datetime.fromisoformat(join_time)
                session_duration = max(0, (datetime.datetime.now() -
                                           join_dt).total_seconds())

                # Update user data using optimized query
                conn.execute(
                    '''UPDATE users SET vc_seconds = vc_seconds + ?
                             WHERE user_id = ? AND guild_id = ?''',
                    (int(session_duration), user_id, guild_id))
                
                print(
                    f"🧹 Cleaned orphaned VC session for user {user_id}: {int(session_duration)}s"
                )

                # Close the session
                conn.execute(
                    '''UPDATE voice_sessions SET leave_time = ?
                             WHERE user_id = ? AND guild_id = ? AND leave_time IS NULL''',
                    (datetime.datetime.now().isoformat(), user_id, guild_id))

            conn.commit()
            print(f"✅ VC session cleanup completed - processed {len(orphaned_sessions)} sessions")
        else:
            print("✅ VC session cleanup completed - no orphaned sessions found")
        
        conn.close()
    except Exception as e:
        print(f"❌ Error in VC session cleanup: {e}")


# Keep-alive message counter
keep_alive_counter = 0

@tasks.loop(minutes=2)
async def send_keep_alive():
    """Send periodic message to keep the Repl active"""
    global keep_alive_counter
    try:
        keep_alive_counter += 1
        channel = bot.get_channel(1334070829415141436)

        if channel:
            await channel.send(f"Ignore this message, I am just trying to stay alive :P This is attempt number {keep_alive_counter}")
            print(f"💚 Keep-alive message sent (attempt #{keep_alive_counter})")
        else:
            print(f"❌ Keep-alive channel not found!")
    except Exception as e:
        print(f"❌ Error sending keep-alive message: {e}")


# Trivia system variables
TRIVIA_XP_MULTIPLIER = 2.0  # 2x XP for correct answers
TRIVIA_XP_PENALTY = 10000   # -10k XP for wrong answers
TRIVIA_QUESTION_TIMEOUT = 300  # 5 minutes to answer
TRIVIA_AUTO_SCHEDULE_HOURS = 2  # Auto-schedule questions every 2 hours

# Trivia background task
@tasks.loop(hours=TRIVIA_AUTO_SCHEDULE_HOURS)
async def schedule_trivia_questions():
    """Automatically schedule trivia questions in designated channels"""
    try:
        for guild in bot.guilds:
            # Check if guild has a trivia channel set
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''SELECT trivia_channel FROM guild_settings WHERE guild_id = ?''',
                      (guild.id,))
            result = c.fetchone()
            conn.close()

            if result and result[0]:
                trivia_channel_id = result[0]
                trivia_channel = bot.get_channel(trivia_channel_id)

                if trivia_channel and trivia_channel.permissions_for(guild.me).send_messages:
                    # Check if there's already an active trivia session
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute('''SELECT 1 FROM trivia_sessions WHERE guild_id = ?''',
                              (guild.id,))
                    active_session = c.fetchone()
                    conn.close()

                    if not active_session:
                        # Start a random trivia question
                        await start_random_trivia_question(guild, trivia_channel)
                        print(f"🎯 Auto-scheduled trivia question in {guild.name}")
    except Exception as e:
        print(f"❌ Error in trivia auto-scheduler: {e}")


async def start_random_trivia_question(guild, channel):
    """Start a random trivia question in the specified channel"""
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Get a random question that hasn't been asked recently
        c.execute('''SELECT id, question, answer FROM trivia_questions
                     ORDER BY RANDOM() LIMIT 1''')
        question_data = c.fetchone()

        if not question_data:
            await channel.send("❌ No trivia questions available!")
            conn.close()
            return

        question_id, question, correct_answer = question_data

        # Create trivia session
        expires_at = (datetime.datetime.now() + datetime.timedelta(seconds=TRIVIA_QUESTION_TIMEOUT)).isoformat()
        c.execute('''INSERT OR REPLACE INTO trivia_sessions
                     (guild_id, question_id, started_at, expires_at, answered_by)
                     VALUES (?, ?, ?, ?, NULL)''',
                  (guild.id, question_id, datetime.datetime.now().isoformat(), expires_at))

        conn.commit()
        conn.close()

        # Send the question
        embed = discord.Embed(
            title="🎯 Trivia Time!",
            description=f"**Question:** {question}",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(
            name="How to Answer",
            value="Reply with `%trivia answer <your_answer>`\nYou have 5 minutes to answer!",
            inline=False
        )
        embed.add_field(
            name="Rewards",
            value=f"✅ Correct: {TRIVIA_XP_MULTIPLIER}x XP multiplier\n❌ Wrong: -{TRIVIA_XP_PENALTY:,} XP penalty",
            inline=False
        )
        embed.set_footer(text="First correct answer wins!")

        await channel.send(embed=embed)

    except Exception as e:
        print(f"❌ Error starting trivia question: {e}")
        await channel.send("❌ Sorry, there was an error starting the trivia question!")


async def check_trivia_answer(user, guild, answer):
    """Check if the user's answer is correct and award/penalize XP"""
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Get active trivia session
        c.execute('''SELECT question_id, expires_at, answered_by FROM trivia_sessions
                     WHERE guild_id = ?''', (guild.id,))
        session_data = c.fetchone()

        if not session_data:
            conn.close()
            return "❌ No active trivia question in this guild!"

        question_id, expires_at, answered_by = session_data

        # Check if already answered
        if answered_by:
            conn.close()
            return "❌ This question has already been answered!"

        # Check if expired
        if datetime.datetime.now() > datetime.datetime.fromisoformat(expires_at):
            # Clean up expired session
            c.execute('''DELETE FROM trivia_sessions WHERE guild_id = ?''', (guild.id,))
            conn.commit()
            conn.close()
            return "❌ This trivia question has expired!"

        # Get the correct answer
        c.execute('''SELECT answer FROM trivia_questions WHERE id = ?''', (question_id,))
        correct_answer_data = c.fetchone()

        if not correct_answer_data:
            conn.close()
            return "❌ Error retrieving question data!"

        correct_answer = correct_answer_data[0].lower().strip()

        # Normalize answers for comparison
        user_answer = answer.lower().strip()
        correct_normalized = correct_answer.lower().strip()

        # Get user data
        user_data = get_user_data(user.id, guild.id)
        if not user_data:
            user_data = create_default_user(user.id, guild.id)

        if user_answer == correct_normalized:
            # Correct answer - award XP with multiplier
            base_xp = 500  # Base XP for correct trivia answer
            bonus_xp = int(base_xp * (TRIVIA_XP_MULTIPLIER - 1))  # Additional XP from multiplier
            total_xp = base_xp + bonus_xp

            user_data['xp'] += total_xp
            user_data['trivia_wins'] = user_data.get('trivia_wins', 0) + 1
            update_user_data(user_data)

            # Mark session as answered
            c.execute('''UPDATE trivia_sessions SET answered_by = ? WHERE guild_id = ?''',
                      (user.id, guild.id))
            conn.commit()
            conn.close()

            return f"🎉 **Correct!** {user.mention} got it right!\n" \
                   f"**XP Gained:** +{total_xp:,} XP ({TRIVIA_XP_MULTIPLIER}x multiplier)\n" \
                   f"**Total Trivia Wins:** {user_data['trivia_wins']}"

        else:
            # Wrong answer - apply penalty
            old_xp = user_data['xp']
            user_data['xp'] = max(0, user_data['xp'] - TRIVIA_XP_PENALTY)
            penalty_applied = old_xp - user_data['xp']
            update_user_data(user_data)

            conn.close()

            return f"❌ **Wrong answer!** {user.mention}\n" \
                   f"**XP Penalty:** -{penalty_applied:,} XP\n" \
                   f"**Correct Answer:** ||{correct_answer.title()}||"

    except Exception as e:
        print(f"❌ Error checking trivia answer: {e}")
        return "❌ Sorry, there was an error processing your answer!"


# Trivia commands
@bot.command(name='trivia')
async def trivia_cmd(ctx, action: str = None, *, args: str = None):
    """Trivia system commands - Usage: %trivia <start|answer|stop|setchannel> [args]"""

    if not action:
        embed = discord.Embed(
            title="🎯 Trivia System Help",
            description="Test your knowledge and earn XP!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Commands",
            value="`%trivia start` - Start a trivia question\n"
                  "`%trivia answer <your_answer>` - Answer the current question\n"
                  "`%trivia stop` - Stop current trivia (admin only)\n"
                  "`%trivia setchannel` - Set trivia channel (admin only)",
            inline=False
        )
        embed.add_field(
            name="Rewards",
            value=f"✅ Correct: {TRIVIA_XP_MULTIPLIER}x XP multiplier\n❌ Wrong: -{TRIVIA_XP_PENALTY:,} XP penalty",
            inline=False
        )
        await ctx.send(embed=embed)
        return

    action = action.lower()

    if action == "start":
        # Check permissions - anyone can start trivia
        conn = get_db_connection()
        c = conn.cursor()

        # Check if trivia channel is set
        c.execute('''SELECT trivia_channel FROM guild_settings WHERE guild_id = ?''',
                  (ctx.guild.id,))
        result = c.fetchone()

        if not result or not result[0]:
            conn.close()
            await ctx.send("❌ No trivia channel set! Ask an admin to use `%trivia setchannel` first.")
            return

        trivia_channel_id = result[0]

        # Check if already in trivia channel
        if ctx.channel.id != trivia_channel_id:
            trivia_channel = bot.get_channel(trivia_channel_id)
            conn.close()
            await ctx.send(f"❌ Trivia questions can only be started in {trivia_channel.mention if trivia_channel else 'the designated trivia channel'}!")
            return

        # Check for active session
        c.execute('''SELECT 1 FROM trivia_sessions WHERE guild_id = ?''', (ctx.guild.id,))
        active_session = c.fetchone()

        if active_session:
            conn.close()
            await ctx.send("❌ There's already an active trivia question! Wait for it to be answered or expire.")
            return

        conn.close()

        # Start the trivia question
        await start_random_trivia_question(ctx.guild, ctx.channel)
        await ctx.send("🎯 Trivia question started!")

    elif action == "answer":
        if not args:
            await ctx.send("❌ Please provide an answer! Usage: `%trivia answer <your_answer>`")
            return

        result = await check_trivia_answer(ctx.author, ctx.guild, args.strip())
        await ctx.send(result)

    elif action == "stop":
        # Admin only
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Only administrators can stop trivia sessions!")
            return

        conn = get_db_connection()
        c = conn.cursor()

        # Check for active session
        c.execute('''SELECT 1 FROM trivia_sessions WHERE guild_id = ?''', (ctx.guild.id,))
        active_session = c.fetchone()

        if not active_session:
            conn.close()
            await ctx.send("❌ No active trivia session to stop!")
            return

        # Delete the session
        c.execute('''DELETE FROM trivia_sessions WHERE guild_id = ?''', (ctx.guild.id,))
        conn.commit()
        conn.close()

        await ctx.send("🛑 Trivia session stopped by administrator.")

    elif action == "setchannel":
        # Admin only
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Only administrators can set the trivia channel!")
            return

        # Set current channel as trivia channel
        conn = get_db_connection()
        c = conn.cursor()

        c.execute('''INSERT OR REPLACE INTO guild_settings
                     (guild_id, trivia_channel) VALUES (?, ?)''',
                  (ctx.guild.id, ctx.channel.id))
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="✅ Trivia Channel Set!",
            description=f"Trivia questions will now be posted in {ctx.channel.mention}",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Auto-Scheduling",
            value=f"Random questions will be posted every {TRIVIA_AUTO_SCHEDULE_HOURS} hours",
            inline=False
        )
        await ctx.send(embed=embed)

    elif action == "stats":
        # Show trivia stats
        user_data = get_user_data(ctx.author.id, ctx.guild.id)
        if not user_data:
            user_data = create_default_user(ctx.author.id, ctx.guild.id)

        trivia_wins = user_data.get('trivia_wins', 0)

        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Trivia Stats",
            color=discord.Color.purple()
        )
        embed.add_field(name="Trivia Wins", value=f"{trivia_wins:,}", inline=True)
        embed.add_field(name="XP from Trivia", value=f"{trivia_wins * 500:,} XP", inline=True)

        await ctx.send(embed=embed)

    else:
        await ctx.send("❌ Invalid action! Use `%trivia` for help.")


async def check_level_up(user, guild):
    user_data = get_user_data(user.id, guild.id)
    if not user_data:
        return

    current_level = user_data['level']
    next_level = current_level + 1

    if next_level > 100:
        return

    requirements = LevelSystem.get_level_requirements(next_level)

    words_met = user_data['unique_words'] >= requirements['words']
    vc_met = user_data['vc_seconds'] >= (requirements['vc_minutes'] * 60)
    messages_met = user_data['messages_sent'] >= requirements['messages']
    quests_met = user_data['quests_completed'] >= requirements['quests']

    if words_met and vc_met and messages_met and quests_met:
        user_data['level'] = next_level
        user_data['xp'] += requirements['words'] * 10
        # Reset counters after leveling up
        user_data['unique_words'] = max(
            0, user_data['unique_words'] - requirements['words'])
        user_data['vc_seconds'] = max(
            0, user_data['vc_seconds'] - (requirements['vc_minutes'] * 60))
        user_data['messages_sent'] = max(
            0, user_data['messages_sent'] - requirements['messages'])
        user_data['quests_completed'] = max(
            0, user_data['quests_completed'] - requirements['quests'])
        update_user_data(user_data)

        embed = discord.Embed(
            title="🎉 Level Up!",
            description=
            f"{user.mention} reached **Level {user_data['level']}**!",
            color=discord.Color.green())
        embed.add_field(name="Words",
                        value=f"{user_data['unique_words']:,}",
                        inline=True)
        embed.add_field(name="VC Time",
                        value=f"{user_data['vc_seconds']//60}m",
                        inline=True)
        embed.add_field(name="Quests",
                        value=user_data['quests_completed'],
                        inline=True)

        channel = None
        if guild.system_channel and guild.system_channel.permissions_for(
                guild.me).send_messages:
            channel = guild.system_channel
        else:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break

        if channel:
            try:
                await channel.send(embed=embed)
                print(f"🎉 Level up message sent for {user}")
            except Exception as e:
                print(f"❌ Couldn't send level up message: {e}")


async def handle_offline_vc_tracking():
    """Handle VC tracking when bot comes back online - catch up on missed time"""
    print("🔄 Checking for offline VC sessions to catch up...")

    conn = get_db_connection()
    try:
        # Find all active sessions (no leave_time)
        active_sessions = conn.execute(
            '''SELECT user_id, guild_id, join_time FROM voice_sessions
                       WHERE leave_time IS NULL''').fetchall()

        if not active_sessions:
            print("✅ No active VC sessions found to catch up")
            return

        caught_up_count = 0
        for session in active_sessions:
            user_id, guild_id, join_time_str = session
            join_time = datetime.datetime.fromisoformat(join_time_str)
            now = datetime.datetime.now()

            # Calculate missed time
            missed_seconds = max(0, (now - join_time).total_seconds())

            if missed_seconds > 0:
                # Apply 5-hour cap even for offline sessions
                capped_missed = min(missed_seconds, 18000)  # 5 hours max

                # Update user VC time
                user_data = get_user_data(user_id, guild_id)
                if not user_data:
                    user_data = create_default_user(user_id, guild_id)

                user_data['vc_seconds'] += int(capped_missed)
                update_user_data(user_data)

                # Update quest stats
                vc_minutes = int(capped_missed) // 60
                if vc_minutes > 0:
                    update_daily_stats(user_id, guild_id, vc_minutes=vc_minutes)
                    update_weekly_stats(user_id, guild_id, vc_minutes=vc_minutes)

                # Mark session as completed with current time
                conn.execute(
                    '''UPDATE voice_sessions SET leave_time = ?
                             WHERE user_id = ? AND guild_id = ? AND leave_time IS NULL''',
                    (now.isoformat(), user_id, guild_id))

                caught_up_count += 1
                print(f"⏱️ Caught up {int(capped_missed)}s VC time for user {user_id}")

        conn.commit()
        print(f"✅ Offline VC tracking complete - caught up {caught_up_count} sessions")

    except Exception as e:
        print(f"❌ Error in offline VC tracking: {e}")
    finally:
        conn.close()


# Commands
@bot.command(name='synchistory')
@commands.has_permissions(administrator=True)
async def sync_history_cmd(ctx, member: discord.Member = None):
    """Sync a user's message and activity history with progress tracking (Admin only)"""
    target = member or ctx.author

    # Send initial status message
    status_msg = await ctx.send(
        f"🔄 Syncing history for {target.mention}... This may take a few minutes."
    )

    # Get or create user data
    user_data = get_user_data(target.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(target.id, ctx.guild.id)

    total_messages = 0
    total_words = 0
    channels_used = set()
    images_sent = 0
    
    # Get all text channels
    text_channels = [ch for ch in ctx.guild.text_channels 
                     if ch.permissions_for(ctx.guild.me).read_message_history]
    total_channels = len(text_channels)
    processed_channels = 0

    # Process each text channel with batch processing
    for channel in text_channels:
        try:
            channel_messages = 0
            
            # Process in batches to avoid rate limits
            async for message in channel.history(limit=None):
                if message.author.id == target.id:
                    total_messages += 1
                    channel_messages += 1

                    # Count unique words
                    unique_words = count_unique_words(message.content)
                    if unique_words >= 2:
                        total_words += unique_words
                        channels_used.add(channel.id)

                    # Count images
                    if message.attachments:
                        images_sent += len([
                            att for att in message.attachments
                            if att.content_type and 'image' in att.content_type
                        ])
                    
                    # Update progress every 100 messages
                    if total_messages % 100 == 0:
                        await status_msg.edit(
                            content=f"🔄 Progress: {processed_channels}/{total_channels} channels | {total_messages:,} messages found..."
                        )
                        # Small delay to avoid rate limits
                        await asyncio.sleep(0.5)
            
            processed_channels += 1
            
            # Update after each channel
            progress_percent = int((processed_channels / total_channels) * 100)
            await status_msg.edit(
                content=f"🔄 [{progress_percent}%] Processed {channel.name} ({channel_messages} msgs) | Total: {total_messages:,} messages"
            )
            
        except discord.errors.Forbidden:
            print(f"⚠️ No access to channel: {channel.name}")
            processed_channels += 1
            continue
        except Exception as e:
            print(f"❌ Error processing channel {channel.name}: {e}")
            processed_channels += 1
            continue

    # Update user data with historical stats
    user_data['messages_sent'] = total_messages
    user_data['unique_words'] = total_words
    user_data['lifetime_words'] = total_words
    user_data['channels_used'] = len(channels_used)
    user_data['images_sent'] = images_sent

    # Save updated data
    update_user_data(user_data)

    # Create result embed
    embed = discord.Embed(
        title="📊 History Sync Complete!",
        description=f"Historical data for {target.mention} has been synced.",
        color=discord.Color.green())

    embed.add_field(name="Messages Found",
                    value=f"{total_messages:,}",
                    inline=True)
    embed.add_field(name="Words Counted",
                    value=f"{total_words:,}",
                    inline=True)
    embed.add_field(name="Channels Used",
                    value=str(len(channels_used)),
                    inline=True)
    embed.add_field(name="Images Found", value=str(images_sent), inline=True)
    embed.add_field(name="Channels Processed", 
                    value=f"{processed_channels}/{total_channels}",
                    inline=True)

    await status_msg.edit(content=None, embed=embed)


@bot.command(name='profile')
async def profile_cmd(ctx, member: discord.Member = None):
    target = member or ctx.author
    user_data = get_user_data(target.id, ctx.guild.id)

    if not user_data:
        embed = discord.Embed(
            title=f"{target.display_name}'s Profile",
            description="No data yet! Start chatting to begin your quest.",
            color=discord.Color.blurple())
        await ctx.send(embed=embed)
        return

    current_level = user_data['level']
    next_level = current_level + 1
    next_req = LevelSystem.get_level_requirements(
        next_level) if next_level <= 100 else None

    embed = discord.Embed(title=f"{target.display_name}'s Profile",
                          color=discord.Color.from_str(
                              user_data['custom_color']))

    if user_data['banner_url']:
        embed.set_image(url=user_data['banner_url'])

    # Calculate quest multipliers
    daily_quests = user_data.get('daily_quests_completed', 0)
    weekly_quests = user_data.get('weekly_quests_completed', 0)
    quest_multiplier = 1.0
    
    if daily_quests > 0:
        quest_multiplier += 0.1  # 1.1x for daily quest completion
    if weekly_quests > 0:
        quest_multiplier += 0.25  # Additional 1.25x for weekly quest completion
    
    total_multiplier = user_data.get('xp_multiplier', 1.0) * quest_multiplier
    
    embed.add_field(name="Level", value=user_data['level'], inline=True)
    embed.add_field(name="Total XP", value=f"{user_data['xp']:,}", inline=True)
    embed.add_field(name="Quests Completed",
                    value=user_data['quests_completed'],
                    inline=True)
    
    # Show XP multipliers
    multiplier_text = f"**Base:** {user_data.get('xp_multiplier', 1.0)}x"
    if daily_quests > 0:
        multiplier_text += f"\n**Daily Quest Bonus:** +0.1x ({daily_quests} completed today)"
    if weekly_quests > 0:
        multiplier_text += f"\n**Weekly Quest Bonus:** +0.25x ({weekly_quests} completed this week)"
    if total_multiplier > 1.0:
        multiplier_text += f"\n**Total:** {total_multiplier:.2f}x"
    
    if total_multiplier > 1.0:
        embed.add_field(name="🔥 XP Multipliers", value=multiplier_text, inline=False)

    if next_req and next_level <= 100:
        progress_text = (
            f"**Words:** {user_data['unique_words']}/{next_req['words']}\n"
            f"**VC Time:** {user_data['vc_seconds']//60}/{next_req['vc_minutes']}m\n"
            f"**Messages:** {user_data['messages_sent']}/{next_req['messages']}\n"
            f"**Quests:** {user_data['quests_completed']}/{next_req['quests']}"
        )
    else:
        progress_text = "🎉 Max Level Reached!"

    embed.add_field(name=f"Progress to Level {next_level}"
                    if next_level <= 100 else "Max Level",
                    value=progress_text,
                    inline=False)

    embed.add_field(
        name="Lifetime Stats",
        value=f"**Unique Words:** {user_data['lifetime_words']:,}\n"
        f"**Channels Used:** {user_data['channels_used']}\n"
        f"**Images Sent:** {user_data['images_sent']}\n"
        f"**Voice Time:** {user_data['vc_seconds']//3600}h {(user_data['vc_seconds']%3600)//60}m",
        inline=False)

    if user_data['xp_multiplier'] > 1.0:
        embed.set_footer(
            text=f"🎯 {user_data['xp_multiplier']}x XP Multiplier Active!")

    await ctx.send(embed=embed)


def generate_profile_card(user: discord.Member, user_data: Dict, guild: discord.Guild) -> BytesIO:
    """Generate a profile card image based on the design specifications"""
    import math
    from collections import Counter
    
    # Image dimensions: Portrait orientation (8x11 inches at 150 DPI)
    DPI = 150
    CARD_WIDTH = int(8 * DPI)   # 1200 pixels (portrait width)
    CARD_HEIGHT = int(11 * DPI) # 1650 pixels (portrait height)
    
    # Padding multiplier from user settings (default 3x = 1.2 inches base)
    padding_multiplier = user_data.get('card_padding', 1.2) or 1.2
    base_padding = 0.4  # Base padding in inches
    
    # Padding in inches, converted to pixels (3x default)
    PADDING_LEFT = int(base_padding * padding_multiplier * DPI)
    PADDING_RIGHT = int(base_padding * padding_multiplier * DPI)
    PADDING_TOP = int(base_padding * padding_multiplier * DPI)
    PADDING_BOTTOM = int(base_padding * padding_multiplier * DPI)
    
    # Content area
    CONTENT_X = PADDING_LEFT
    CONTENT_Y = PADDING_TOP
    CONTENT_WIDTH = CARD_WIDTH - PADDING_LEFT - PADDING_RIGHT
    CONTENT_HEIGHT = CARD_HEIGHT - PADDING_TOP - PADDING_BOTTOM
    
    # Default colors
    DEFAULT_BG_COLOR = (128, 128, 128)  # Gray default
    PROFILE_BOX_COLOR = (255, 0, 0)  # Red for profile picture
    COUNTRY_BOX_COLOR = (118, 137, 131)  # #758983 default for country
    GUILD_BOX_COLOR = (118, 137, 131)  # #758983 default for guild
    DEFAULT_PROGRESS_BAR_BG = (84, 107, 81)  # #546b51 dark green (default)
    DEFAULT_PROGRESS_BAR_FILL = (118, 137, 131)  # Ash green (default)
    MULTIPLIER_BOX_COLOR = (84, 107, 81)  # #546b51 dark blue/green
    MESSAGE_ICON_COLOR = (255, 255, 255)  # White
    
    # Helper function to extract dominant color from image
    def get_dominant_color(img: Image.Image, k=3) -> tuple:
        """Extract dominant color from image using k-means clustering approximation"""
        try:
            # Resize for faster processing
            img_small = img.resize((100, 100), Image.Resampling.LANCZOS)
            img_small = img_small.convert('RGB')
            pixels = list(img_small.getdata())
            
            # Simple approach: get most common colors
            color_counts = Counter(pixels)
            # Get top color
            dominant = color_counts.most_common(1)[0][0]
            return dominant
        except:
            return DEFAULT_PROGRESS_BAR_FILL
    
    # Helper function to download image/GIF (extracts first frame for GIFs)
    def download_image(url: str, size: tuple) -> Image.Image:
        try:
            response = requests.get(url, timeout=10, stream=True)
            img_data = Image.open(BytesIO(response.content))
            
            # Handle GIFs - extract first frame
            if hasattr(img_data, 'is_animated') and img_data.is_animated:
                img_data.seek(0)  # Get first frame
            
            img_data = img_data.convert('RGB')
            img_data = img_data.resize(size, Image.Resampling.LANCZOS)
            return img_data
        except:
            return None
    
    # Get background color (use profile_card_bg_color, fallback to custom_color, default to gray)
    bg_color_hex = user_data.get('profile_card_bg_color') or user_data.get('custom_color', '#808080')
    if bg_color_hex.startswith('#'):
        bg_color_hex = bg_color_hex[1:]
    
    try:
        bg_r = int(bg_color_hex[0:2], 16)
        bg_g = int(bg_color_hex[2:4], 16)
        bg_b = int(bg_color_hex[4:6], 16)
    except:
        bg_r, bg_g, bg_b = DEFAULT_BG_COLOR
    
    # Calculate brightness for text color decision
    bg_brightness = (bg_r * 299 + bg_g * 587 + bg_b * 114) / 1000
    
    # No default darkening (0%)
    bg_color = (bg_r, bg_g, bg_b)
    
    # Determine text colors based on background brightness
    # If background is very bright (white), use black text, otherwise white
    is_light_bg = bg_brightness > 200
    TEXT_COLOR = (0, 0, 0) if is_light_bg else (255, 255, 255)
    TEXT_GRAY = (100, 100, 100) if is_light_bg else (180, 180, 180)  # About me text
    
    # Progress bar colors (will be updated if banner is set)
    progress_bar_bg = DEFAULT_PROGRESS_BAR_BG
    progress_bar_fill = DEFAULT_PROGRESS_BAR_FILL
    
    # Create base image
    img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)
    
    # If background_url is set, try to overlay it (with user-defined darkening)
    background_url = user_data.get('background_url')
    banner_img = None
    banner_brightness_value = user_data.get('banner_brightness', 0.0) or 0.0  # 0-100%
    darken_factor = banner_brightness_value / 100.0  # Convert to 0.0-1.0
    
    if background_url:
        try:
            bg_img = download_image(background_url, (CARD_WIDTH, CARD_HEIGHT))
            if bg_img:
                banner_img = bg_img.copy()
                # Calculate brightness from banner image
                banner_brightness = sum(bg_img.convert('L').resize((10, 10)).getdata()) / 100
                is_light_bg = banner_brightness > 200
                TEXT_COLOR = (0, 0, 0) if is_light_bg else (255, 255, 255)
                TEXT_GRAY = (100, 100, 100) if is_light_bg else (180, 180, 180)
                
                # Paste background image first
                img.paste(bg_img, (0, 0))
                # Apply user-defined darkening overlay (0-100%)
                if darken_factor > 0:
                    overlay = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0))
                    overlay_alpha = Image.new('L', (CARD_WIDTH, CARD_HEIGHT), int(255 * darken_factor))
                    img = Image.composite(img, overlay, overlay_alpha)
                draw = ImageDraw.Draw(img)
                
                # Extract dominant color from banner for progress bar
                dominant_color = get_dominant_color(bg_img)
                # Create a darker version for progress bar background
                progress_bar_fill = dominant_color
                # Darken the dominant color for the background
                progress_bar_bg = tuple(max(0, int(c * 0.6)) for c in dominant_color)
        except:
            pass  # If background image fails, just use solid color
    
    # Try to load Anton font, fallback to default
    # Note: To use Anton font, place Anton-Regular.ttf in the 'fonts' directory or root directory
    # Download from: https://fonts.google.com/specimen/Anton
    # Font sizes: Canva size 12 = ~16px, size 8 = ~11px (scaled for 150 DPI)
    try:
        font_paths = [
            'fonts/Anton-Regular.ttf',
            'Anton-Regular.ttf',
            './fonts/Anton-Regular.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
            'C:/Windows/Fonts/arial.ttf',
        ]
        font_path_used = None
        for path in font_paths:
            try:
                if os.path.exists(path):
                    font_path_used = path
                    break
            except:
                continue
        
        if font_path_used:
            # Get user-defined font size (default 3x larger = 99px)
            # If user hasn't set a custom size, use 3x default (99px)
            custom_font_size = user_data.get('card_font_size')
            if custom_font_size is None:
                # Default: 3x larger than original (33px * 3 = 99px)
                main_font_size = 99
            else:
                # User has set a custom size, use it directly (clamped 5-999)
                main_font_size = int(max(5, min(999, custom_font_size)))
            about_font_size = int(main_font_size * 0.73)  # About 73% of main size for about me
            
            title_font = ImageFont.truetype(font_path_used, main_font_size)
            large_font = ImageFont.truetype(font_path_used, main_font_size)
            medium_font = ImageFont.truetype(font_path_used, main_font_size)
            small_font = ImageFont.truetype(font_path_used, main_font_size)
            about_font = ImageFont.truetype(font_path_used, about_font_size)
        else:
            # Fallback to default font
            title_font = ImageFont.load_default()
            large_font = ImageFont.load_default()
            medium_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
            about_font = ImageFont.load_default()
    except:
        title_font = ImageFont.load_default()
        large_font = ImageFont.load_default()
        medium_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
        about_font = ImageFont.load_default()
    
    # Draw profile picture box (red, large, rounded)
    # Scale elements for new dimensions
    scale_factor = CARD_WIDTH / 1000  # Scale from original 1000px width
    pfp_size = int(140 * scale_factor)  # ~231px
    pfp_x = CONTENT_X
    pfp_y = CONTENT_Y
    pfp_radius = int(20 * scale_factor)  # ~33px
    
    # Create rounded rectangle mask for profile picture
    pfp_mask = Image.new('L', (pfp_size, pfp_size), 0)
    pfp_mask_draw = ImageDraw.Draw(pfp_mask)
    pfp_mask_draw.rounded_rectangle([(0, 0), (pfp_size, pfp_size)], radius=pfp_radius, fill=255)
    
    # Try to load profile picture (custom or default)
    try:
        custom_pfp_url = user_data.get('custom_pfp_url')
        pfp_url = custom_pfp_url if custom_pfp_url else str(user.display_avatar.url)
        pfp_img = download_image(pfp_url, (pfp_size, pfp_size))
        if pfp_img:
            img.paste(pfp_img, (pfp_x, pfp_y), pfp_mask)
        else:
            draw.rounded_rectangle([(pfp_x, pfp_y), (pfp_x + pfp_size, pfp_y + pfp_size)], 
                                 radius=pfp_radius, fill=PROFILE_BOX_COLOR)
    except:
        draw.rounded_rectangle([(pfp_x, pfp_y), (pfp_x + pfp_size, pfp_y + pfp_size)], 
                             radius=pfp_radius, fill=PROFILE_BOX_COLOR)
    
    # Draw country flag box (green, small, rounded)
    flag_size = int(60 * scale_factor)  # ~99px
    flag_x = pfp_x + pfp_size + int(25 * scale_factor)
    flag_y = pfp_y
    flag_radius = int(12 * scale_factor)  # ~20px
    
    # Check for country flag (not in DB yet, use default)
    country_flag_url = user_data.get('country_flag_url')
    if country_flag_url:
        flag_img = download_image(country_flag_url, (flag_size, flag_size))
        if flag_img:
            flag_mask = Image.new('L', (flag_size, flag_size), 0)
            flag_mask_draw = ImageDraw.Draw(flag_mask)
            flag_mask_draw.rounded_rectangle([(0, 0), (flag_size, flag_size)], radius=flag_radius, fill=255)
            img.paste(flag_img, (flag_x, flag_y), flag_mask)
        else:
            draw.rounded_rectangle([(flag_x, flag_y), (flag_x + flag_size, flag_y + flag_size)], 
                                 radius=flag_radius, fill=COUNTRY_BOX_COLOR)
    else:
        draw.rounded_rectangle([(flag_x, flag_y), (flag_x + flag_size, flag_y + flag_size)], 
                             radius=flag_radius, fill=COUNTRY_BOX_COLOR)
    
    # Draw guild logo box (blue, small, rounded)
    guild_size = int(60 * scale_factor)  # ~99px
    guild_x = flag_x + flag_size + int(15 * scale_factor)
    guild_y = pfp_y
    guild_radius = int(12 * scale_factor)  # ~20px
    
    # Check for guild logo
    guild_icon_url = str(guild.icon.url) if guild.icon else None
    if guild_icon_url:
        guild_img = download_image(guild_icon_url, (guild_size, guild_size))
        if guild_img:
            guild_mask = Image.new('L', (guild_size, guild_size), 0)
            guild_mask_draw = ImageDraw.Draw(guild_mask)
            guild_mask_draw.rounded_rectangle([(0, 0), (guild_size, guild_size)], radius=guild_radius, fill=255)
            img.paste(guild_img, (guild_x, guild_y), guild_mask)
        else:
            draw.rounded_rectangle([(guild_x, guild_y), (guild_x + guild_size, guild_y + guild_size)], 
                                 radius=guild_radius, fill=GUILD_BOX_COLOR)
    else:
        draw.rounded_rectangle([(guild_x, guild_y), (guild_x + guild_size, guild_y + guild_size)], 
                             radius=guild_radius, fill=GUILD_BOX_COLOR)
    
    # Draw level text (top left)
    level = user_data.get('level', 0)
    level_text = f"lvl {level}"
    level_y = int(30 * scale_factor)
    draw.text((CONTENT_X, level_y), level_text, fill=TEXT_COLOR, font=title_font)
    
    # Draw rank text (top right)
    rank = get_user_rank(user.id, guild.id) or 0
    rank_text = f"#{rank}" if rank > 0 else "#-"
    rank_bbox = draw.textbbox((0, 0), rank_text, font=title_font)
    rank_width = rank_bbox[2] - rank_bbox[0]
    draw.text((CARD_WIDTH - rank_width - CONTENT_X, level_y), rank_text, fill=TEXT_COLOR, font=title_font)
    
    # Draw display name and username
    display_name = user.display_name or "-"
    username = user.name or "-"
    
    name_y = pfp_y + pfp_size + int(20 * scale_factor)
    draw.text((pfp_x, name_y), display_name, fill=TEXT_COLOR, font=large_font)
    draw.text((pfp_x, name_y + int(45 * scale_factor)), f"@{username}", fill=TEXT_GRAY, font=medium_font)
    
    # Calculate progress
    current_level = user_data.get('level', 0)
    next_level = current_level + 1
    next_req = LevelSystem.get_level_requirements(next_level) if next_level <= 100 else None
    
    if next_req:
        # Calculate progress percentage (average of all requirements)
        words_progress = min(1.0, user_data.get('unique_words', 0) / max(1, next_req.get('words', 1)))
        vc_progress = min(1.0, (user_data.get('vc_seconds', 0) / 60) / max(1, next_req.get('vc_minutes', 1)))
        messages_progress = min(1.0, user_data.get('messages_sent', 0) / max(1, next_req.get('messages', 1)))
        quests_progress = min(1.0, user_data.get('quests_completed', 0) / max(1, next_req.get('quests', 1)))
        overall_progress = (words_progress + vc_progress + messages_progress + quests_progress) / 4.0
    else:
        overall_progress = 1.0
    
    # Draw progress bar
    progress_y = name_y + int(100 * scale_factor)
    progress_x = pfp_x
    progress_width = int(700 * scale_factor)  # ~1155px
    progress_height = int(35 * scale_factor)  # ~58px
    progress_radius = int(10 * scale_factor)  # ~17px
    
    # Background bar (matches banner or default)
    draw.rounded_rectangle([(progress_x, progress_y), (progress_x + progress_width, progress_y + progress_height)], 
                         radius=progress_radius, fill=progress_bar_bg)
    
    # Filled bar (matches banner dominant color or default)
    fill_width = int(progress_width * overall_progress)
    if fill_width > 0:
        draw.rounded_rectangle([(progress_x, progress_y), (progress_x + fill_width, progress_y + progress_height)], 
                             radius=progress_radius, fill=progress_bar_fill)
    
    # Progress text (vertically centered)
    progress_text_bbox = draw.textbbox((0, 0), "Progress", font=small_font)
    progress_text_height = progress_text_bbox[3] - progress_text_bbox[1]
    progress_text_y = progress_y + (progress_height - progress_text_height) // 2
    draw.text((progress_x + int(15 * scale_factor), progress_text_y), "Progress", fill=TEXT_COLOR, font=small_font)
    
    # XP multiplier box
    multiplier = user_data.get('xp_multiplier', 1.0)
    # Calculate quest multipliers
    daily_quests = user_data.get('daily_quests_completed', 0)
    weekly_quests = user_data.get('weekly_quests_completed', 0)
    quest_multiplier = 1.0
    if daily_quests > 0:
        quest_multiplier += 0.1
    if weekly_quests > 0:
        quest_multiplier += 0.25
    total_multiplier = multiplier * quest_multiplier
    
    multiplier_text = f"{total_multiplier:.1f}x"
    multiplier_box_width = int(90 * scale_factor)
    multiplier_box_height = progress_height
    multiplier_x = progress_x + progress_width + int(25 * scale_factor)
    multiplier_y = progress_y
    
    draw.rounded_rectangle([(multiplier_x, multiplier_y), (multiplier_x + multiplier_box_width, multiplier_y + multiplier_box_height)], 
                         radius=progress_radius, fill=MULTIPLIER_BOX_COLOR)
    multiplier_bbox = draw.textbbox((0, 0), multiplier_text, font=small_font)
    multiplier_text_width = multiplier_bbox[2] - multiplier_bbox[0]
    multiplier_text_x = multiplier_x + (multiplier_box_width - multiplier_text_width) // 2
    multiplier_text_y = multiplier_y + int(8 * scale_factor)
    draw.text((multiplier_text_x, multiplier_text_y), multiplier_text, fill=TEXT_COLOR, font=small_font)
    
    # Draw stats section
    stats_start_y = progress_y + progress_height + int(50 * scale_factor)
    stats_x = pfp_x
    stat_spacing = int(55 * scale_factor)
    
    stats_labels = ["XP", "words", "messages", "vc", "quests"]
    
    # Overall/lifetime stats (for middle column display)
    overall_xp = user_data.get('xp', 0)
    overall_words = user_data.get('lifetime_words', user_data.get('unique_words', 0))  # Use lifetime if available
    overall_messages = user_data.get('messages_sent', 0)  # Current value (may be reset on level up)
    overall_vc = user_data.get('vc_seconds', 0) // 60  # Current value (may be reset on level up)
    overall_quests = user_data.get('quests_completed', 0)  # Current value (may be reset on level up)
    
    stats_values = [
        f"{overall_xp:,}",
        f"{overall_words:,}",
        f"{overall_messages:,}",
        f"{overall_vc:,}",
        f"{overall_quests:,}"
    ]
    
    # Current progress values (for right column - progress towards next level)
    # Note: These represent progress since last level up
    current_words = user_data.get('unique_words', 0)
    current_messages = user_data.get('messages_sent', 0)
    current_vc = user_data.get('vc_seconds', 0) // 60
    current_quests = user_data.get('quests_completed', 0)
    
    # Requirements for next level
    if next_req:
        # Calculate XP requirement (based on level requirements)
        xp_req = next_req.get('words', 0) * 10  # Approximate XP from words
        req_words = next_req.get('words', 0)
        req_messages = next_req.get('messages', 0)
        req_vc = next_req.get('vc_minutes', 0)
        req_quests = next_req.get('quests', 0)
        
        # Current progress towards requirements (capped at requirement)
        # Note: These are the values since last level up (for progress tracking)
        # For XP, we'll use a simple calculation based on words progress
        progress_xp = min(overall_xp, xp_req) if xp_req > 0 else overall_xp
        progress_words = min(current_words, req_words) if req_words > 0 else current_words
        progress_messages = min(current_messages, req_messages) if req_messages > 0 else current_messages
        progress_vc = min(current_vc, req_vc) if req_vc > 0 else current_vc
        progress_quests = min(current_quests, req_quests) if req_quests > 0 else current_quests
        
        stats_requirements = [
            (f"{progress_xp:,}", f"{xp_req:,}"),
            (f"{progress_words:,}", f"{req_words:,}"),
            (f"{progress_messages:,}", f"{req_messages:,}"),
            (f"{progress_vc:,}", f"{req_vc:,}"),
            (f"{progress_quests:,}", f"{req_quests:,}")
        ]
    else:
        # Max level reached
        stats_requirements = [("-", "-")] * 5
    
    for i, (label, value, (progress, req)) in enumerate(zip(stats_labels, stats_values, stats_requirements)):
        y_pos = stats_start_y + (i * stat_spacing)
        
        # Label
        draw.text((stats_x, y_pos), label, fill=TEXT_COLOR, font=small_font)
        
        # Value (overall stat)
        value_x = stats_x + int(150 * scale_factor)
        draw.text((value_x, y_pos), value, fill=TEXT_COLOR, font=small_font)
        
        # Separator and requirement (progress / requirement)
        req_x = value_x + int(150 * scale_factor)
        draw.text((req_x, y_pos), "]", fill=TEXT_COLOR, font=small_font)
        req_text = f"{progress} / {req}"
        draw.text((req_x + int(25 * scale_factor), y_pos), req_text, fill=TEXT_COLOR, font=small_font)
    
    # Draw "About me" section
    about_y = stats_start_y + (len(stats_labels) * stat_spacing) + int(40 * scale_factor)
    about_x = pfp_x
    
    # Message icon (white/black rounded box based on background)
    icon_size = int(35 * scale_factor)
    icon_radius = int(6 * scale_factor)
    icon_color = (0, 0, 0) if is_light_bg else (255, 255, 255)
    draw.rounded_rectangle([(about_x, about_y), (about_x + icon_size, about_y + icon_size)], 
                         radius=icon_radius, fill=icon_color)
    
    # "Abouts me" title
    about_title_x = about_x + icon_size + int(12 * scale_factor)
    draw.text((about_title_x, about_y), "Abouts me", fill=TEXT_COLOR, font=medium_font)
    
    # About me text
    about_text = user_data.get('about_me', '') or ''
    if about_text:
        # Wrap text if too long
        max_width = CONTENT_WIDTH - int(40 * scale_factor)
        words = about_text.split()
        lines = []
        current_line = []
        current_width = 0
        
        for word in words:
            word_bbox = draw.textbbox((0, 0), word + " ", font=about_font)
            word_width = word_bbox[2] - word_bbox[0]
            if current_width + word_width > max_width and current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
                current_width = word_width
            else:
                current_line.append(word)
                current_width += word_width
        
        if current_line:
            lines.append(" ".join(current_line))
        
        about_text_y = about_y + int(40 * scale_factor)
        line_height = int(28 * scale_factor)
        for line in lines[:3]:  # Limit to 3 lines
            draw.text((about_x, about_text_y), line, fill=TEXT_GRAY, font=about_font)
            about_text_y += line_height
    
    # Convert to bytes
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes


@bot.command(name='me')
async def me_cmd(ctx, action: str = None, *, value: str = None):
    """Profile card commands. Use: %me [banner <url>|color <hex>|about <text>] or just %me [@user] to view"""
    
    # Handle subcommands first
    if action == 'banner':
        if not value:
            await ctx.send("❌ Please provide an image URL: `%me banner <image_url>`")
            return
        
        if not value.startswith(('http://', 'https://')):
            await ctx.send("❌ Please provide a valid image URL!")
            return
        
        # Update background_url for profile card
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''UPDATE users SET background_url = ? WHERE user_id = ? AND guild_id = ?''',
                  (value, ctx.author.id, ctx.guild.id))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="✅ Profile Card Banner Updated!",
                              description="Your profile card background image has been set.",
                              color=discord.Color.green())
        embed.set_image(url=value)
        await ctx.send(embed=embed)
        return
    
    elif action == 'color':
        if not value:
            await ctx.send("❌ Please provide a hex color: `%me color #FF5733`")
            return
        
        # Validate hex color
        hex_color = value.strip()
        if not hex_color.startswith('#'):
            hex_color = '#' + hex_color
        
        if not re.match(r'^#[0-9A-Fa-f]{6}$', hex_color):
            await ctx.send("❌ Invalid hex color! Use format: `#FF5733` or `FF5733`")
            return
        
        # Update profile_card_bg_color
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''UPDATE users SET profile_card_bg_color = ? WHERE user_id = ? AND guild_id = ?''',
                  (hex_color, ctx.author.id, ctx.guild.id))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="✅ Profile Card Color Updated!",
                              description=f"Your profile card background color has been set to `{hex_color}`.",
                              color=discord.Color.from_str(hex_color))
        await ctx.send(embed=embed)
        return
    
    elif action == 'about':
        if value is None:
            await ctx.send("❌ Please provide your about me text: `%me about <your text>`")
            return
        
        # Update about_me
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''UPDATE users SET about_me = ? WHERE user_id = ? AND guild_id = ?''',
                  (value, ctx.author.id, ctx.guild.id))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="✅ About Me Updated!",
                              description="Your profile card about me section has been updated.",
                              color=discord.Color.green())
        await ctx.send(embed=embed)
        return
    
    elif action == 'brightness':
        if not value:
            await ctx.send("❌ Please provide a brightness value (0-100): `%me brightness 20`")
            return
        
        try:
            brightness = float(value)
            if brightness < 0 or brightness > 100:
                await ctx.send("❌ Brightness must be between 0 and 100!")
                return
            
            # Update banner_brightness
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''UPDATE users SET banner_brightness = ? WHERE user_id = ? AND guild_id = ?''',
                      (brightness, ctx.author.id, ctx.guild.id))
            conn.commit()
            conn.close()
            
            embed = discord.Embed(title="✅ Banner Brightness Updated!",
                                  description=f"Your banner darkness has been set to {brightness}%.",
                                  color=discord.Color.green())
            await ctx.send(embed=embed)
            return
        except ValueError:
            await ctx.send("❌ Please provide a valid number between 0 and 100!")
            return
    
    elif action == 'padding':
        if not value:
            await ctx.send("❌ Please provide a padding multiplier: `%me padding 1.5`")
            return
        
        try:
            padding = float(value)
            if padding < 0.1 or padding > 10:
                await ctx.send("❌ Padding multiplier must be between 0.1 and 10!")
                return
            
            # Update card_padding
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''UPDATE users SET card_padding = ? WHERE user_id = ? AND guild_id = ?''',
                      (padding, ctx.author.id, ctx.guild.id))
            conn.commit()
            conn.close()
            
            embed = discord.Embed(title="✅ Card Padding Updated!",
                                  description=f"Your card padding has been set to {padding}x.",
                                  color=discord.Color.green())
            await ctx.send(embed=embed)
            return
        except ValueError:
            await ctx.send("❌ Please provide a valid number!")
            return
    
    elif action == 'fontsize':
        if not value:
            await ctx.send("❌ Please provide a font size (5-999): `%me fontsize 50`")
            return
        
        try:
            font_size = float(value)
            if font_size < 5 or font_size > 999:
                await ctx.send("❌ Font size must be between 5 and 999!")
                return
            
            # Update card_font_size
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''UPDATE users SET card_font_size = ? WHERE user_id = ? AND guild_id = ?''',
                      (font_size, ctx.author.id, ctx.guild.id))
            conn.commit()
            conn.close()
            
            embed = discord.Embed(title="✅ Font Size Updated!",
                                  description=f"Your card font size has been set to {font_size}.",
                                  color=discord.Color.green())
            await ctx.send(embed=embed)
            return
        except ValueError:
            await ctx.send("❌ Please provide a valid number between 5 and 999!")
            return
    
    elif action == 'pfp':
        if not value:
            await ctx.send("❌ Please provide an image URL: `%me pfp <image_url>`")
            return
        
        if not value.startswith(('http://', 'https://')):
            await ctx.send("❌ Please provide a valid image URL!")
            return
        
        # Update custom_pfp_url
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''UPDATE users SET custom_pfp_url = ? WHERE user_id = ? AND guild_id = ?''',
                  (value, ctx.author.id, ctx.guild.id))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="✅ Profile Picture Updated!",
                              description="Your profile card picture has been set.",
                              color=discord.Color.green())
        embed.set_image(url=value)
        await ctx.send(embed=embed)
        return
    
    # Default: Show profile card
    # Check if a member was mentioned in the message
    target = ctx.author
    if ctx.message.mentions:
        target = ctx.message.mentions[0]
    elif action and action not in ['banner', 'color', 'about', 'brightness', 'padding', 'fontsize', 'pfp']:
        # Try to parse action as member mention
        try:
            target = await commands.MemberConverter().convert(ctx, action)
        except:
            target = ctx.author
    
    # Get target's data
    target_data = get_user_data(target.id, ctx.guild.id)
    if not target_data:
        embed = discord.Embed(
            title=f"{target.display_name}'s Profile",
            description="No data yet! Start chatting to begin your quest.",
            color=discord.Color.blurple())
        await ctx.send(embed=embed)
        return
    
    # Generate profile card
    try:
        card_image = generate_profile_card(target, target_data, ctx.guild)
        file = discord.File(card_image, filename='profile_card.png')
        await ctx.send(file=file)
    except Exception as e:
        # Fallback to embed if image generation fails
        await ctx.send(f"❌ Error generating profile card: {str(e)}")
        await profile_cmd(ctx, target if target != ctx.author else None)


@bot.command(name='vctest')
async def vc_test_cmd(ctx):
    """Test your VC time tracking"""
    user_data = get_user_data(ctx.author.id, ctx.guild.id)

    if not user_data:
        await ctx.send("❌ No data found. Join a voice channel first!")
        return

    embed = discord.Embed(title="🎧 VC Time Test", color=discord.Color.blue())

    embed.add_field(name="Total VC Seconds",
                    value=f"{user_data['vc_seconds']}s",
                    inline=True)
    embed.add_field(name="Total VC Minutes",
                    value=f"{user_data['vc_seconds']//60}m",
                    inline=True)
    embed.add_field(name="Total VC Hours",
                    value=f"{user_data['vc_seconds']//3600}h",
                    inline=True)

    # Check active sessions
    conn = get_db_connection()
    active_sessions = conn.execute(
        '''SELECT COUNT(*) FROM voice_sessions 
                                    WHERE user_id = ? AND guild_id = ? AND leave_time IS NULL''',
        (ctx.author.id, ctx.guild.id)).fetchone()[0]
    conn.close()

    embed.add_field(name="Active Sessions",
                    value=active_sessions,
                    inline=False)
    embed.set_footer(text="Join/leave a VC to test tracking")

    await ctx.send(embed=embed)


@bot.command(name='debug')
async def debug_cmd(ctx):
    user_data = get_user_data(ctx.author.id, ctx.guild.id)

    if not user_data:
        await ctx.send("❌ No user data found. Have you sent any messages?")
        return

    embed = discord.Embed(title="🔧 Debug Information",
                          color=discord.Color.orange())

    embed.add_field(name="Level", value=user_data['level'], inline=True)
    embed.add_field(name="Messages",
                    value=user_data['messages_sent'],
                    inline=True)
    embed.add_field(name="Channels",
                    value=user_data['channels_used'],
                    inline=True)

    embed.add_field(
        name="Word Stats",
        value=
        f"Unique Words: {user_data['unique_words']}\nLifetime Words: {user_data['lifetime_words']}",
        inline=False)

    embed.add_field(
        name="VC Stats",
        value=
        f"VC Seconds: {user_data['vc_seconds']}\nVC Minutes: {user_data['vc_seconds']//60}",
        inline=False)

    current_level = user_data['level']
    next_req = LevelSystem.get_level_requirements(current_level + 1)

    embed.add_field(
        name=f"Progress to Level {current_level + 1}",
        value=f"Words: {user_data['unique_words']}/{next_req['words']}\n"
        f"Messages: {user_data['messages_sent']}/{next_req['messages']}\n"
        f"VC: {user_data['vc_seconds']//60}/{next_req['vc_minutes']}m\n"
        f"Quests: {user_data['quests_completed']}/{next_req['quests']}",
        inline=False)

    await ctx.send(embed=embed)


@bot.command(name='forcevc')
async def force_vc_cmd(ctx, seconds: int):
    """Force add VC time for testing (owner only)"""
    if ctx.author.id != YOUR_USER_ID_HERE:  # Replace with your Discord ID
        await ctx.send("❌ This command is for bot owner only!")
        return

    user_data = get_user_data(ctx.author.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(ctx.author.id, ctx.guild.id)

    user_data['vc_seconds'] += seconds
    update_user_data(user_data)

    await ctx.send(
        f"✅ Added {seconds} seconds of VC time! Total: {user_data['vc_seconds']//60} minutes"
    )


# Add other essential commands
@bot.command(name='banner')
async def banner_cmd(ctx, image_url: str = None):
    user_data = get_user_data(ctx.author.id, ctx.guild.id)

    if not user_data or user_data['level'] < 1:
        await ctx.send("❌ You need to be at least Level 1 to set a banner!")
        return

    if not image_url:
        await ctx.send("❌ Please provide an image URL: `%banner <image_url>`")
        return

    if not image_url.startswith(('http://', 'https://')):
        await ctx.send("❌ Please provide a valid image URL!")
        return

    user_data['banner_url'] = image_url
    update_user_data(user_data)

    embed = discord.Embed(title="✅ Banner Updated!",
                          description="Your profile banner has been set.",
                          color=discord.Color.green())
    embed.set_image(url=image_url)
    await ctx.send(embed=embed)


@bot.command(name='color')
async def color_cmd(ctx, hex_color: str):
    if not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', hex_color):
        await ctx.send("❌ Please provide a valid hex color (e.g., #5865F2)")
        return

    user_data = get_user_data(ctx.author.id, ctx.guild.id)
    if user_data:
        user_data['custom_color'] = hex_color
        update_user_data(user_data)

        embed = discord.Embed(
            title="✅ Color Updated!",
            description=f"Your profile color has been set to {hex_color}",
            color=discord.Color.from_str(hex_color))
        await ctx.send(embed=embed)


@bot.command(name='leaderboard', aliases=['lb'])
async def leaderboard_cmd(ctx, category: str = "overall", page: int = 1):
    """Optimized leaderboard with pagination - Usage: %leaderboard [category] [page]"""
    
    # Validate page number
    if page < 1:
        page = 1
    
    # Calculate offset for pagination (10 users per page)
    per_page = 10
    offset = (page - 1) * per_page
    
    conn = get_db_connection()

    # Get total count for the category
    if category == "words":
        # Uses idx_users_words index
        total_count = conn.execute(
            '''SELECT COUNT(*) FROM users WHERE guild_id = ? AND unique_words > 0''',
            (ctx.guild.id,)).fetchone()[0]
        results = conn.execute(
            '''SELECT user_id, unique_words FROM users 
                               WHERE guild_id = ? AND unique_words > 0
                               ORDER BY unique_words DESC LIMIT ? OFFSET ?''',
            (ctx.guild.id, per_page, offset)).fetchall()
        title = "📊 Word Leaderboard"
        value_key = "unique_words"
    elif category == "vc":
        # Uses idx_users_vc index
        total_count = conn.execute(
            '''SELECT COUNT(*) FROM users WHERE guild_id = ? AND vc_seconds > 0''',
            (ctx.guild.id,)).fetchone()[0]
        results = conn.execute(
            '''SELECT user_id, vc_seconds FROM users 
                               WHERE guild_id = ? AND vc_seconds > 0
                               ORDER BY vc_seconds DESC LIMIT ? OFFSET ?''',
            (ctx.guild.id, per_page, offset)).fetchall()
        title = "🎧 VC Time Leaderboard"
        value_key = "vc_seconds"
    elif category == "quests":
        # Uses idx_users_quests index
        total_count = conn.execute(
            '''SELECT COUNT(*) FROM users WHERE guild_id = ? AND quests_completed > 0''',
            (ctx.guild.id,)).fetchone()[0]
        results = conn.execute(
            '''SELECT user_id, quests_completed FROM users 
                               WHERE guild_id = ? AND quests_completed > 0
                               ORDER BY quests_completed DESC LIMIT ? OFFSET ?''',
            (ctx.guild.id, per_page, offset)).fetchall()
        title = "🎯 Quests Leaderboard"
        value_key = "quests_completed"
    elif category == "xp":
        # Uses idx_users_xp index
        total_count = conn.execute(
            '''SELECT COUNT(*) FROM users WHERE guild_id = ? AND xp > 0''',
            (ctx.guild.id,)).fetchone()[0]
        results = conn.execute(
            '''SELECT user_id, xp FROM users 
                               WHERE guild_id = ? AND xp > 0
                               ORDER BY xp DESC LIMIT ? OFFSET ?''',
            (ctx.guild.id, per_page, offset)).fetchall()
        title = "⭐ XP Leaderboard"
        value_key = "xp"
    else:
        # Uses idx_users_level index
        total_count = conn.execute(
            '''SELECT COUNT(*) FROM users WHERE guild_id = ?''',
            (ctx.guild.id,)).fetchone()[0]
        results = conn.execute(
            '''SELECT user_id, level, xp FROM users 
                               WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT ? OFFSET ?''',
            (ctx.guild.id, per_page, offset)).fetchall()
        title = "🏆 Overall Leaderboard"
        value_key = "level"

    conn.close()

    if not results:
        await ctx.send("❌ No data available for this page!")
        return

    # Calculate total pages
    total_pages = (total_count + per_page - 1) // per_page  # Ceiling division
    
    embed = discord.Embed(title=f"{title} - Page {page}/{total_pages}", color=discord.Color.gold())

    leaderboard_text = ""
    for i, row in enumerate(results):
        # Calculate actual rank based on page
        rank = offset + i + 1
        
        if category == "overall":
            user_id, level_val, xp_val = row
            value = level_val
        else:
            user_id, value = row
        
        user = ctx.guild.get_member(user_id)
        if user:
            if value_key == "vc_seconds":
                display_value = f"{value//60}m"
            elif value_key == "xp":
                display_value = f"{value:,}"
            else:
                display_value = str(value)

            # Only show medals for top 3 on first page
            if page == 1 and rank <= 3:
                medal = ["🥇", "🥈", "🥉"][rank - 1]
            else:
                medal = f"{rank}."
            
            leaderboard_text += f"{medal} {user.mention} - `{display_value}`\n"
        else:
            # Handle users who left the server
            if value_key == "vc_seconds":
                display_value = f"{value//60}m"
            elif value_key == "xp":
                display_value = f"{value:,}"
            else:
                display_value = str(value)
            
            if page == 1 and rank <= 3:
                medal = ["🥇", "🥈", "🥉"][rank - 1]
            else:
                medal = f"{rank}."
            
            leaderboard_text += f"{medal} `[Left Server]` - `{display_value}`\n"

    embed.description = leaderboard_text
    
    # Add navigation hints
    footer_text = f"Use %leaderboard {category} [page] to navigate"
    if page < total_pages:
        footer_text += f" • Next: %lb {category} {page + 1}"
    embed.set_footer(text=footer_text)
    
    await ctx.send(embed=embed)


@bot.command(name='version')
async def version_cmd(ctx):
    """Check the bot's current version"""
    embed = discord.Embed(
        title="🤖 Questuza Version",
        description=f"Current version: **{VERSION}**",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📅 Last Updated",
        value="Features added in this version:\n"
              "• Version command\n"
              "• Improved typo detection\n"
              "• Offline VC tracking\n"
              "• 5-hour VC session cap\n"
              "• Advanced quests with pagination",
        inline=False
    )
    embed.set_footer(text="Use %help for command list")
    await ctx.send(embed=embed)


@bot.command(name='help')
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🪢 Questuza Help",
        description=
        "A leveling bot focused on meaningful engagement and creative quests!",
        color=discord.Color.blurple())

    commands_list = {
        "%me [@user]": "View your profile card (image)",
        "%me banner <url>": "Set profile card background image",
        "%me color <hex>": "Set profile card background color",
        "%me brightness <0-100>": "Adjust banner darkness (0% = no darkening)",
        "%me padding <multiplier>": "Adjust card padding (default: 1.2x)",
        "%me fontsize <5-999>": "Adjust card font size (default: 33)",
        "%me pfp <url>": "Set custom profile picture for card",
        "%me about <text>": "Set your about me text",
        "%profile [user]": "View your or someone else's profile (embed)",
        "%quests [type] [page]": "View available quests (daily/weekly/achievement/special)",
        "%claim <quest_id>": "Manually claim quest reward (100% XP)",
        "%claimall": "Claim all completed quests at once (85% XP, 15% fee)",
        "%autoclaim [on/off/status]": "Toggle auto-claim (70% XP, 30% fee)",
        "%questprogress <quest_id>": "Check progress on a specific quest",
        "%vctest": "Test your VC time tracking",
        "%debug": "Check your current stats and progress",
        "%banner <url>": "Set profile banner for embed (Level 1+)",
        "%color <hex>": "Change profile color for embed",
        "%leaderboard [category] [page]": "View leaderboards (overall/words/vc/quests/xp)",
        "%version": "Check bot version and changelog",
        "%guide": "Learn how the bot works",
        "%admin help": "View admin-only commands"
    }

    embed.add_field(
        name="⏰ Quest Expiration",
        value="Unclaimed quests expire and silently auto-collect at 10% XP:\n"
              "• Daily quests: 24 hours\n"
              "• Weekly quests: 7 days\n"
              "• Claim manually for 100%, bulk claim for 85%, or auto-claim for 70%!",
        inline=False
    )

    for cmd, desc in commands_list.items():
        embed.add_field(name=cmd, value=desc, inline=False)

    embed.set_footer(
        text="Track unique words, VC time, and complete quests to level up!")
    await ctx.send(embed=embed)


@bot.command(name='guide')
async def guide_cmd(ctx):
    embed = discord.Embed(
        title="📚 Questuza Guide",
        description="How to level up and complete quests effectively",
        color=discord.Color.green())

    guide_text = """
    **📈 Leveling System**
    • Track **unique words** per message (minimum 2)
    • Time spent in **voice channels**
    • Complete **creative quests**
    • All activities contribute to XP

    **🎯 Quest System**
    • **Daily Quests** - Reset every day, earn 1.1x XP multiplier
    • **Weekly Quests** - Reset weekly, earn 1.25x XP multiplier
    • **Achievement Quests** - One-time permanent goals
    
    **💰 Claiming Rewards (4 Options)**
    1. **Manual Claim** (`%claim <quest_id>`): Get **100% XP** ✅ BEST!
    2. **Bulk Claim** (`%claimall`): Get **85% XP** (15% fee) - Claim all at once!
    3. **Auto-Claim** (`%autoclaim on`): Get **70% XP** (30% fee) - Instant & automatic
    4. **Expired Auto-Collection**: Get **10% XP** silently if unclaimed
       • Daily quests expire after 24 hours
       • Weekly quests expire after 7 days
    
    **💡 Best Strategy:** Claim manually one-by-one for maximum rewards!

    **🔥 XP Multipliers**
    • Complete daily quests: +0.1x (1.1x total)
    • Complete weekly quests: +0.25x (1.25x total)
    • Stack both for maximum gains!

    **🔤 Word Counting**
    • Only alphabetic words count
    • Duplicates in same message don't count
    • "hello hello" = 1 word
    • "Hello there!" = 2 words

    **🎧 Voice Chat Tracking**
    • Automatically tracks time in voice channels
    • Use `%vctest` to check your VC time
    • Time updates when you leave VC

    **🖼️ Profile Customization**
    • Level 1: Unlock banner
    • Custom colors anytime
    • Show off your progress!
    
    **🎨 Profile Card Commands (`%me`)**
    • `%me` - View your profile card (beautiful image!)
    • `%me banner <url>` - Set background image/GIF
    • `%me color <hex>` - Set background color
    • `%me brightness <0-100>` - Adjust banner darkness (0% = original image)
    • `%me padding <multiplier>` - Adjust card padding (default: 1.2x)
    • `%me fontsize <5-999>` - Adjust font size (default: 33)
    • `%me pfp <url>` - Set custom profile picture
    • `%me about <text>` - Set your about me text
    
    **💡 Tips:**
    • Profile cards are portrait-oriented (8x11 inches)
    • Progress bar color matches your banner automatically
    • Text color adapts to background brightness
    • All settings are separate from embed profile!
    """

    embed.description = guide_text
    await ctx.send(embed=embed)


@bot.command(name='admin')
async def admin_cmd(ctx, action: str = None):
    """Admin commands help"""
    if action != 'help':
        await ctx.send("❌ Use `%admin help` to view admin commands.")
        return
    
    # Check if user has administrator permissions
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to view this!")
        return
    
    embed = discord.Embed(
        title="🔐 Admin Commands",
        description="Commands available only to administrators",
        color=discord.Color.red())
    
    admin_commands = {
        "%synchistory [user]": "Sync message history for a user (admin only)",
        "%forcevc <user> <seconds>": "Force add VC time to a user (admin only)",
        "%forcelevel <user> <level>": "Force set a user's level (admin only)",
        "%forcexp <user> <amount>": "Force add XP to a user (admin only)",
        "%forcewords <user> <amount>": "Force add words to a user (admin only)",
        "%forcemessages <user> <amount>": "Force add messages to a user (admin only)",
        "%forcequests <user> <amount>": "Force add quests completed to a user (admin only)",
        "%trivia <action>": "Manage trivia questions and sessions (admin only)",
        "%testweekly [user]": "Test weekly quest reset (admin only)",
        "%testlevel [user]": "Test leveling system calculations (admin only)",
        "%testall [user]": "Run all tracker tests (admin only)",
    }
    
    for cmd, desc in admin_commands.items():
        embed.add_field(name=cmd, value=desc, inline=False)
    
    embed.set_footer(text="⚠️ Use these commands responsibly!")
    await ctx.send(embed=embed)


@bot.command(name='quests')
async def quests_cmd(ctx, quest_type: str = "all", page: int = 1):
    """View available quests with pagination - Usage: %quests [daily/weekly/achievement/special/all] [page]"""

    user_data = get_user_data(ctx.author.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(ctx.author.id, ctx.guild.id)

    # Validate page number
    if page < 1:
        page = 1

    # Get quests based on type
    if quest_type.lower() == "daily":
        quests = get_quests_by_type(QuestType.DAILY)
        title = "📅 Daily Quests"
        color = discord.Color.blue()
    elif quest_type.lower() == "weekly":
        quests = get_quests_by_type(QuestType.WEEKLY)
        title = "📆 Weekly Quests"
        color = discord.Color.purple()
    elif quest_type.lower() == "achievement":
        quests = get_quests_by_type(QuestType.ACHIEVEMENT)
        title = "🏆 Achievement Quests"
        color = discord.Color.gold()
    elif quest_type.lower() == "special":
        quests = get_quests_by_type(QuestType.SPECIAL)
        title = "💎 Special Quests"
        color = discord.Color.red()
    else:
        quests = get_all_quests()
        title = "🎯 All Available Quests"
        color = discord.Color.green()

    # Pagination setup
    quests_per_page = 5
    total_quests = len(quests)
    total_pages = (total_quests + quests_per_page - 1) // quests_per_page  # Ceiling division

    # Adjust page if out of bounds
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * quests_per_page
    end_idx = start_idx + quests_per_page
    page_quests = quests[start_idx:end_idx]

    embed = discord.Embed(
        title=f"{title} - Page {page}/{total_pages}",
        description="Complete quests to earn bonus XP!",
        color=color
    )

    # Group by completion status for this page
    completed_quests = []
    available_quests = []

    for quest in page_quests:
        progress = get_user_quest_progress(ctx.author.id, ctx.guild.id, quest.quest_id)
        if progress and progress['completed'] == 1:
            status = "✅ CLAIMED" if progress.get('claimed', 0) == 1 else "🎁 READY TO CLAIM"
            completed_quests.append((quest, status))
        else:
            available_quests.append(quest)

    # Show available quests
    if available_quests:
        for quest in available_quests:
            type_icon = {"daily": "📅", "weekly": "📆", "achievement": "🏆", "special": "💎"}.get(quest.quest_type.value, "🎯")
            embed.add_field(
                name=f"{quest.emoji} {quest.name} {type_icon}",
                value=f"{quest.description}\n**Reward:** {quest.xp_reward:,} XP\n**ID:** `{quest.quest_id}`",
                inline=False
            )

    # Show completed quests
    if completed_quests:
        completed_text = "\n".join([f"{q.emoji} {q.name} - {status}" for q, status in completed_quests])
        embed.add_field(
            name="Completed Quests",
            value=completed_text,
            inline=False
        )

    # Add navigation footer
    footer_text = f"Use %quests {quest_type} [page] to navigate"
    if page < total_pages:
        footer_text += f" • Next: %quests {quest_type} {page + 1}"
    embed.set_footer(text=footer_text)

    await ctx.send(embed=embed)


@bot.command(name='claim')
async def claim_cmd(ctx, quest_id: str = None):
    """Claim rewards for a completed quest"""
    if not quest_id:
        await ctx.send("❌ Please specify a quest ID! Example: `%claim daily_chatter`\nUse `%quests` to see available quests.")
        return
    
    quest = get_quest_by_id(quest_id)
    
    if not quest:
        # Find similar quest IDs
        all_quests = get_all_quests()
        quest_ids = [q.quest_id for q in all_quests]
        
        # Simple fuzzy matching
        similar_quest = None
        quest_id_lower = quest_id.lower()
        
        for qid in quest_ids:
            if quest_id_lower in qid.lower() or qid.lower() in quest_id_lower:
                similar_quest = qid
                break
        
        if similar_quest:
            embed = discord.Embed(
                title="🤔 Quest Not Found",
                description="I couldn't find that quest ID.",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="You typed:",
                value=f"`{quest_id}`",
                inline=False
            )
            embed.add_field(
                name="Did you mean:",
                value=f"`%claim {similar_quest}`",
                inline=False
            )
            embed.set_footer(text="Use %quests to see all available quest IDs")
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Quest not found! Use `%quests` to see available quests and their IDs.")
        return
    
    xp_reward = claim_quest_reward(ctx.author.id, ctx.guild.id, quest_id)
    
    if xp_reward is None:
        # Check if it's completed but not claimed
        progress = get_user_quest_progress(ctx.author.id, ctx.guild.id, quest_id)
        if progress and progress['completed'] == 1 and progress.get('claimed', 0) == 1:
            await ctx.send(f"❌ You've already claimed the reward for **{quest.name}**!")
        else:
            await ctx.send(f"❌ You haven't completed **{quest.name}** yet! Use `%questprogress {quest_id}` to check your progress.")
        return
    
    # Add XP to user
    user_data = get_user_data(ctx.author.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(ctx.author.id, ctx.guild.id)
    
    user_data['xp'] += xp_reward
    user_data['quests_completed'] += 1
    update_user_data(user_data)
    
    embed = discord.Embed(
        title="🎉 Quest Reward Claimed!",
        description=f"**{quest.name}** completed!",
        color=discord.Color.gold()
    )
    embed.add_field(name="XP Earned", value=f"+{xp_reward:,} XP", inline=True)
    embed.add_field(name="Total XP", value=f"{user_data['xp']:,} XP", inline=True)
    embed.add_field(name="Quests Completed", value=f"{user_data['quests_completed']}", inline=True)
    embed.set_footer(text=f"Quest ID: {quest_id}")
    
    await ctx.send(embed=embed)


@bot.command(name='claimall')
async def claimall_cmd(ctx):
    """Claim all completed quest rewards at once with a 15% fee"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Find all completed but unclaimed quests
    c.execute('''SELECT quest_id FROM quests_progress 
                 WHERE user_id = ? AND guild_id = ? AND completed = 1 AND claimed = 0''',
              (ctx.author.id, ctx.guild.id))
    unclaimed_quest_ids = [row[0] for row in c.fetchall()]
    conn.close()
    
    if not unclaimed_quest_ids:
        await ctx.send("❌ You don't have any unclaimed quest rewards!")
        return
    
    # Calculate rewards with 15% fee (85% received)
    total_base_xp = 0
    total_received_xp = 0
    claimed_quests = []
    
    user_data = get_user_data(ctx.author.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(ctx.author.id, ctx.guild.id)
    
    for quest_id in unclaimed_quest_ids:
        quest = get_quest_by_id(quest_id)
        if quest:
            xp_reward = claim_quest_reward(ctx.author.id, ctx.guild.id, quest_id)
            if xp_reward:
                reduced_xp = int(xp_reward * 0.85)  # 15% fee
                total_base_xp += xp_reward
                total_received_xp += reduced_xp
                claimed_quests.append((quest, reduced_xp))
                
                # Track quest completion for multipliers
                from quest_system import QuestType
                if quest.quest_type == QuestType.DAILY:
                    user_data['daily_quests_completed'] = user_data.get('daily_quests_completed', 0) + 1
                elif quest.quest_type == QuestType.WEEKLY:
                    user_data['weekly_quests_completed'] = user_data.get('weekly_quests_completed', 0) + 1
    
    if not claimed_quests:
        await ctx.send("❌ Failed to claim quest rewards. Please try again!")
        return
    
    # Add XP to user
    user_data['xp'] += total_received_xp
    user_data['quests_completed'] += len(claimed_quests)
    update_user_data(user_data)
    
    # Create summary embed
    embed = discord.Embed(
        title="🎉 Bulk Quest Claim Complete!",
        description=f"Successfully claimed **{len(claimed_quests)}** quest rewards!",
        color=discord.Color.gold()
    )
    
    # List claimed quests (max 10 to avoid embed limits)
    quest_list = "\n".join([f"{q.emoji} **{q.name}** - {xp:,} XP" for q, xp in claimed_quests[:10]])
    if len(claimed_quests) > 10:
        quest_list += f"\n... and {len(claimed_quests) - 10} more!"
    
    embed.add_field(name="Claimed Quests", value=quest_list, inline=False)
    embed.add_field(name="Total Base XP", value=f"{total_base_xp:,} XP", inline=True)
    embed.add_field(name="XP Received (85%)", value=f"+{total_received_xp:,} XP", inline=True)
    embed.add_field(name="Fee (15%)", value=f"-{total_base_xp - total_received_xp:,} XP", inline=True)
    embed.set_footer(text="💡 Tip: Claim quests individually with %claim <quest_id> for 100% XP!")
    
    await ctx.send(embed=embed)


@bot.command(name='autoclaim')
async def autoclaim_cmd(ctx, status: str = None):
    """Toggle auto-claim for quest rewards (70% XP due to 30% fee) - Usage: %autoclaim on/off/status"""
    user_data = get_user_data(ctx.author.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(ctx.author.id, ctx.guild.id)

    conn = get_db_connection()
    c = conn.cursor()

    # Get current autoclaim status
    c.execute('''SELECT autoclaim_enabled FROM users WHERE user_id = ? AND guild_id = ?''',
              (ctx.author.id, ctx.guild.id))
    result = c.fetchone()
    current_status = result[0] if result and result[0] is not None else 0

    if status is None or status.lower() == 'status':
        status_text = "✅ Enabled" if current_status else "❌ Disabled"
        embed = discord.Embed(
            title="⚙️ Auto-Claim Status",
            description=f"Auto-claim is currently: **{status_text}**",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="ℹ️ How it works",
            value="When enabled, quest rewards are automatically claimed with a **30% fee**.\n"
                  "You receive **70% of the quest XP** instantly upon completion.\n\n"
                  "**Example:** 1,000 XP quest → You get 700 XP automatically",
            inline=False
        )
        embed.add_field(
            name="💡 Commands",
            value="`%autoclaim on` - Enable auto-claim (70% XP)\n"
                  "`%autoclaim off` - Disable auto-claim (claim full 100% manually)\n"
                  "`%claimall` - Claim all at once (85% XP, 15% fee)",
            inline=False
        )
        conn.close()
        await ctx.send(embed=embed)
        return

    if status.lower() == 'on':
        c.execute('''UPDATE users SET autoclaim_enabled = 1
                     WHERE user_id = ? AND guild_id = ?''',
                  (ctx.author.id, ctx.guild.id))
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="✅ Auto-Claim Enabled!",
            description="Quest rewards will now be **automatically claimed with a 30% fee**.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="⚠️ Important",
            value="You will receive **70% of quest XP** automatically.\n"
                  "Use `%autoclaim off` to disable and claim full rewards manually.",
            inline=False
        )
        await ctx.send(embed=embed)

    elif status.lower() == 'off':
        c.execute('''UPDATE users SET autoclaim_enabled = 0
                     WHERE user_id = ? AND guild_id = ?''',
                  (ctx.author.id, ctx.guild.id))
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="🔒 Auto-Claim Disabled!",
            description="You must now **manually claim** quest rewards using `%claim <quest_id>`.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="💰 Benefit",
            value="Manual claims give you **100% of the quest XP** (no fee).",
            inline=False
        )
        await ctx.send(embed=embed)
    else:
        conn.close()
        await ctx.send("❌ Invalid option! Use `%autoclaim on`, `%autoclaim off`, or `%autoclaim status`")


@bot.command(name='createquest')
@commands.has_permissions(administrator=True)
async def create_quest_cmd(ctx, *, args: str = None):
    """Create a custom quest (Admin only) - Usage: %createquest <type> "<name>" "<description>" <xp> "<requirements>" [emoji]"""
    from quest_system import create_custom_quest, parse_requirements_string
    import shlex

    if not args:
        embed = discord.Embed(
            title="🎯 Create Custom Quest",
            description="Create a custom quest for your server!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Usage",
            value="`%createquest <type> \"<name>\" \"<description>\" <xp> \"<requirements>\" [emoji]`",
            inline=False
        )
        embed.add_field(
            name="Quest Types",
            value="`daily`, `weekly`, `achievement`, `special`",
            inline=True
        )
        embed.add_field(
            name="Requirements Format",
            value="`stat1:value1,stat2:value2`\nExample: `daily_messages:20,words:50`",
            inline=True
        )
        embed.add_field(
            name="Available Stats",
            value="`daily_messages`, `daily_words`, `daily_vc_minutes`, `daily_channels`, `daily_replies`\n`weekly_messages`, `weekly_words`, `weekly_vc_minutes`, `weekly_channels`, `weekly_active_days`\n`level`, `lifetime_words`, `total_vc_hours`, `messages_sent`, `channels_used`, `images_sent`",
            inline=False
        )
        await ctx.send(embed=embed)
        return

    try:
        # Parse the arguments using shell-like parsing to handle quotes
        parsed_args = shlex.split(args)
    except ValueError as e:
        await ctx.send(f"❌ Error parsing arguments: {e}\nMake sure to use quotes around name and description!")
        return

    if len(parsed_args) < 5:
        await ctx.send("❌ Not enough arguments! Need at least: type, name, description, xp, requirements")
        return

    quest_type = parsed_args[0].lower()
    name = parsed_args[1]
    description = parsed_args[2]

    try:
        xp_reward = int(parsed_args[3])
    except ValueError:
        await ctx.send("❌ XP reward must be a number!")
        return

    requirements_str = parsed_args[4]
    emoji = parsed_args[5] if len(parsed_args) > 5 else "🎯"

    # Validate quest type
    valid_types = ['daily', 'weekly', 'achievement', 'special']
    if quest_type not in valid_types:
        await ctx.send(f"❌ Invalid quest type! Valid types: {', '.join(valid_types)}")
        return

    # Validate XP reward
    if xp_reward <= 0 or xp_reward > 100000:
        await ctx.send("❌ XP reward must be between 1 and 100,000!")
        return

    # Parse requirements
    parsed_reqs = parse_requirements_string(requirements_str)
    if not parsed_reqs:
        await ctx.send("❌ Invalid requirements format! Use format: `stat1:value1,stat2:value2`\nExample: `daily_messages:20,words:50`")
        return

    # Generate unique quest ID
    quest_id = f"custom_{ctx.guild.id}_{int(datetime.datetime.now().timestamp())}"

    # Create the quest
    success = create_custom_quest(
        creator_id=ctx.author.id,
        guild_id=ctx.guild.id,
        quest_id=quest_id,
        name=name,
        description=description,
        quest_type=quest_type,
        xp_reward=xp_reward,
        requirements=parsed_reqs,
        emoji=emoji
    )

    if success:
        embed = discord.Embed(
            title="✅ Custom Quest Created!",
            description=f"**{name}** has been added to the quest system.",
            color=discord.Color.green()
        )
        embed.add_field(name="Quest ID", value=f"`{quest_id}`", inline=True)
        embed.add_field(name="Type", value=quest_type.title(), inline=True)
        embed.add_field(name="XP Reward", value=f"{xp_reward:,}", inline=True)
        embed.add_field(name="Requirements", value="\n".join([f"{k}: {v}" for k, v in parsed_reqs.items()]), inline=False)
        embed.set_footer(text=f"Created by {ctx.author.display_name}")
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Failed to create quest! Quest ID may already exist or invalid data provided.")


@bot.command(name='editquest')
@commands.has_permissions(administrator=True)
async def edit_quest_cmd(ctx, quest_id: str, field: str, *, value: str):
    """Edit a custom quest (Admin only) - Usage: %editquest <quest_id> <field> <value>"""
    from quest_system import edit_custom_quest

    valid_fields = ['name', 'description', 'xp_reward', 'requirements_json', 'emoji', 'enabled']
    if field not in valid_fields:
        await ctx.send(f"❌ Invalid field! Valid fields: {', '.join(valid_fields)}")
        return

    # Special validation for certain fields
    if field == 'xp_reward':
        try:
            int_value = int(value)
            if int_value <= 0 or int_value > 100000:
                await ctx.send("❌ XP reward must be between 1 and 100,000!")
                return
        except ValueError:
            await ctx.send("❌ XP reward must be a number!")
            return

    elif field == 'requirements_json':
        try:
            import json
            json.loads(value)
        except json.JSONDecodeError:
            await ctx.send("❌ Requirements must be valid JSON format!\nExample: `{\"daily_messages\": 20, \"words\": 50}`")
            return

    elif field == 'enabled':
        if value.lower() not in ['0', '1', 'true', 'false']:
            await ctx.send("❌ Enabled field must be 0/1 or true/false!")
            return
        value = '1' if value.lower() in ['1', 'true'] else '0'

    success = edit_custom_quest(ctx.guild.id, quest_id, field, value)

    if success:
        embed = discord.Embed(
            title="✅ Quest Updated!",
            description=f"**{quest_id}** has been updated.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Field", value=field, inline=True)
        embed.add_field(name="New Value", value=value[:100] + "..." if len(value) > 100 else value, inline=True)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Failed to update quest! Quest may not exist or invalid data provided.")


@bot.command(name='deletequest')
@commands.has_permissions(administrator=True)
async def delete_quest_cmd(ctx, quest_id: str):
    """Delete a custom quest (Admin only) - Usage: %deletequest <quest_id>"""
    from quest_system import delete_custom_quest

    # Confirm deletion
    embed = discord.Embed(
        title="⚠️ Confirm Deletion",
        description=f"Are you sure you want to delete quest **{quest_id}**?\n\nThis action cannot be undone!",
        color=discord.Color.red()
    )
    embed.add_field(name="To confirm", value=f"Reply with `yes` to delete or `no` to cancel.", inline=False)

    confirm_msg = await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']

    try:
        response = await bot.wait_for('message', check=check, timeout=30.0)
        if response.content.lower() == 'yes':
            success = delete_custom_quest(ctx.guild.id, quest_id)
            if success:
                embed = discord.Embed(
                    title="🗑️ Quest Deleted!",
                    description=f"**{quest_id}** has been permanently removed.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send("❌ Failed to delete quest! Quest may not exist.")
        else:
            await ctx.send("❌ Deletion cancelled.")
    except asyncio.TimeoutError:
        await ctx.send("❌ Deletion timed out. Quest was not deleted.")

    # Clean up confirmation message
    try:
        await confirm_msg.delete()
    except:
        pass


@bot.command(name='listcustomquests')
@commands.has_permissions(administrator=True)
async def list_custom_quests_cmd(ctx, page: int = 1):
    """List all custom quests in this guild (Admin only) - Usage: %listcustomquests [page]"""
    from quest_system import get_custom_quests

    quests = get_custom_quests(ctx.guild.id)

    if not quests:
        await ctx.send("❌ No custom quests found in this guild!")
        return

    # Pagination
    per_page = 5
    total_pages = (len(quests) + per_page - 1) // per_page
    if page < 1 or page > total_pages:
        page = 1

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_quests = quests[start_idx:end_idx]

    embed = discord.Embed(
        title=f"🎯 Custom Quests - Page {page}/{total_pages}",
        description=f"Total custom quests: {len(quests)}",
        color=discord.Color.purple()
    )

    for quest in page_quests:
        status = "✅ Enabled" if quest['enabled'] else "❌ Disabled"
        embed.add_field(
            name=f"{quest['emoji']} {quest['name']} ({status})",
            value=f"**ID:** `{quest['quest_id']}`\n"
                  f"**Type:** {quest['quest_type'].title()}\n"
                  f"**XP:** {quest['xp_reward']:,}\n"
                  f"**Description:** {quest['description'][:100]}{'...' if len(quest['description']) > 100 else ''}",
            inline=False
        )

    if total_pages > 1:
        embed.set_footer(text=f"Use %listcustomquests {page + 1} for next page")

    await ctx.send(embed=embed)


@bot.command(name='backup')
@commands.has_permissions(administrator=True)
async def backup_cmd(ctx):
    """Manually create a database backup (Admin only)"""
    try:
        backup_database()
        
        # Get list of backups
        import glob
        backups = sorted(glob.glob('backups/questuza_backup_*.db'), reverse=True)
        
        embed = discord.Embed(
            title="✅ Backup Created!",
            description=f"Database backed up successfully.\n\nTotal backups: {len(backups)}",
            color=discord.Color.green()
        )
        
        if backups:
            latest = backups[0].split('/')[-1]
            embed.add_field(name="Latest Backup", value=f"`{latest}`", inline=False)
        
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Backup failed: {e}")


@bot.command(name='listbackups')
@commands.has_permissions(administrator=True)
async def list_backups_cmd(ctx):
    """List all database backups (Admin only)"""
    import glob
    import os
    from datetime import datetime
    
    backups = sorted(glob.glob('backups/questuza_backup_*.db'), reverse=True)
    
    if not backups:
        await ctx.send("❌ No backups found!")
        return
    
    embed = discord.Embed(
        title="💾 Database Backups",
        description=f"Found {len(backups)} backup(s)",
        color=discord.Color.blue()
    )
    
    for i, backup in enumerate(backups[:10], 1):  # Show only last 10
        filename = backup.split('/')[-1]
        size = os.path.getsize(backup) / 1024  # KB
        timestamp = os.path.getctime(backup)
        date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        embed.add_field(
            name=f"{i}. {filename}",
            value=f"Size: {size:.1f} KB\nCreated: {date_str}",
            inline=False
        )
    
    await ctx.send(embed=embed)


@bot.command(name='questprogress')
async def quest_progress_cmd(ctx, quest_id: str = None):
    """View your progress on quests"""
    if not quest_id:
        await ctx.send("❌ Please specify a quest ID! Example: `%questprogress daily_chatter`")
        return

    quest = get_quest_by_id(quest_id)
    if not quest:
        await ctx.send("❌ Quest not found!")
        return

    user_data = get_user_data(ctx.author.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(ctx.author.id, ctx.guild.id)

    # Get current stats for progress calculation
    conn = get_db_connection()
    c = conn.cursor()
    today = datetime.date.today().isoformat()
    week_start = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()

    c.execute('''SELECT * FROM daily_stats WHERE user_id = ? AND guild_id = ? AND date = ?''',
              (ctx.author.id, ctx.guild.id, today))
    daily_stats = c.fetchone()
    daily_data = dict(daily_stats) if daily_stats else {}

    c.execute('''SELECT * FROM weekly_stats WHERE user_id = ? AND guild_id = ? AND week_start = ?''',
              (ctx.author.id, ctx.guild.id, week_start))
    weekly_stats = c.fetchone()
    weekly_data = dict(weekly_stats) if weekly_stats else {}
    conn.close()

    check_stats = {
        'daily_messages': daily_data.get('messages', 0),
        'daily_words': daily_data.get('words', 0),
        'daily_vc_minutes': daily_data.get('vc_minutes', 0),
        'daily_channels': daily_data.get('channels_used', 0),
        'daily_replies': daily_data.get('replies', 0),
        'weekly_messages': weekly_data.get('messages', 0),
        'weekly_words': weekly_data.get('words', 0),
        'weekly_vc_minutes': weekly_data.get('vc_minutes', 0),
        'weekly_channels': weekly_data.get('channels_used', 0),
        'weekly_active_days': weekly_data.get('active_days', 0),
        'level': user_data.get('level', 0),
        'lifetime_words': user_data.get('lifetime_words', 0),
        'total_vc_hours': user_data.get('vc_seconds', 0) // 3600,
        'messages_sent': user_data.get('messages_sent', 0),
        'channels_used': user_data.get('channels_used', 0),
        'images_sent': user_data.get('images_sent', 0),
    }

    progress = quest.get_progress(check_stats)

    embed = discord.Embed(
        title=f"{quest.emoji} {quest.name}",
        description=quest.description,
        color=discord.Color.blue()
    )

    for stat, data in progress.items():
        bar_length = 10
        filled = int((data['percentage'] / 100) * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)

        embed.add_field(
            name=stat.replace('_', ' ').title(),
            value=f"{bar} {data['percentage']}%\n{data['current']}/{data['required']}",
            inline=False
        )

    embed.add_field(name="Reward", value=f"{quest.xp_reward:,} XP", inline=True)
    embed.add_field(name="Type", value=quest.quest_type.value.title(), inline=True)

    await ctx.send(embed=embed)


@bot.command(name='testmessages')
async def test_messages_cmd(ctx, member: discord.Member = None):
    """Test message tracking system"""
    target = member or ctx.author
    user_data = get_user_data(target.id, ctx.guild.id)

    if not user_data:
        await ctx.send(f"❌ No data found for {target.mention}")
        return

    embed = discord.Embed(
        title="🧪 Message Tracking Test",
        description=f"Testing message stats for {target.mention}",
        color=discord.Color.blue()
    )

    embed.add_field(name="Messages Sent", value=f"{user_data['messages_sent']:,}", inline=True)
    embed.add_field(name="Unique Words", value=f"{user_data['unique_words']:,}", inline=True)
    embed.add_field(name="Lifetime Words", value=f"{user_data['lifetime_words']:,}", inline=True)

    # Calculate expected XP from words
    expected_xp = user_data['lifetime_words'] * 10
    embed.add_field(name="Expected XP from Words", value=f"{expected_xp:,}", inline=True)
    embed.add_field(name="Actual XP", value=f"{user_data['xp']:,}", inline=True)

    # Check for discrepancies
    if abs(expected_xp - user_data['xp']) > 1000:  # Allow some variance
        embed.add_field(name="⚠️ Warning", value="XP calculation may be off!", inline=False)

    await ctx.send(embed=embed)


@bot.command(name='testchannels')
async def test_channels_cmd(ctx, member: discord.Member = None):
    """Test channel tracking system"""
    target = member or ctx.author
    user_data = get_user_data(target.id, ctx.guild.id)

    if not user_data:
        await ctx.send(f"❌ No data found for {target.mention}")
        return

    conn = get_db_connection()
    c = conn.cursor()

    # Get daily channels for today
    today = datetime.date.today().isoformat()
    c.execute('''SELECT COUNT(*) FROM daily_channels
                 WHERE user_id = ? AND guild_id = ? AND date = ?''',
              (target.id, ctx.guild.id, today))
    daily_channels = c.fetchone()[0]

    # Get total unique channels
    c.execute('''SELECT COUNT(*) FROM user_channels
                 WHERE user_id = ? AND guild_id = ?''',
              (target.id, ctx.guild.id))
    total_channels = c.fetchone()[0]

    conn.close()

    embed = discord.Embed(
        title="🧪 Channel Tracking Test",
        description=f"Testing channel stats for {target.mention}",
        color=discord.Color.green()
    )

    embed.add_field(name="Total Unique Channels", value=f"{user_data['channels_used']:,}", inline=True)
    embed.add_field(name="Daily Channels Today", value=f"{daily_channels:,}", inline=True)
    embed.add_field(name="Database Total Channels", value=f"{total_channels:,}", inline=True)

    # Check for discrepancies
    if user_data['channels_used'] != total_channels:
        embed.add_field(name="⚠️ Warning", value="Channel count mismatch!", inline=False)

    await ctx.send(embed=embed)


@bot.command(name='testimages')
async def test_images_cmd(ctx, member: discord.Member = None):
    """Test image tracking system"""
    target = member or ctx.author
    user_data = get_user_data(target.id, ctx.guild.id)

    if not user_data:
        await ctx.send(f"❌ No data found for {target.mention}")
        return

    embed = discord.Embed(
        title="🧪 Image Tracking Test",
        description=f"Testing image stats for {target.mention}",
        color=discord.Color.purple()
    )

    embed.add_field(name="Images Sent", value=f"{user_data['images_sent']:,}", inline=True)

    await ctx.send(embed=embed)


@bot.command(name='testdaily')
async def test_daily_cmd(ctx, member: discord.Member = None):
    """Test daily stats tracking"""
    target = member or ctx.author

    conn = get_db_connection()
    c = conn.cursor()
    today = datetime.date.today().isoformat()

    c.execute('''SELECT * FROM daily_stats WHERE user_id = ? AND guild_id = ? AND date = ?''',
              (target.id, ctx.guild.id, today))
    daily_stats = c.fetchone()
    conn.close()

    embed = discord.Embed(
        title="🧪 Daily Stats Test",
        description=f"Testing daily stats for {target.mention} (Today)",
        color=discord.Color.orange()
    )

    if daily_stats:
        daily_data = dict(daily_stats)
        embed.add_field(name="Messages", value=f"{daily_data.get('messages', 0):,}", inline=True)
        embed.add_field(name="Words", value=f"{daily_data.get('words', 0):,}", inline=True)
        embed.add_field(name="VC Minutes", value=f"{daily_data.get('vc_minutes', 0):,}", inline=True)
        embed.add_field(name="Channels Used", value=f"{daily_data.get('channels_used', 0):,}", inline=True)
        embed.add_field(name="Replies", value=f"{daily_data.get('replies', 0):,}", inline=True)
    else:
        embed.add_field(name="Status", value="No daily stats found for today", inline=False)

    await ctx.send(embed=embed)


@bot.command(name='testweekly')
async def test_weekly_cmd(ctx, member: discord.Member = None):
    """Test weekly stats tracking"""
    target = member or ctx.author

    conn = get_db_connection()
    c = conn.cursor()
    week_start = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()

    c.execute('''SELECT * FROM weekly_stats WHERE user_id = ? AND guild_id = ? AND week_start = ?''',
              (target.id, ctx.guild.id, week_start))
    weekly_stats = c.fetchone()
    conn.close()

    embed = discord.Embed(
        title="🧪 Weekly Stats Test",
        description=f"Testing weekly stats for {target.mention} (This Week)",
        color=discord.Color.red()
    )

    if weekly_stats:
        weekly_data = dict(weekly_stats)
        embed.add_field(name="Messages", value=f"{weekly_data.get('messages', 0):,}", inline=True)
        embed.add_field(name="Words", value=f"{weekly_data.get('words', 0):,}", inline=True)
        embed.add_field(name="VC Minutes", value=f"{weekly_data.get('vc_minutes', 0):,}", inline=True)
        embed.add_field(name="Channels Used", value=f"{weekly_data.get('channels_used', 0):,}", inline=True)
        embed.add_field(name="Active Days", value=f"{weekly_data.get('active_days', 0):,}", inline=True)
    else:
        embed.add_field(name="Status", value="No weekly stats found for this week", inline=False)

    await ctx.send(embed=embed)


@bot.command(name='testlevel')
async def test_level_cmd(ctx, member: discord.Member = None):
    """Test leveling system calculations"""
    target = member or ctx.author
    user_data = get_user_data(target.id, ctx.guild.id)

    if not user_data:
        await ctx.send(f"❌ No data found for {target.mention}")
        return

    current_level = user_data['level']
    next_level = current_level + 1

    embed = discord.Embed(
        title="🧪 Leveling System Test",
        description=f"Testing level calculations for {target.mention}",
        color=discord.Color.gold()
    )

    embed.add_field(name="Current Level", value=user_data['level'], inline=True)
    embed.add_field(name="Unique Words", value=f"{user_data['unique_words']:,}", inline=True)
    embed.add_field(name="VC Seconds", value=f"{user_data['vc_seconds']:,}", inline=True)
    embed.add_field(name="Messages Sent", value=f"{user_data['messages_sent']:,}", inline=True)
    embed.add_field(name="Quests Completed", value=user_data['quests_completed'], inline=True)

    if next_level <= 100:
        req = LevelSystem.get_level_requirements(next_level)
        embed.add_field(
            name=f"Next Level ({next_level}) Requirements",
            value=f"Words: {req['words']:,}\nVC: {req['vc_minutes']}m\nMsgs: {req['messages']:,}\nQuests: {req['quests']}",
            inline=False
        )

        # Check if ready to level up
        words_ok = user_data['unique_words'] >= req['words']
        vc_ok = user_data['vc_seconds'] >= (req['vc_minutes'] * 60)
        msgs_ok = user_data['messages_sent'] >= req['messages']
        quests_ok = user_data['quests_completed'] >= req['quests']

        status = "✅ Ready to level up!" if all([words_ok, vc_ok, msgs_ok, quests_ok]) else "⏳ Not ready yet"
        embed.add_field(name="Level Up Status", value=status, inline=False)
    else:
        embed.add_field(name="Status", value="Max level reached!", inline=False)

    await ctx.send(embed=embed)


@bot.command(name='testall')
async def test_all_cmd(ctx, member: discord.Member = None):
    """Run all tracker tests at once"""
    target = member or ctx.author

    embed = discord.Embed(
        title="🧪 Complete Tracker Test Suite",
        description=f"Running all tests for {target.mention}",
        color=discord.Color.teal()
    )

    # Test messages
    user_data = get_user_data(target.id, ctx.guild.id)
    if user_data:
        embed.add_field(name="📝 Messages", value=f"Sent: {user_data['messages_sent']:,}", inline=True)
        embed.add_field(name="📚 Words", value=f"Unique: {user_data['unique_words']:,}", inline=True)
        embed.add_field(name="🖼️ Images", value=f"Sent: {user_data['images_sent']:,}", inline=True)
        embed.add_field(name="🎯 Level", value=user_data['level'], inline=True)

    # Test daily stats
    conn = get_db_connection()
    c = conn.cursor()
    today = datetime.date.today().isoformat()

    c.execute('''SELECT * FROM daily_stats WHERE user_id = ? AND guild_id = ? AND date = ?''',
              (target.id, ctx.guild.id, today))
    daily_stats = c.fetchone()

    if daily_stats:
        daily_data = dict(daily_stats)
        embed.add_field(name="📅 Daily", value=f"Msgs: {daily_data.get('messages', 0):,}", inline=True)
        embed.add_field(name="📅 Daily Channels", value=f"{daily_data.get('channels_used', 0):,}", inline=True)

    # Test weekly stats
    week_start = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
    c.execute('''SELECT * FROM weekly_stats WHERE user_id = ? AND guild_id = ? AND week_start = ?''',
              (target.id, ctx.guild.id, week_start))
    weekly_stats = c.fetchone()

    if weekly_stats:
        weekly_data = dict(weekly_stats)
        embed.add_field(name="📆 Weekly", value=f"Msgs: {weekly_data.get('messages', 0):,}", inline=True)
        embed.add_field(name="📆 Active Days", value=f"{weekly_data.get('active_days', 0):,}", inline=True)

    # Test VC
    c.execute('''SELECT COUNT(*) FROM voice_sessions
                 WHERE user_id = ? AND guild_id = ? AND leave_time IS NULL''',
              (target.id, ctx.guild.id))
    active_sessions = c.fetchone()[0]

    embed.add_field(name="🎧 VC", value=f"Seconds: {user_data['vc_seconds']:,}", inline=True)
    embed.add_field(name="🎧 Active Sessions", value=active_sessions, inline=True)

    conn.close()

    embed.set_footer(text="All tracker tests completed")
    await ctx.send(embed=embed)


# Manual Stat Editor Commands - Only for user 942963169071079504

def is_authorized():
    def predicate(ctx):
        return ctx.author.id == 942963169071079504
    return commands.check(predicate)

async def confirm_edit(ctx, target, stat_name, current_value, new_value):
    """Helper function to confirm stat edits"""
    embed = discord.Embed(
        title="⚠️ Confirm Stat Edit",
        description=f"Are you sure you want to change {target.mention}'s {stat_name}?",
        color=discord.Color.orange()
    )
    embed.add_field(name="Current Value", value=f"{current_value:,}", inline=True)
    embed.add_field(name="New Value", value=f"{new_value:,}", inline=True)
    embed.set_footer(text="Type 'yes' to confirm or 'no' to cancel")

    confirm_msg = await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']

    try:
        response = await bot.wait_for('message', check=check, timeout=30.0)
        await confirm_msg.delete()
        return response.content.lower() == 'yes'
    except asyncio.TimeoutError:
        await confirm_msg.delete()
        await ctx.send("❌ Edit timed out. No changes made.")
        return False

# Set Absolute Value Commands

@bot.command(name='setxp')
@is_authorized()
async def set_xp_cmd(ctx, member: discord.Member, amount: int):
    """Set a user's XP to an absolute value (Authorized users only)"""
    if amount < 0:
        await ctx.send("❌ XP cannot be negative!")
        return

    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(member.id, ctx.guild.id)

    current_xp = user_data['xp']
    if not await confirm_edit(ctx, member, "XP", current_xp, amount):
        return

    user_data['xp'] = amount
    update_user_data(user_data)

    embed = discord.Embed(
        title="✅ XP Updated",
        description=f"{member.mention}'s XP has been set to {amount:,}",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command(name='setvc')
@is_authorized()
async def set_vc_cmd(ctx, member: discord.Member, minutes: int):
    """Set a user's VC time to an absolute value in minutes (Authorized users only)"""
    if minutes < 0:
        await ctx.send("❌ VC time cannot be negative!")
        return

    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(member.id, ctx.guild.id)

    current_minutes = user_data['vc_seconds'] // 60
    if not await confirm_edit(ctx, member, "VC Minutes", current_minutes, minutes):
        return

    user_data['vc_seconds'] = minutes * 60
    update_user_data(user_data)

    embed = discord.Embed(
        title="✅ VC Time Updated",
        description=f"{member.mention}'s VC time has been set to {minutes:,} minutes",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command(name='setwords')
@is_authorized()
async def set_words_cmd(ctx, member: discord.Member, amount: int):
    """Set a user's unique word count to an absolute value (Authorized users only)"""
    if amount < 0:
        await ctx.send("❌ Word count cannot be negative!")
        return

    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(member.id, ctx.guild.id)

    current_words = user_data['unique_words']
    if not await confirm_edit(ctx, member, "Unique Words", current_words, amount):
        return

    user_data['unique_words'] = amount
    update_user_data(user_data)

    embed = discord.Embed(
        title="✅ Word Count Updated",
        description=f"{member.mention}'s unique word count has been set to {amount:,}",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command(name='setmessages')
@is_authorized()
async def set_messages_cmd(ctx, member: discord.Member, amount: int):
    """Set a user's message count to an absolute value (Authorized users only)"""
    if amount < 0:
        await ctx.send("❌ Message count cannot be negative!")
        return

    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(member.id, ctx.guild.id)

    current_messages = user_data['messages_sent']
    if not await confirm_edit(ctx, member, "Messages Sent", current_messages, amount):
        return

    user_data['messages_sent'] = amount
    update_user_data(user_data)

    embed = discord.Embed(
        title="✅ Message Count Updated",
        description=f"{member.mention}'s message count has been set to {amount:,}",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

# Add/Subtract Commands

@bot.command(name='addxp')
@is_authorized()
async def add_xp_cmd(ctx, member: discord.Member, amount: int):
    """Add or subtract XP from a user (Authorized users only)"""
    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(member.id, ctx.guild.id)

    current_xp = user_data['xp']
    new_xp = max(0, current_xp + amount)  # Prevent negative XP

    if not await confirm_edit(ctx, member, "XP", current_xp, new_xp):
        return

    user_data['xp'] = new_xp
    update_user_data(user_data)

    embed = discord.Embed(
        title="✅ XP Updated",
        description=f"{member.mention}'s XP has been {'increased' if amount > 0 else 'decreased'} by {abs(amount):,}",
        color=discord.Color.green()
    )
    embed.add_field(name="New Total", value=f"{new_xp:,}", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='addvc')
@is_authorized()
async def add_vc_cmd(ctx, member: discord.Member, minutes: int):
    """Add or subtract VC time from a user in minutes (Authorized users only)"""
    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(member.id, ctx.guild.id)

    current_minutes = user_data['vc_seconds'] // 60
    new_minutes = max(0, current_minutes + minutes)  # Prevent negative VC

    if not await confirm_edit(ctx, member, "VC Minutes", current_minutes, new_minutes):
        return

    user_data['vc_seconds'] = new_minutes * 60
    update_user_data(user_data)

    embed = discord.Embed(
        title="✅ VC Time Updated",
        description=f"{member.mention}'s VC time has been {'increased' if minutes > 0 else 'decreased'} by {abs(minutes):,} minutes",
        color=discord.Color.green()
    )
    embed.add_field(name="New Total", value=f"{new_minutes:,} minutes", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='addwords')
@is_authorized()
async def add_words_cmd(ctx, member: discord.Member, amount: int):
    """Add or subtract unique words from a user (Authorized users only)"""
    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(member.id, ctx.guild.id)

    current_words = user_data['unique_words']
    new_words = max(0, current_words + amount)  # Prevent negative words

    if not await confirm_edit(ctx, member, "Unique Words", current_words, new_words):
        return

    user_data['unique_words'] = new_words
    update_user_data(user_data)

    embed = discord.Embed(
        title="✅ Word Count Updated",
        description=f"{member.mention}'s unique word count has been {'increased' if amount > 0 else 'decreased'} by {abs(amount):,}",
        color=discord.Color.green()
    )
    embed.add_field(name="New Total", value=f"{new_words:,}", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='addmessages')
@is_authorized()
async def add_messages_cmd(ctx, member: discord.Member, amount: int):
    """Add or subtract messages from a user (Authorized users only)"""
    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(member.id, ctx.guild.id)

    current_messages = user_data['messages_sent']
    new_messages = max(0, current_messages + amount)  # Prevent negative messages

    if not await confirm_edit(ctx, member, "Messages Sent", current_messages, new_messages):
        return

    user_data['messages_sent'] = new_messages
    update_user_data(user_data)

    embed = discord.Embed(
        title="✅ Message Count Updated",
        description=f"{member.mention}'s message count has been {'increased' if amount > 0 else 'decreased'} by {abs(amount):,}",
        color=discord.Color.green()
    )
    embed.add_field(name="New Total", value=f"{new_messages:,}", inline=True)
    await ctx.send(embed=embed)


@bot.command(name='resetstats')
@commands.has_permissions(administrator=True)
async def reset_stats_cmd(ctx, member: discord.Member, stat_type: str = "all"):
    """Reset user stats (Admin only) - Usage: %resetstats @user [messages/vc/channels/images/all]"""
    if not member:
        await ctx.send("❌ Please specify a user to reset stats for!")
        return

    user_data = get_user_data(member.id, ctx.guild.id)
    if not user_data:
        await ctx.send(f"❌ No data found for {member.mention}")
        return

    conn = get_db_connection()
    c = conn.cursor()

    if stat_type.lower() == "messages":
        user_data['messages_sent'] = 0
        user_data['unique_words'] = 0
        user_data['lifetime_words'] = 0
        c.execute('''DELETE FROM daily_stats WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
        c.execute('''DELETE FROM weekly_stats WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
    elif stat_type.lower() == "vc":
        user_data['vc_seconds'] = 0
        c.execute('''DELETE FROM voice_sessions WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
    elif stat_type.lower() == "channels":
        user_data['channels_used'] = 0
        c.execute('''DELETE FROM user_channels WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
        c.execute('''DELETE FROM daily_channels WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
    elif stat_type.lower() == "images":
        user_data['images_sent'] = 0
    elif stat_type.lower() == "all":
        user_data = create_default_user(member.id, ctx.guild.id)
        # Clear all related tables
        c.execute('''DELETE FROM daily_stats WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
        c.execute('''DELETE FROM weekly_stats WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
        c.execute('''DELETE FROM user_channels WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
        c.execute('''DELETE FROM daily_channels WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
        c.execute('''DELETE FROM voice_sessions WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
        c.execute('''DELETE FROM quests_progress WHERE user_id = ? AND guild_id = ?''', (member.id, ctx.guild.id))
    else:
        conn.close()
        await ctx.send("❌ Invalid stat type! Use: messages/vc/channels/images/all")
        return

    update_user_data(user_data)
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="🔄 Stats Reset Complete",
        description=f"Reset {stat_type} stats for {member.mention}",
        color=discord.Color.red()
    )
    embed.set_footer(text="This action cannot be undone")
    await ctx.send(embed=embed)


# Fuzzy command matching helper
def get_similar_command(attempted_command: str) -> str:
    """Find similar commands using simple string matching"""
    all_commands = ['profile', 'quests', 'claim', 'claimall', 'autoclaim', 'questprogress', 
                    'vctest', 'debug', 'banner', 'color', 'leaderboard', 'lb', 'help', 'guide']
    
    attempted_lower = attempted_command.lower()
    
    # Check for exact matches with different case
    for cmd in all_commands:
        if attempted_lower == cmd.lower():
            return cmd
    
    # Check for partial matches
    for cmd in all_commands:
        if attempted_lower in cmd.lower() or cmd.lower() in attempted_lower:
            return cmd
    
    # Check for common typos (Levenshtein distance of 1-2)
    for cmd in all_commands:
        if len(attempted_lower) == len(cmd):
            differences = sum(1 for a, b in zip(attempted_lower, cmd.lower()) if a != b)
            if differences <= 2:
                return cmd
    
    return None


@bot.event
async def on_message(message):
    """Enhanced message handler with improved typo detection"""
    if message.author.bot:
        return await bot.process_commands(message)

    # Check for wrong prefix usage - only for commands that closely match bot commands
    content = message.content.strip()
    wrong_prefixes = ['$', '!', '/', '.', '>', '<', '?']

    # Only check for typos if the message looks like it could be a command
    if len(content) > 1 and len(content) < 50:  # Reasonable command length
        for prefix in wrong_prefixes:
            if content.startswith(prefix):
                # Extract the command part
                command_part = content[1:].split()[0] if len(content) > 1 else ""
                similar_cmd = get_similar_command(command_part)

                # Only suggest if it's a very close match (not just any random word)
                if similar_cmd and len(command_part) >= 3:  # Minimum 3 characters for suggestion
                    embed = discord.Embed(
                        title="🤔 Wrong Prefix Detected",
                        description=f"Hey there! It looks like you tried to use a command, but used the wrong prefix.",
                        color=discord.Color.orange()
                    )
                    embed.add_field(
                        name="You typed:",
                        value=f"`{content[:50]}`",
                        inline=False
                    )
                    embed.add_field(
                        name="Did you mean:",
                        value=f"`%{similar_cmd}`",
                        inline=False
                    )
                    embed.set_footer(text="💡 Tip: All Questuza commands start with %")
                    await message.channel.send(embed=embed)
                    return

    # Continue with normal message processing
    if content.startswith('%'):
        return await bot.process_commands(message)

    user_data = get_user_data(message.author.id, message.guild.id)
    if not user_data:
        user_data = create_default_user(message.author.id, message.guild.id)

    # Prepare cleaned words list (counts total words, not just unique)
    txt = re.sub(r'http\S+', '', message.content or '')
    txt = re.sub(r'<@!?\d+>', '', txt)
    txt = re.sub(r'[^\w\s]', ' ', txt)
    words_list = re.findall(r'\b[a-zA-Z]{2,}\b', txt.lower())
    total_words = len(words_list)

    # Only consider messages with at least 2 words
    if total_words >= 2:
        # XP counts use first 50 words only
        xp_word_count = min(50, total_words)
        unique_words = len(set(words_list))

        # Normalize content for duplicate detection
        normalized = ' '.join((message.content or '').split()).strip().lower()
        key = (message.guild.id if message.guild else None, message.channel.id)
        last = LAST_USER_MESSAGE.get(key)
        is_consecutive_duplicate = last and last.get('author_id') == message.author.id and last.get('content') == normalized

        # Update last message record for this channel
        LAST_USER_MESSAGE[key] = {'author_id': message.author.id, 'content': normalized}

        # If it's a consecutive duplicate outside spam channel => punish (deduct XP by removing equivalent lifetime words)
        if is_consecutive_duplicate and message.channel.id != SPAM_CHANNEL_ID:
            # Deduct the XP equivalent by subtracting lifetime words (10 XP per word -> 1 word = 10 XP)
            user_data['lifetime_words'] = user_data.get('lifetime_words', 0) - xp_word_count
            # Still count the message as a message for stats
            user_data['messages_sent'] += 1
        else:
            # Normal or spam-channel message: update stats
            user_data['messages_sent'] += 1
            # Keep unique words tracking (used by quests)
            user_data['unique_words'] += unique_words

            # If this is the spam channel, award heavily reduced XP: 1 XP per 100 words (so add to xp directly)
            if message.channel.id == SPAM_CHANNEL_ID:
                spam_xp = xp_word_count // 100  # integer division: 1 XP per 100 words
                if spam_xp:
                    user_data['xp'] = user_data.get('xp', 0) + spam_xp
            else:
                # For regular channels, add xp via lifetime_words (10 XP per word)
                user_data['lifetime_words'] = user_data.get('lifetime_words', 0) + xp_word_count

        # Track channel usage
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            '''SELECT 1 FROM user_channels 
                     WHERE user_id = ? AND guild_id = ? AND channel_id = ?''',
            (message.author.id, message.guild.id if message.guild else None, message.channel.id))
        if not c.fetchone():
            c.execute(
                '''INSERT INTO user_channels (user_id, guild_id, channel_id)
                         VALUES (?, ?, ?)''',
                (message.author.id, message.guild.id if message.guild else None, message.channel.id))
            user_data['channels_used'] += 1
        conn.commit()
        conn.close()

    if message.attachments:
        image_count = len([
            att for att in message.attachments
            if att.content_type and 'image' in att.content_type
        ])
        if image_count > 0:
            user_data['images_sent'] += image_count

    update_user_data(user_data)
    
    # Update daily and weekly quest stats
    is_reply = 1 if message.reference else 0
    # Use unique_words for quest progress reporting, but cap for XP was applied above
    update_daily_stats(message.author.id, message.guild.id, 
                      messages=1, words=(len(set(re.findall(r'\b[a-zA-Z]{2,}\b', re.sub(r'http\S+', '', message.content or '').lower()))) if message.content else 0), replies=is_reply)
    update_weekly_stats(message.author.id, message.guild.id,
                       messages=1, words=(len(set(re.findall(r'\b[a-zA-Z]{2,}\b', re.sub(r'http\S+', '', message.content or '').lower()))) if message.content else 0))
    
    # Check for expired unclaimed quests and auto-collect at 10% SILENTLY
    from quest_system import collect_expired_quests
    expired_quests = collect_expired_quests(message.author.id, message.guild.id)
    if expired_quests:
        total_expired_xp = sum(xp for _, xp in expired_quests)
        user_data['xp'] += total_expired_xp
        update_user_data(user_data)
        # NO MESSAGE SENT - Silent collection
    
    # Check for completed quests
    completed = check_and_complete_quests(message.author.id, message.guild.id, user_data)
    if completed:
        # Quest announcement channel ID
        QUEST_ANNOUNCEMENT_CHANNEL_ID = 1158615333289086997
        announcement_channel = bot.get_channel(QUEST_ANNOUNCEMENT_CHANNEL_ID)
        
        # Check if user has autoclaim enabled
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''SELECT autoclaim_enabled FROM users WHERE user_id = ? AND guild_id = ?''',
                  (message.author.id, message.guild.id))
        result = c.fetchone()
        autoclaim_enabled = result[0] if result and result[0] else 0
        conn.close()
        
        for quest in completed:
            # Handle auto-claim if enabled (30% fee)
            if autoclaim_enabled:
                reduced_xp = int(quest.xp_reward * 0.7)  # 30% fee = 70% received
                user_data['xp'] += reduced_xp
                user_data['quests_completed'] += 1
                
                # Track daily/weekly quest completion for multipliers
                from quest_system import QuestType
                if quest.quest_type == QuestType.DAILY:
                    user_data['daily_quests_completed'] = user_data.get('daily_quests_completed', 0) + 1
                elif quest.quest_type == QuestType.WEEKLY:
                    user_data['weekly_quests_completed'] = user_data.get('weekly_quests_completed', 0) + 1
                
                update_user_data(user_data)
                claim_quest_reward(message.author.id, message.guild.id, quest.quest_id)
                
                embed = discord.Embed(
                    title=f"{quest.emoji} Quest Auto-Claimed!",
                    description=f"{message.author.mention} completed **{quest.name}**!\n{quest.description}",
                    color=discord.Color.gold()
                )
                embed.add_field(name="XP Received (70%)", value=f"+{reduced_xp:,} XP", inline=True)
                embed.add_field(name="Fee (30%)", value=f"-{quest.xp_reward - reduced_xp:,} XP", inline=True)
                embed.set_footer(text=f"Auto-claimed • Use %autoclaim off to disable and claim full rewards manually")
            else:
                embed = discord.Embed(
                    title=f"{quest.emoji} Quest Completed!",
                    description=f"{message.author.mention} completed **{quest.name}**!\n{quest.description}",
                    color=discord.Color.gold()
                )
                embed.add_field(name="Reward", value=f"+{quest.xp_reward:,} XP", inline=True)
                embed.add_field(name="Quest Type", value=quest.quest_type.value.title(), inline=True)
                embed.set_footer(text=f"Use %claim {quest.quest_id} to claim your reward!")
            
            # Try to send to announcement channel, fallback to current channel
            try:
                if announcement_channel:
                    await announcement_channel.send(embed=embed)
                else:
                    await message.channel.send(embed=embed)
            except:
                try:
                    await message.channel.send(embed=embed)
                except:
                    pass
    
    await check_level_up(message.author, message.guild)
    await bot.process_commands(message)


# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Extract the attempted command
        attempted = ctx.message.content[1:].split()[0] if len(ctx.message.content) > 1 else ""
        similar_cmd = get_similar_command(attempted)
        
        if similar_cmd:
            embed = discord.Embed(
                title="🤔 Command Not Found",
                description=f"I couldn't find that command.",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="You typed:",
                value=f"`%{attempted}`",
                inline=False
            )
            embed.add_field(
                name="Did you mean:",
                value=f"`%{similar_cmd}`",
                inline=False
            )
            embed.set_footer(text="Use %help to see all available commands")
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Command not found. Use `%help` for available commands.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    else:
        print(f"Error: {error}")
        await ctx.send("❌ An error occurred while executing the command.")


# Run the bot
if __name__ == "__main__":
    # Try multiple token environment variable names for compatibility
    token = os.getenv('DISCORD_TOKEN') or os.getenv('BOT_TOKEN') or os.getenv('TOKEN')

    if not token:
        print("❌ DISCORD_TOKEN not found in environment variables!")
        print("💡 Please add your Discord bot token to Replit Secrets:")
        print("   1. Click the 'Secrets' tool in the left sidebar")
        print("   2. Add a new secret with key: DISCORD_TOKEN")
        print("   3. Paste your bot token as the value")
        exit(1)

    print("🚀 Starting Questuza bot...")
    print(f"✅ Token found: {token[:20]}...{token[-4:]}")
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("❌ Invalid Discord token! Please check your DISCORD_TOKEN in Secrets.")
        exit(1)
    except Exception as e:
        print(f"❌ Bot failed to start: {e}")
