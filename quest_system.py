
"""
Quest System for Questuza Discord Bot
Handles daily quests, weekly quests, and achievement-based quests
"""

import sqlite3
import datetime
from typing import Dict, List, Optional
from enum import Enum


class QuestType(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    ACHIEVEMENT = "achievement"
    SPECIAL = "special"


class QuestStatus(Enum):
    NOT_STARTED = 0
    IN_PROGRESS = 1
    COMPLETED = 2
    CLAIMED = 3


class Quest:
    def __init__(self, quest_id: str, name: str, description: str, 
                 quest_type: QuestType, xp_reward: int, requirements: Dict,
                 emoji: str = "🎯"):
        self.quest_id = quest_id
        self.name = name
        self.description = description
        self.quest_type = quest_type
        self.xp_reward = xp_reward
        self.requirements = requirements
        self.emoji = emoji

    def check_completion(self, user_stats: Dict) -> bool:
        """Check if quest requirements are met"""
        for stat, required_value in self.requirements.items():
            if user_stats.get(stat, 0) < required_value:
                return False
        return True

    def get_progress(self, user_stats: Dict) -> Dict:
        """Get progress for each requirement"""
        progress = {}
        for stat, required_value in self.requirements.items():
            current = user_stats.get(stat, 0)
            progress[stat] = {
                'current': current,
                'required': required_value,
                'percentage': min(100, int((current / required_value) * 100))
            }
        return progress


# Quest Database
DAILY_QUESTS = [
    Quest(
        quest_id="daily_chatter",
        name="Daily Chatter",
        description="Send 20 messages today",
        quest_type=QuestType.DAILY,
        xp_reward=300,
        requirements={"daily_messages": 20},
        emoji="💬"
    ),
    Quest(
        quest_id="daily_wordsmith",
        name="Word Wizard",
        description="Use 50 unique words today",
        quest_type=QuestType.DAILY,
        xp_reward=400,
        requirements={"daily_words": 50},
        emoji="📝"
    ),
    Quest(
        quest_id="daily_voice",
        name="Voice Active",
        description="Spend 30 minutes in voice chat today",
        quest_type=QuestType.DAILY,
        xp_reward=500,
        requirements={"daily_vc_minutes": 30},
        emoji="🎤"
    ),
    Quest(
        quest_id="daily_social",
        name="Social Butterfly",
        description="Chat in 5 different channels today",
        quest_type=QuestType.DAILY,
        xp_reward=350,
        requirements={"daily_channels": 5},
        emoji="🦋"
    ),
    Quest(
        quest_id="daily_helper",
        name="Helpful Hand",
        description="Reply to 10 different users today",
        quest_type=QuestType.DAILY,
        xp_reward=450,
        requirements={"daily_replies": 10},
        emoji="🤝"
    ),
]

WEEKLY_QUESTS = [
    Quest(
        quest_id="weekly_wordmaster",
        name="Word Master",
        description="Use 500 unique words this week",
        quest_type=QuestType.WEEKLY,
        xp_reward=2000,
        requirements={"weekly_words": 500},
        emoji="📚"
    ),
    Quest(
        quest_id="weekly_voice_champion",
        name="Voice Champion",
        description="Spend 5 hours in voice chat this week",
        quest_type=QuestType.WEEKLY,
        xp_reward=2500,
        requirements={"weekly_vc_minutes": 300},
        emoji="🏆"
    ),
    Quest(
        quest_id="weekly_community",
        name="Community Builder",
        description="Send 100 messages this week",
        quest_type=QuestType.WEEKLY,
        xp_reward=1800,
        requirements={"weekly_messages": 100},
        emoji="🌟"
    ),
    Quest(
        quest_id="weekly_explorer",
        name="Channel Explorer",
        description="Be active in 15 different channels this week",
        quest_type=QuestType.WEEKLY,
        xp_reward=2200,
        requirements={"weekly_channels": 15},
        emoji="🗺️"
    ),
    Quest(
        quest_id="weekly_consistent",
        name="Consistency King",
        description="Be active for 5 different days this week",
        quest_type=QuestType.WEEKLY,
        xp_reward=2800,
        requirements={"weekly_active_days": 5},
        emoji="👑"
    ),
]

ACHIEVEMENT_QUESTS = [
    Quest(
        quest_id="achievement_level_10",
        name="Rising Star",
        description="Reach Level 10",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=5000,
        requirements={"level": 10},
        emoji="⭐"
    ),
    Quest(
        quest_id="achievement_level_25",
        name="Community Legend",
        description="Reach Level 25",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=10000,
        requirements={"level": 25},
        emoji="🌟"
    ),
    Quest(
        quest_id="achievement_words_1000",
        name="Vocabulary Expert",
        description="Use 1,000 lifetime unique words",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=3000,
        requirements={"lifetime_words": 1000},
        emoji="📖"
    ),
    Quest(
        quest_id="achievement_words_5000",
        name="Dictionary Master",
        description="Use 5,000 lifetime unique words",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=8000,
        requirements={"lifetime_words": 5000},
        emoji="📚"
    ),
    Quest(
        quest_id="achievement_vc_10h",
        name="Voice Veteran",
        description="Spend 10 hours total in voice chat",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=4000,
        requirements={"total_vc_hours": 10},
        emoji="🎧"
    ),
    Quest(
        quest_id="achievement_vc_50h",
        name="Voice Legend",
        description="Spend 50 hours total in voice chat",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=12000,
        requirements={"total_vc_hours": 50},
        emoji="🎵"
    ),
    Quest(
        quest_id="achievement_messages_500",
        name="Conversation Starter",
        description="Send 500 total messages",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=3500,
        requirements={"messages_sent": 500},
        emoji="💭"
    ),
    Quest(
        quest_id="achievement_messages_2000",
        name="Chat Champion",
        description="Send 2,000 total messages",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=9000,
        requirements={"messages_sent": 2000},
        emoji="💬"
    ),
    Quest(
        quest_id="achievement_channels_20",
        name="Omnipresent",
        description="Be active in 20 different channels",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=4500,
        requirements={"channels_used": 20},
        emoji="🌐"
    ),
    Quest(
        quest_id="achievement_images_100",
        name="Picture Perfect",
        description="Share 100 images",
        quest_type=QuestType.ACHIEVEMENT,
        xp_reward=3000,
        requirements={"images_sent": 100},
        emoji="📸"
    ),
]


def get_db_connection():
    """Get database connection with proper settings"""
    conn = sqlite3.connect('questuza.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_quest_tables():
    """Initialize quest tracking tables"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Quest progress table (already exists but let's ensure it has all fields)
    c.execute('''CREATE TABLE IF NOT EXISTS quests_progress
                 (user_id INTEGER, guild_id INTEGER, quest_id TEXT,
                  progress INTEGER DEFAULT 0, completed INTEGER DEFAULT 0,
                  started_at TEXT, completed_at TEXT, claimed INTEGER DEFAULT 0,
                  PRIMARY KEY (user_id, guild_id, quest_id))''')
    
    # Daily stats tracking
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats
                 (user_id INTEGER, guild_id INTEGER, date TEXT,
                  messages INTEGER DEFAULT 0, words INTEGER DEFAULT 0,
                  vc_minutes INTEGER DEFAULT 0, channels_used INTEGER DEFAULT 0,
                  replies INTEGER DEFAULT 0,
                  PRIMARY KEY (user_id, guild_id, date))''')
    
    # Weekly stats tracking
    c.execute('''CREATE TABLE IF NOT EXISTS weekly_stats
                 (user_id INTEGER, guild_id INTEGER, week_start TEXT,
                  messages INTEGER DEFAULT 0, words INTEGER DEFAULT 0,
                  vc_minutes INTEGER DEFAULT 0, channels_used INTEGER DEFAULT 0,
                  active_days INTEGER DEFAULT 0,
                  PRIMARY KEY (user_id, guild_id, week_start))''')
    
    # Indexes for performance
    c.execute('''CREATE INDEX IF NOT EXISTS idx_daily_stats_date 
                 ON daily_stats(user_id, guild_id, date)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_weekly_stats_week 
                 ON weekly_stats(user_id, guild_id, week_start)''')
    
    conn.commit()
    conn.close()


def get_all_quests() -> List[Quest]:
    """Get all available quests"""
    return DAILY_QUESTS + WEEKLY_QUESTS + ACHIEVEMENT_QUESTS


def get_quests_by_type(quest_type: QuestType) -> List[Quest]:
    """Get quests filtered by type"""
    if quest_type == QuestType.DAILY:
        return DAILY_QUESTS
    elif quest_type == QuestType.WEEKLY:
        return WEEKLY_QUESTS
    elif quest_type == QuestType.ACHIEVEMENT:
        return ACHIEVEMENT_QUESTS
    return []


def get_quest_by_id(quest_id: str) -> Optional[Quest]:
    """Get a specific quest by ID"""
    all_quests = get_all_quests()
    for quest in all_quests:
        if quest.quest_id == quest_id:
            return quest
    return None


def get_user_quest_progress(user_id: int, guild_id: int, quest_id: str) -> Dict:
    """Get user's progress for a specific quest"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''SELECT * FROM quests_progress 
                 WHERE user_id = ? AND guild_id = ? AND quest_id = ?''',
              (user_id, guild_id, quest_id))
    result = c.fetchone()
    conn.close()
    
    if result:
        return dict(result)
    return None


def update_daily_stats(user_id: int, guild_id: int, messages: int = 0, 
                       words: int = 0, vc_minutes: int = 0, 
                       channels: int = 0, replies: int = 0):
    """Update daily statistics for quest tracking"""
    conn = get_db_connection()
    c = conn.cursor()
    
    today = datetime.date.today().isoformat()
    
    c.execute('''INSERT INTO daily_stats 
                 (user_id, guild_id, date, messages, words, vc_minutes, channels_used, replies)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(user_id, guild_id, date) DO UPDATE SET
                 messages = messages + ?,
                 words = words + ?,
                 vc_minutes = vc_minutes + ?,
                 channels_used = channels_used + ?,
                 replies = replies + ?''',
              (user_id, guild_id, today, messages, words, vc_minutes, channels, replies,
               messages, words, vc_minutes, channels, replies))
    
    conn.commit()
    conn.close()


def update_weekly_stats(user_id: int, guild_id: int, messages: int = 0,
                        words: int = 0, vc_minutes: int = 0, channels: int = 0):
    """Update weekly statistics for quest tracking"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get start of current week (Monday)
    today = datetime.date.today()
    week_start = (today - datetime.timedelta(days=today.weekday())).isoformat()
    
    # Check if user was active today
    c.execute('''SELECT date FROM daily_stats 
                 WHERE user_id = ? AND guild_id = ? AND date >= ?''',
              (user_id, guild_id, week_start))
    active_days = len(set([row[0] for row in c.fetchall()]))
    
    c.execute('''INSERT INTO weekly_stats 
                 (user_id, guild_id, week_start, messages, words, vc_minutes, channels_used, active_days)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(user_id, guild_id, week_start) DO UPDATE SET
                 messages = messages + ?,
                 words = words + ?,
                 vc_minutes = vc_minutes + ?,
                 channels_used = channels_used + ?,
                 active_days = ?''',
              (user_id, guild_id, week_start, messages, words, vc_minutes, channels, active_days,
               messages, words, vc_minutes, channels, active_days))
    
    conn.commit()
    conn.close()


def check_and_complete_quests(user_id: int, guild_id: int, user_data: Dict) -> List[Quest]:
    """Check all quests and return newly completed ones"""
    completed_quests = []
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get daily stats
    today = datetime.date.today().isoformat()
    c.execute('''SELECT * FROM daily_stats WHERE user_id = ? AND guild_id = ? AND date = ?''',
              (user_id, guild_id, today))
    daily_stats = c.fetchone()
    daily_data = dict(daily_stats) if daily_stats else {}
    
    # Get weekly stats
    week_start = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
    c.execute('''SELECT * FROM weekly_stats WHERE user_id = ? AND guild_id = ? AND week_start = ?''',
              (user_id, guild_id, week_start))
    weekly_stats = c.fetchone()
    weekly_data = dict(weekly_stats) if weekly_stats else {}
    
    # Prepare stats for checking
    check_stats = {
        # Daily stats
        'daily_messages': daily_data.get('messages', 0),
        'daily_words': daily_data.get('words', 0),
        'daily_vc_minutes': daily_data.get('vc_minutes', 0),
        'daily_channels': daily_data.get('channels_used', 0),
        'daily_replies': daily_data.get('replies', 0),
        # Weekly stats
        'weekly_messages': weekly_data.get('messages', 0),
        'weekly_words': weekly_data.get('words', 0),
        'weekly_vc_minutes': weekly_data.get('vc_minutes', 0),
        'weekly_channels': weekly_data.get('channels_used', 0),
        'weekly_active_days': weekly_data.get('active_days', 0),
        # Achievement stats
        'level': user_data.get('level', 0),
        'lifetime_words': user_data.get('lifetime_words', 0),
        'total_vc_hours': user_data.get('vc_seconds', 0) // 3600,
        'messages_sent': user_data.get('messages_sent', 0),
        'channels_used': user_data.get('channels_used', 0),
        'images_sent': user_data.get('images_sent', 0),
    }
    
    # Check all quests
    for quest in get_all_quests():
        # Check if quest already completed
        c.execute('''SELECT completed FROM quests_progress 
                     WHERE user_id = ? AND guild_id = ? AND quest_id = ?''',
                  (user_id, guild_id, quest.quest_id))
        result = c.fetchone()
        
        if result and result[0] == 1:
            continue  # Already completed
        
        # Check if quest can be completed
        if quest.check_completion(check_stats):
            # Mark as completed
            c.execute('''INSERT OR REPLACE INTO quests_progress 
                         (user_id, guild_id, quest_id, completed, completed_at, claimed)
                         VALUES (?, ?, ?, 1, ?, 0)''',
                      (user_id, guild_id, quest.quest_id, datetime.datetime.now().isoformat()))
            completed_quests.append(quest)
    
    conn.commit()
    conn.close()
    
    return completed_quests


def claim_quest_reward(user_id: int, guild_id: int, quest_id: str) -> Optional[int]:
    """Claim reward for a completed quest, returns XP reward"""
    quest = get_quest_by_id(quest_id)
    if not quest:
        return None
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if quest is completed but not claimed
    c.execute('''SELECT completed, claimed FROM quests_progress 
                 WHERE user_id = ? AND guild_id = ? AND quest_id = ?''',
              (user_id, guild_id, quest_id))
    result = c.fetchone()
    
    if not result or result[0] != 1 or result[1] == 1:
        conn.close()
        return None  # Not completed or already claimed
    
    # Mark as claimed
    c.execute('''UPDATE quests_progress SET claimed = 1 
                 WHERE user_id = ? AND guild_id = ? AND quest_id = ?''',
              (user_id, guild_id, quest_id))
    
    conn.commit()
    conn.close()
    
    return quest.xp_reward


def collect_expired_quests(user_id: int, guild_id: int) -> List[tuple]:
    """
    Auto-collect unclaimed quest rewards that have expired.
    Daily quests expire after 24 hours, weekly after 7 days.
    Returns list of (quest, xp_awarded) tuples.
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    now = datetime.datetime.now()
    collected = []
    
    # Find completed but unclaimed quests
    c.execute('''SELECT quest_id, completed_at FROM quests_progress 
                 WHERE user_id = ? AND guild_id = ? AND completed = 1 AND claimed = 0''',
              (user_id, guild_id))
    unclaimed = c.fetchall()
    
    for quest_id, completed_at in unclaimed:
        quest = get_quest_by_id(quest_id)
        if not quest or not completed_at:
            continue
        
        completed_time = datetime.datetime.fromisoformat(completed_at)
        time_elapsed = (now - completed_time).total_seconds()
        
        # Check if quest has expired based on type
        is_expired = False
        if quest.quest_type == QuestType.DAILY:
            # Daily quests expire after 24 hours
            is_expired = time_elapsed > 86400  # 24 hours in seconds
        elif quest.quest_type == QuestType.WEEKLY:
            # Weekly quests expire after 7 days
            is_expired = time_elapsed > 604800  # 7 days in seconds
        
        if is_expired:
            # Award 10% of the quest XP
            xp_awarded = int(quest.xp_reward * 0.1)
            
            # Mark as claimed (expired)
            c.execute('''UPDATE quests_progress SET claimed = 1 
                         WHERE user_id = ? AND guild_id = ? AND quest_id = ?''',
                      (user_id, guild_id, quest_id))
            
            collected.append((quest, xp_awarded))
    
    conn.commit()
    conn.close()
    
    return collected


def reset_daily_quests(user_id: int, guild_id: int):
    """Reset daily quests for a new day"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Remove completed daily quests
    daily_quest_ids = [q.quest_id for q in DAILY_QUESTS]
    placeholders = ','.join('?' * len(daily_quest_ids))
    c.execute(f'''DELETE FROM quests_progress 
                  WHERE user_id = ? AND guild_id = ? AND quest_id IN ({placeholders})''',
              (user_id, guild_id, *daily_quest_ids))
    
    conn.commit()
    conn.close()


def reset_weekly_quests(user_id: int, guild_id: int):
    """Reset weekly quests for a new week"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Remove completed weekly quests
    weekly_quest_ids = [q.quest_id for q in WEEKLY_QUESTS]
    placeholders = ','.join('?' * len(weekly_quest_ids))
    c.execute(f'''DELETE FROM quests_progress 
                  WHERE user_id = ? AND guild_id = ? AND quest_id IN ({placeholders})''',
              (user_id, guild_id, *weekly_quest_ids))
    
    conn.commit()
    conn.close()
