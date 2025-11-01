import discord
from discord.ext import commands, tasks
import sqlite3
import datetime
from typing import Dict
import re
import os
from flask import Flask
from threading import Thread
from quest_system import (
    init_quest_tables, get_all_quests, get_quests_by_type, get_quest_by_id,
    check_and_complete_quests, claim_quest_reward, update_daily_stats,
    update_weekly_stats, QuestType, get_user_quest_progress, reset_daily_quests,
    reset_weekly_quests
)

# Flask app for uptime monitoring
app = Flask('')


@app.route('/')
def home():
    return "Questuza is running!"


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

    # Insert/update version info
    c.execute(
        '''INSERT OR REPLACE INTO db_version (version, updated_at)
                 VALUES (?, ?)''', (5, datetime.datetime.now().isoformat()))

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


# Bot events
@bot.event
async def on_ready():
    print(f'🚀 Questuza is online! Logged in as {bot.user.name}')
    print(f'📊 Connected to {len(bot.guilds)} guilds')
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="your quests | %help"))
    # Start the background tasks
    if not check_voice_sessions.is_running():
        check_voice_sessions.start()
    if not send_keep_alive.is_running():
        send_keep_alive.start()
        print("💚 Keep-alive task started - sending messages every 2 minutes")


@bot.event
async def on_message(message):
    if message.author.bot:
        return await bot.process_commands(message)

    if message.content.startswith('%'):
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
    
    # Check for expired unclaimed quests and auto-collect at 10%
    from quest_system import collect_expired_quests
    expired_quests = collect_expired_quests(message.author.id, message.guild.id)
    if expired_quests:
        total_expired_xp = sum(xp for _, xp in expired_quests)
        user_data['xp'] += total_expired_xp
        update_user_data(user_data)
        
        # Send notification about expired quests
        try:
            embed = discord.Embed(
                title="⏰ Expired Quest Rewards Collected",
                description=f"{message.author.mention}, you had unclaimed quest rewards that expired!",
                color=discord.Color.orange()
            )
            
            expired_text = "\n".join([f"{q.emoji} **{q.name}** - {xp:,} XP (10% of {q.xp_reward:,})" 
                                     for q, xp in expired_quests])
            embed.add_field(name="Expired Quests", value=expired_text, inline=False)
            embed.add_field(name="Total XP Collected", value=f"+{total_expired_xp:,} XP", inline=True)
            embed.set_footer(text="💡 Claim quests within 24h (daily) or 7 days (weekly) for full rewards!")
            
            await message.channel.send(embed=embed)
        except:
            pass
    
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


# SIMPLIFIED VC TRACKING - FIXED VERSION
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

            # Update user VC time
            user_data = get_user_data(member.id, member.guild.id)
            if not user_data:
                user_data = create_default_user(member.id, member.guild.id)

            user_data['vc_seconds'] += int(session_duration)
            update_user_data(user_data)
            print(f"⏱️ Added {int(session_duration)}s VC time to {member}")
            
            # Update quest stats for VC time
            vc_minutes = int(session_duration) // 60
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

    user_data['xp'] = (user_data['lifetime_words'] * 10 +
                       (user_data['vc_seconds'] // 60) * 5 +
                       user_data['quests_completed'] * 100)

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


@bot.command(name='help')
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🪢 Questuza Help",
        description=
        "A leveling bot focused on meaningful engagement and creative quests!",
        color=discord.Color.blurple())

    commands_list = {
        "%profile [user]": "View your or someone else's profile",
        "%quests [type]": "View available quests (daily/weekly/achievement)",
        "%claim <quest_id>": "Manually claim quest reward (100% XP)",
        "%claimall": "Claim all completed quests at once (85% XP, 15% fee)",
        "%autoclaim [on/off/status]": "Toggle auto-claim (70% XP, 30% fee)",
        "%questprogress <quest_id>": "Check progress on a specific quest",
        "%vctest": "Test your VC time tracking",
        "%debug": "Check your current stats and progress",
        "%banner <url>": "Set profile banner (Level 1+)",
        "%color <hex>": "Change profile color",
        "%leaderboard [category] [page]":
        "View leaderboards (overall/words/vc/quests/xp)",
        "%guide": "Learn how the bot works"
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
    """

    embed.description = guide_text
    await ctx.send(embed=embed)


@bot.command(name='quests')
async def quests_cmd(ctx, quest_type: str = "all"):
    """View available quests - Usage: %quests [daily/weekly/achievement/all]"""
    
    user_data = get_user_data(ctx.author.id, ctx.guild.id)
    if not user_data:
        user_data = create_default_user(ctx.author.id, ctx.guild.id)
    
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
    else:
        quests = get_all_quests()
        title = "🎯 All Available Quests"
        color = discord.Color.green()
    
    embed = discord.Embed(
        title=title,
        description="Complete quests to earn bonus XP!",
        color=color
    )
    
    # Group by completion status
    completed_quests = []
    available_quests = []
    
    for quest in quests:
        progress = get_user_quest_progress(ctx.author.id, ctx.guild.id, quest.quest_id)
        if progress and progress['completed'] == 1:
            status = "✅ CLAIMED" if progress.get('claimed', 0) == 1 else "🎁 READY TO CLAIM"
            completed_quests.append((quest, status))
        else:
            available_quests.append(quest)
    
    # Show available quests
    if available_quests:
        for quest in available_quests[:10]:  # Limit to 10 to avoid embed limits
            type_icon = {"daily": "📅", "weekly": "📆", "achievement": "🏆"}.get(quest.quest_type.value, "🎯")
            embed.add_field(
                name=f"{quest.emoji} {quest.name} {type_icon}",
                value=f"{quest.description}\n**Reward:** {quest.xp_reward:,} XP\n**ID:** `{quest.quest_id}`",
                inline=False
            )
    
    # Show completed quests
    if completed_quests:
        completed_text = "\n".join([f"{q.emoji} {q.name} - {status}" for q, status in completed_quests[:5]])
        embed.add_field(
            name="Completed Quests",
            value=completed_text,
            inline=False
        )
    
    embed.set_footer(text="Use %quests [daily/weekly/achievement] to filter | Copy the quest ID and use %claim <quest_id> to claim rewards")
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
    """Enhanced message handler with helpful error detection"""
    if message.author.bot:
        return await bot.process_commands(message)

    # Check for wrong prefix usage
    content = message.content.strip()
    wrong_prefixes = ['$', '!', '/', '.', '>', '<', '?']
    
    for prefix in wrong_prefixes:
        if content.startswith(prefix):
            # Extract the command part
            command_part = content[1:].split()[0] if len(content) > 1 else ""
            similar_cmd = get_similar_command(command_part)
            
            if similar_cmd:
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
