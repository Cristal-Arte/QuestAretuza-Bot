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

# Questuza Bot 4.5.0 Updates TODO

## Project Overview
Implement study features alongside existing levelling system in Discord bot. Features should be minimalistic, user-friendly with soft colors and minimal emojis.

## Core Features

### 1. Study Session Management
- [ ] Command: %study start
- [ ] Bot initiates interactive setup
- [ ] Collects: study type, duration, subject, mood
- [ ] Starts session timer
- [ ] Creates session record in database
- [ ] Command: %study stop
- [ ] Ends current study session
- [ ] Saves final session data
- [ ] Displays session summary
- [ ] Session Tracking
- [ ] Real-time duration tracking
- [ ] Auto-save progress every 30 seconds
- [ ] Resume capability after bot restart

### 2. MCQ Practice System
- [ ] PDF Integration
  - [ ] Support Google Drive and direct PDF links
  - [ ] PDF accessibility validation with friendly error messages
  - [ ] Multi-page PDF rendering as embeds/images

  - [ ] Answer Recognition
  - [ ] Natural language parsing for answers ("Answer = B", "B", "Option B")
  - [ ] Database storage for user answers
  - [ ] Support for answer comments/explanations

  - [ ] Answer Checking
  - [ ] Answer key input (PDF link or manual entry)
  - [ ] Pattern recognition system for PDF answer keys
  - [ ] Configurable answer pattern detection
  - [ ] Score calculation and wrong answer reporting

### 3. MCQ Test Mode
  - [ ] Timed Tests
  - [ ] Custom timer setup (30min, 1hr, etc.)
  - [ ] Automatic test termination
  - [ ] Option to continue past timer for completion time tracking

  - [ ] Test Management
  - [ ] Start/stop test commands
  - [ ] Progress saving during test
  - [ ] Test summary and analytics

### 4. Bookmark System
  - [ ] Command: %study bookmarks
  - [ ] Save links, PDFs, images, text
  - [ ] Categorize/organize bookmarks
  - [ ] Quick access to saved resources

### 5. Analytics & History
  - [ ] Session History
  - [ ] View past study sessions
  - [ ] Filter by date, subject, type
  - [ ] Session duration statistics

  - [ ] Progress Tracking
  - [ ] Study time leaderboards
  - [ ] Frequency statistics
  - [ ] Performance trends and charts

  - [ ] Data Export
  - [ ] Session data backup
  - [ ] Progress reports

## Technical Requirements

### Database Schema
  - [ ] Sessions Table
  - session_id, user_id, start_time, end_time, duration
  - study_type, subject, mood, status

  - [ ] MCQ Answers Table
  - [ ] answer_id, session_id, question_number, user_answer
  - [ ] correct_answer, is_correct, user_comment, timestamp

  - [ ] Bookmarks Table
  - [ ] bookmark_id, user_id, title, url, content_type, tags, created_at

  - [ ] Progress Table
  - [ ] user_id, total_study_time, sessions_completed, subjects

### PDF Processing
- [ ] PDF text extraction library integration
- [ ] Pattern matching for answer keys
- [ ] Fallback pattern detection algorithms
- [ ] Error handling for inaccessible PDFs

### User Experience
- [ ] Minimalist design with soft colors
- [ ] Zero or minimal emojis
- [ ] Natural language interaction
- [ ] Clear error messages and guidance
- [ ] Progressive disclosure of complex features

### Phase 1: Core Session Management
- [ ] Study session start/stop commands
- [ ] Basic session tracking and database
- [ ] Simple timer functionality

### Phase 2: MCQ Practice
- [ ] PDF upload and display
- [ ] Basic answer recording
- [ ] Manual answer checking

### Phase 3: Advanced Features
- [ ] PDF answer key processing
- [ ] Pattern recognition system
- [ ] Test mode with timers

### Phase 4: Analytics & Bookmarks
- [ ] Session history and statistics
- [ ] Bookmark system
- [ ] Leaderboards and trends

### Phase 5: Polish & Reliability
- [ ] Comprehensive error handling
- [ ] Data backup and recovery
- [ ] Performance optimization

## Success Metrics
- [ ] Users can start/stop study sessions seamlessly
- [ ] MCQ practice works with various PDF formats
- [ ] Answer checking is accurate with different key formats
- [ ] Data persists through bot restarts
- [ ] Interface remains clean and unintrusive

## Notes
- [ ] Maintain separation from existing levelling system
- [ ] Focus on natural conversation flow after initial commands
- [ ] Ensure all user data is properly saved and recoverable
- [ ] Test with various PDF sources and formats