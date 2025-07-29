# Shared Email Templates

Common templates used across different game types for system-level communications.

## Error Handling Templates

### Session Not Found Template
```
Subject: Session Not Found - Let's Get You Back on Track

Hello,

I couldn't find the session you're trying to access. This can happen for a few reasons:

**Possible Causes:**
- The session ID might be incorrect
- The session may have expired
- There might be a temporary system issue

**What You Can Do:**
1. Check that you're replying to the correct email
2. Look for your most recent session email with the correct session ID
3. If you can't find it, reply with "HELP" and I'll help you locate your session

**Starting Fresh:**
If you'd like to begin a new session, simply email:
- dungeon@aws.promptexecution.com for adventures
- intimacy@aws.promptexecution.com for couples therapy

I'm here to help get you back into your session!

Best regards,
GPT Therapy Support Team
```

### System Maintenance Template
```
Subject: Temporary Maintenance - Your Session Will Resume Shortly

Dear Participant,

We're performing brief system maintenance to improve your experience. Your session is safely stored and will resume once maintenance is complete.

**What This Means:**
- Your progress is preserved
- All session data is secure
- You'll receive a notification when we're back online

**Estimated Duration:** {maintenance_duration}

**What You Can Do:**
- No action needed from you
- Keep this email for your session ID reference
- We'll send an update when maintenance is complete

Thank you for your patience!

GPT Therapy System Team
Session: {session_id}
```

## Welcome Back Templates

### Returning Player Template
```
Subject: Welcome Back! Continuing Your Journey

Hello {player_name},

Welcome back to your {game_type} session! It's been {time_since_last_activity} since your last turn.

## Where We Left Off
{session_summary}

## Your Character/Progress
{player_state_summary}

## Ready to Continue?
Simply reply with your next action or decision, and we'll pick up right where you left off.

Looking forward to continuing your journey!

{agent_signature}
Session: {session_id}
```

## Session Invitation Templates

### Multiplayer Invitation Template
```
Subject: You're Invited to Join a {game_type} Session!

Hello,

{inviter_name} has invited you to join their {game_type} session. This is a collaborative experience where you'll work together via email.

## About This Session
{session_description}

## How to Join
To accept this invitation:
1. Reply to this email with "ACCEPT"
2. Complete the quick setup questions
3. Start participating immediately

## Session Details
- **Session ID**: {session_id}
- **Game Type**: {game_type}
- **Current Players**: {current_player_list}
- **Started**: {session_start_date}

Ready to join the adventure?

{agent_signature}
```

## Timeout and Reminder Templates

### Gentle Reminder Template
```
Subject: [Reminder] Your Turn in {game_type} Session

Hello {player_name},

Your {game_type} session is waiting for your response! It's been {days_since_last_turn} days since the last update.

## Current Status
{current_situation_brief}

## What's Needed
{action_needed_from_player}

## No Pressure
Take your time - there's no rush! Just wanted to make sure you didn't miss the continuation of your journey.

Reply whenever you're ready to continue.

{agent_signature}
Session: {session_id}
```

### Final Timeout Warning Template
```
Subject: [Final Notice] Session Will Pause Soon - {game_type}

Dear {player_name},

Your {game_type} session will be automatically paused in {warning_period} due to inactivity.

## What Happens Next
- **If you respond**: Session continues normally
- **If no response**: Session pauses but remains saved
- **To resume later**: Email with your session ID anytime

## Current Status
{situation_summary}

We'll keep your progress safe! Resume anytime by emailing with session {session_id}.

{agent_signature}
```

## Completion Templates

### Session Complete Template
```
Subject: [Complete] Your {game_type} Journey Ends - What's Next?

Dear {player_name},

Congratulations! You've completed your {game_type} session.

## Your Journey
{session_completion_summary}

## Final Stats
{completion_statistics}

## What's Next?
- **Start New Session**: Email {game_type}@aws.promptexecution.com
- **Different Experience**: Try our other game types
- **Share Your Story**: Tell friends about your experience

## Feedback Welcome
How was your experience? Reply with any thoughts or suggestions!

Thank you for playing!

{agent_signature}
Final Session: {session_id}
```

## Technical Support Templates

### Email Parsing Error Template
```
Subject: [Technical Issue] Having Trouble Reading Your Message

Hello,

I'm having difficulty processing your recent email. This is usually a temporary technical issue.

**What You Can Try:**
1. Reply again with a simpler message
2. Avoid special formatting or attachments
3. Make sure you're replying to the most recent session email

**If Problems Persist:**
Reply with "HELP" and include your session ID: {session_id}

I'm here to help get you back in the game!

Technical Support Team
```

### Account Recovery Template
```
Subject: [Recovery] Finding Your Session

Hello,

I'll help you recover access to your session.

**Information Needed:**
1. Approximate date you started
2. Game type (dungeon adventure or couples therapy)
3. Any details you remember about your character or progress

**Recovery Process:**
Reply with the above information, and I'll locate your session and get you back on track.

**Privacy Note:**
All session recovery is secure and confidential.

Support Team
```
