# Guide Command Update - v6.1.4

## Update Summary

The `%guide` command has been completely rebuilt into a comprehensive **5-page interactive guide** with pagination buttons, consolidating ALL bot information into a single, organized resource.

### Version Update
- **Previous Version:** 5.2.0
- **New Version:** 6.1.4
- **Updated Locations:** Both root and backup directories

---

## What's New in %guide

### 📄 Page Structure (5 Total Pages)

#### **PAGE 1: XP & Basics (1/5)** 🟢
- **XP System** - How to earn XP (1 XP per unique word, 10 XP per message, 60 XP per VC minute)
- **XP Multiplier System** - Base 1.0x, up to 1.35x with daily+weekly quests
- **How to Level Up** - Level progression and requirements

#### **PAGE 2: Daily & Weekly Quests (2/5)** 🔵
- **Daily Quests** - All 5 daily quests with requirements and rewards (300-500 XP each)
  - Daily Chatter, Word Wizard, Voice Active, Social Butterfly, Helpful Hand
  - Total: 2,000 XP/day potential + multipliers
- **Weekly Quests** - All 5 weekly quests with requirements and rewards (1,800-2,800 XP each)
  - Word Master, Voice Champion, Community Builder, Channel Explorer, Consistency King
  - Total: 11,300 XP/week potential + multipliers

#### **PAGE 3: Achievement & Special Quests (3/5)** 🟡
- **Achievement Quests** - Permanent one-time goals (3,000-10,000 XP)
  - Vocabulary Expert, Dictionary Master, Rising Star, Community Legend, Voice Veteran
- **Special Quests** - Complete breakdown of all 20 special quests across 4 tiers:
  - 🔴 **LEGENDARY TIER** (5 quests, 75,000-300,000 XP)
  - 🟠 **EPIC TIER** (5 quests, 37,500-75,000 XP)
  - 🟡 **RARE TIER** (5 quests, 18,000-37,500 XP)
  - 🟢 **ULTRA-TIER** (5 NEW quests, 80,000-125,000 XP)

#### **PAGE 4: Reward Systems (4/5)** 🟣
- **3 Claiming Methods:**
  - Manual Claim: 100% XP (BEST!)
  - Bulk Claim: 85% XP (15% fee)
  - Auto-Claim: 70% XP (30% fee)
  - Expired: 10% XP (if unclaimed after 24h/7d)
- **Unique Quests (Level 11+)** - Complete overview of unique quest system, submission, approval, and bypass mechanics

#### **PAGE 5: Mechanics & Tips (5/5)** 🟠
- **Word Counting Rules** - Detailed explanation with examples
- **Voice Chat Tracking** - How VC tracking works, max 5h/session, recovery
- **Profile Customization** - Banner, color, and cosmetics
- **10 Tips for Fast Leveling** - Optimization strategies
- **Useful Commands** - Quick reference for all major commands

---

## Interactive Features

### 🔘 Pagination Buttons
- **◀ Previous** - Navigate to previous page
- **Next ▶** - Navigate to next page
- Buttons auto-disable at start/end
- Maintains current page state

### 📊 Complete Coverage
The new guide now covers:
- ✅ All 4 quest types (Daily, Weekly, Achievement, Special)
- ✅ All 20 special quests with exact requirements and rewards
- ✅ Unique quest system mechanics
- ✅ Complete reward system breakdown
- ✅ XP earning mechanics with multipliers
- ✅ Voice chat tracking details
- ✅ Profile customization options
- ✅ 10 leveling tips
- ✅ Quick command reference

---

## Files Modified

### Root Directory
- `main.py`
  - Line 28: VERSION = "6.1.4"
  - Lines 5341-5637: Completely rebuilt guide_cmd with 5-page system

### Backup Directory
- `QuestAretuza-Bot/main.py`
  - Line 28: VERSION = "6.1.4"
  - Lines 4574-4870: Synchronized guide_cmd with root version

---

## Special Quest Details in Guide

### 🔴 LEGENDARY TIER (Hardest)
1. **Ultimate Level** (Lvl 100) → 300,000 XP
2. **Server Historian** (50k messages) → 150,000 XP
3. **Eternal Voice** (500 VC hours) → 112,500 XP
4. **Mythical Wordsmith** (25k words) → 75,000 XP
5. **Channel Master** (100 channels) → 90,000 XP

### 🟠 EPIC TIER
1. **Level Lord** (Lvl 50) → 75,000 XP
2. **Message Maestro** (10k messages) → 52,500 XP
3. **Voice Commander** (100 VC hours) → 45,000 XP
4. **Channel Conqueror** (50 channels) → 42,000 XP
5. **Word Collector** (10k words) → 37,500 XP

### 🟡 RARE TIER
1. **Level Legend** (Lvl 25) → 37,500 XP
2. **Chat Champion** (5k messages) → 30,000 XP
3. **Voice Virtuoso** (50 VC hours) → 27,000 XP
4. **Word Warrior** (5k words) → 22,500 XP
5. **Channel Explorer** (25 channels) → 18,000 XP

### 🟢 ULTRA-TIER (New)
1. **Ancient Dragon Slayer** (Lvl 75) → 125,000 XP
2. **Platinum Voice Master** (250 VC hrs) → 100,000 XP
3. **Message Millionaire** (25k messages) → 95,000 XP
4. **Ultra Wordsmith** (15k words) → 85,000 XP
5. **Channel Emperor** (75 channels) → 80,000 XP

---

## User Benefits

Users can now:
- ✅ View ALL quest details in one command
- ✅ Understand exact requirements for each quest
- ✅ See XP rewards for all quest types
- ✅ Learn optimal claiming strategies
- ✅ Understand multiplier system completely
- ✅ Navigate through 5 organized pages
- ✅ Reference all commands at once
- ✅ Get leveling tips all in one place

---

## Command Usage

```
%guide
```

This displays the first page. Use the **Next ▶** button to navigate through all 5 pages. The **◀ Previous** button allows backward navigation.

---

## Backward Compatibility

- ✅ All existing commands still work
- ✅ No breaking changes
- ✅ Same functionality with enhanced presentation
- ✅ Better organization for user education

---

## Next Steps

- Users can now run `%guide` to access comprehensive documentation
- All future guide references should point to this new interactive guide
- The guide consolidates all bot mechanics into a single, accessible resource

---

**Updated:** January 2025  
**Version:** 6.1.4  
**Status:** ✅ Complete
