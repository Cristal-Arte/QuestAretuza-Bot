# Questuza Bot Updates TODO

## Completed Tasks
- [x] Add version command (%version)
- [x] Fix typo detection to avoid interfering with other bots
- [x] Implement offline VC tracking (catch up missed time on startup)
- [x] Add 5-hour cap on individual VC sessions
- [x] Add advanced quests with pagination support
- [x] Fix Social Butterfly Quest Tracking
- [x] Add comprehensive test commands for all trackers
- [x] Add fail-safes and error handling for tracking systems

## In Progress: Major Feature Implementation

### 1. Implement 24/7 Uptime Self-Recovery
- [x] Add `on_disconnect` event handler with logging
- [x] Add `on_resumed` event handler with recovery notifications
- [x] Implement exponential backoff reconnection logic
- [x] Add status monitoring and recovery messages

### 2. Create Trivia System
- [x] Add trivia questions table to database schema
- [x] Create trivia commands: `%trivia start`, `%trivia answer`, `%trivia stop`
- [x] Implement random question scheduling background task
- [x] Add XP multiplier system for correct answers
- [x] Add XP penalty system (-10k XP for wrong answers)
- [x] Add trivia channel settings per guild
- [x] Test trivia system with sample questions

### 3. Add Custom Quest Creation Commands
- [x] Create admin commands: %createquest, %editquest, %deletequest
- [x] Add custom quests table to database
- [x] Implement dynamic quest loading from database
- [x] Allow quest type selection (daily/weekly/achievement/special)
- [x] Test custom quest creation and completion

## Testing Tasks
- [x] Test bot startup and version command
- [x] Test typo detection improvements
- [x] Test offline VC tracking functionality
- [x] Test VC session capping
- [x] Test advanced quests and pagination
- [x] Test Social Butterfly quest fix
- [x] Test disconnect/reconnect handling
- [x] Test trivia system functionality
- [x] Test custom quest creation
- [x] Test all XP multipliers and penalties
- [x] Test new tracker test commands and fail-safes
