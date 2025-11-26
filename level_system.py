"""
Level System for Questuza Discord Bot
Defines all levels, XP requirements, and unique quest requirements
"""

# Exponential level progression - every level gets progressively harder
# Formula basis: Base 1000 XP with 1.15x multiplier per level (roughly exponential)
LEVEL_REQUIREMENTS = {
    1: 0,           # Start at level 1
    2: 1000,        # 1.0k
    3: 2200,        # 2.2k cumulative
    4: 3600,        # 3.6k
    5: 5150,        # 5.1k
    6: 6950,        # 6.9k
    7: 9000,        # 9.0k
    8: 11350,       # 11.3k
    9: 13950,       # 13.9k
    10: 16850,      # 16.8k
    11: 20200,      # 20.2k - UNIQUE QUEST REQUIREMENT STARTS
    12: 24100,      # 24.1k
    13: 28600,      # 28.6k
    14: 33850,      # 33.8k
    15: 39950,      # 39.9k
    16: 47000,      # 47.0k
    17: 55150,      # 55.1k
    18: 64500,      # 64.5k
    19: 75300,      # 75.3k
    20: 87700,      # 87.7k
    21: 102000,     # 102.0k
    22: 118500,     # 118.5k
    23: 137500,     # 137.5k
    24: 159500,     # 159.5k
    25: 185000,     # 185.0k
    26: 215000,     # 215.0k
    27: 250000,     # 250.0k
    28: 290000,     # 290.0k
    29: 337000,     # 337.0k
    30: 390000,     # 390.0k
    31: 451000,     # 451.0k
    32: 522000,     # 522.0k
    33: 604000,     # 604.0k
    34: 700000,     # 700.0k
    35: 813000,     # 813.0k
    36: 945000,     # 945.0k
    37: 1100000,    # 1.1M
    38: 1280000,    # 1.28M
    39: 1490000,    # 1.49M
    40: 1730000,    # 1.73M
    41: 2010000,    # 2.01M
    42: 2330000,    # 2.33M
    43: 2700000,    # 2.7M
    44: 3130000,    # 3.13M
    45: 3630000,    # 3.63M
    50: 5500000,    # 5.5M
    60: 10000000,   # 10M
    70: 18000000,   # 18M
    80: 30000000,   # 30M
    90: 50000000,   # 50M
    100: 80000000,  # 80M
}

# Unique quests list - ordered for levels 11+
UNIQUE_QUESTS = [
    {
        "id": "sky_gazer",
        "name": "Sky Gazer",
        "description": "Take 10 pictures of the sky on 10 different days and post them",
        "requires_approval": True,
        "xp_reward": 5000,
        "lifely_points": 1
    },
    {
        "id": "cloud_hunter",
        "name": "Cloud Hunter",
        "description": "Take a picture of a cloud and post it",
        "requires_approval": True,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "local_landmark_hunter",
        "name": "Local Landmark Hunter",
        "description": "Take a selfie with a notable statue, fountain, or historical marker in your town",
        "requires_approval": True,
        "xp_reward": 3000,
        "lifely_points": 1
    },
    {
        "id": "locality",
        "name": "Locality",
        "description": "Find a random common object in your town and send a picture of it",
        "requires_approval": True,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "bridge_to_nowhere",
        "name": "Bridge to Nowhere",
        "description": "Find and photograph a bridge (any kind!)",
        "requires_approval": True,
        "xp_reward": 2500,
        "lifely_points": 1
    },
    {
        "id": "reflection_quest",
        "name": "Reflection Quest",
        "description": "Take a photo of a landscape reflected in a body of water or a window",
        "requires_approval": True,
        "xp_reward": 3000,
        "lifely_points": 1
    },
    {
        "id": "seasonal_snapper",
        "name": "Seasonal Snapper",
        "description": "Capture a sign of the current season where you live (e.g., cherry blossoms, falling leaves, snowman, first sprout of spring)",
        "requires_approval": True,
        "xp_reward": 2500,
        "lifely_points": 1
    },
    {
        "id": "urban_jungle",
        "name": "Urban Jungle",
        "description": "Find the coolest piece of graffiti or street art in your city",
        "requires_approval": True,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "doodle_master",
        "name": "Doodle Master",
        "description": "Draw your favorite food in MS Paint (or any simple drawing app) and post it",
        "requires_approval": True,
        "xp_reward": 2500,
        "lifely_points": 1
    },
    {
        "id": "meme_forge",
        "name": "Meme Forge",
        "description": "Create an original meme about this server or a current event and post it",
        "requires_approval": True,
        "xp_reward": 3000,
        "lifely_points": 1
    },
    {
        "id": "haiku_horizon",
        "name": "Haiku Horizon",
        "description": "Write a haiku about your day",
        "requires_approval": False,
        "xp_reward": 1500,
        "lifely_points": 1
    },
    {
        "id": "rebus_riddle",
        "name": "Rebus Riddle",
        "description": "Create a simple rebus puzzle for others to solve",
        "requires_approval": False,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "six_word_story",
        "name": "Six-Word Story",
        "description": "Tell a complete story about your week in exactly six words",
        "requires_approval": False,
        "xp_reward": 1500,
        "lifely_points": 1
    },
    {
        "id": "screenshot_scavenger_hunt",
        "name": "Screenshot Scavenger Hunt",
        "description": "Find a message from a random user that is at least 6 months old and screenshot it",
        "requires_approval": True,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "emoji_architect",
        "name": "Emoji Architect",
        "description": "Use 10 different server emojis in a single message",
        "requires_approval": False,
        "xp_reward": 1500,
        "lifely_points": 1
    },
    {
        "id": "compliment_chain",
        "name": "Compliment Chain",
        "description": "Give a genuine compliment to 3 different users in the general chat",
        "requires_approval": False,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "collaborative_canvas",
        "name": "Collaborative Canvas",
        "description": "Work with at least 2 other people to create a collaborative drawing or document and share the link",
        "requires_approval": True,
        "xp_reward": 3500,
        "lifely_points": 1
    },
    {
        "id": "word_of_the_day",
        "name": "Word of the Day",
        "description": "Use the word 'serendipity' correctly in a sentence in general chat",
        "requires_approval": False,
        "xp_reward": 1000,
        "lifely_points": 1
    },
    {
        "id": "tongue_twister",
        "name": "Tongue Twister",
        "description": "Post a voice message of you successfully saying a tricky tongue twister three times fast",
        "requires_approval": True,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "language_intro",
        "name": "Language Intro",
        "description": "Post a voice message greeting the server in a language you are learning or don't know",
        "requires_approval": False,
        "xp_reward": 1500,
        "lifely_points": 1
    },
    {
        "id": "walkable",
        "name": "Walkable",
        "description": "Post a picture of your step counter showing you walked at least 10k steps a week",
        "requires_approval": True,
        "xp_reward": 2500,
        "lifely_points": 1
    },
    {
        "id": "hydration_station",
        "name": "Hydration Station",
        "description": "Post a picture of a glass of water and commit to drinking it",
        "requires_approval": False,
        "xp_reward": 1000,
        "lifely_points": 1
    },
    {
        "id": "gratitude_attitude",
        "name": "Gratitude Attitude",
        "description": "List 3 things you're grateful for today in a dedicated channel",
        "requires_approval": False,
        "xp_reward": 1500,
        "lifely_points": 1
    },
    {
        "id": "tidy_space",
        "name": "Tidy Space",
        "description": "Spend 10 minutes tidying your desk/room and post a before-and-after picture",
        "requires_approval": True,
        "xp_reward": 2500,
        "lifely_points": 1
    },
    {
        "id": "unplugged",
        "name": "Unplugged",
        "description": "Spend a day away from all screens and post about what you did instead",
        "requires_approval": False,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "sock_puppet_theater",
        "name": "Sock Puppet Theater",
        "description": "Create a short video using a sock puppet",
        "requires_approval": True,
        "xp_reward": 3000,
        "lifely_points": 1
    },
    {
        "id": "impression_impression",
        "name": "Impression Impression",
        "description": "Post a voice message doing your best impression of a famous cartoon character",
        "requires_approval": True,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "food_face",
        "name": "Food Face",
        "description": "Create a face on a plate using your food and take a picture",
        "requires_approval": True,
        "xp_reward": 2000,
        "lifely_points": 1
    },
    {
        "id": "to_be_continued",
        "name": "To Be Continued...",
        "description": "Write at least 100 words in the stories channel (ID: 1433396448698826832)",
        "requires_approval": False,
        "xp_reward": 3000,
        "lifely_points": 1
    },
    {
        "id": "mystery_box",
        "name": "Mystery Box",
        "description": "Wrap something you own in aluminum foil or paper and take a picture of it - others have to guess what it is",
        "requires_approval": True,
        "xp_reward": 2500,
        "lifely_points": 1
    },
]

def get_xp_for_level(level: int) -> int:
    """Get total XP needed to reach a level"""
    return LEVEL_REQUIREMENTS.get(level, LEVEL_REQUIREMENTS.get(100, 80000000))

def get_xp_for_next_level(current_xp: int, current_level: int) -> int:
    """Get XP needed to reach next level"""
    next_level = current_level + 1
    if next_level not in LEVEL_REQUIREMENTS:
        return LEVEL_REQUIREMENTS.get(100, 80000000)
    return LEVEL_REQUIREMENTS[next_level] - current_xp

def get_level_from_xp(total_xp: int) -> int:
    """Get user's level from total XP"""
    for level in range(100, 0, -1):
        if total_xp >= LEVEL_REQUIREMENTS.get(level, 0):
            return level
    return 1

def get_unique_quest_for_level(level: int) -> dict or None:
    """Get the unique quest required for a given level"""
    if level < 11:
        return None
    quest_index = level - 11
    if quest_index < len(UNIQUE_QUESTS):
        return UNIQUE_QUESTS[quest_index]
    return None

def get_required_unique_quests_count(level: int) -> int:
    """Get number of unique quests required for a level"""
    if level < 11:
        return 0
    return level - 10
