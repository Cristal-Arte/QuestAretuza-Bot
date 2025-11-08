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
- [ ] Add trivia questions table to database schema
- [ ] Create trivia commands: `%trivia start`, `%trivia answer`, `%trivia stop`
- [ ] Implement random question scheduling background task
- [ ] Add XP multiplier system for correct answers
- [ ] Add XP penalty system (-10k XP for wrong answers)
- [ ] Add trivia channel settings per guild
- [ ] Test trivia system with sample questions

### 3. Add Custom Quest Creation Commands
- [ ] Create admin commands: `%createquest`, `%editquest`, `%deletequest`
- [ ] Add custom quests table to database
- [ ] Implement dynamic quest loading from database
- [ ] Allow quest type selection (daily/weekly/achievement/special)
- [ ] Test custom quest creation and completion

## Testing Tasks
- [ ] Test bot startup and version command
- [ ] Test typo detection improvements
- [ ] Test offline VC tracking functionality
- [ ] Test VC session capping
- [ ] Test advanced quests and pagination
- [ ] Test Social Butterfly quest fix
- [ ] Test disconnect/reconnect handling
- [ ] Test trivia system functionality
- [ ] Test custom quest creation
- [ ] Test all XP multipliers and penalties
- [ ] Test new tracker test commands and fail-safes
