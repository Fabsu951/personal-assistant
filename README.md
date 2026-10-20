# Personal Assistant (Telegram + Claude)

Your own AI personal assistant that you chat with on Telegram. It can:

- **Email & calendar**: read and search Gmail, draft and send replies, check and book Google Calendar events, search Google Drive
- **Tasks & reminders**: keep a to-do list and send you reminders on Telegram at the right time
- **Research & notes**: search the web and remember things for you
- **Life admin**: log expenses, give monthly spending summaries, and track recurring bills
- **Training coach**: keeps your training program, logs workouts and how your body feels (sleep, energy, injuries), adapts sessions to that, and sends a weekly review every Sunday
- **Strava**: workouts from Garmin, Apple Watch, Polar etc. come in automatically (optional)
- **Voice messages**: talk instead of typing (needs an OpenAI key, see below)
- **Daily briefing**: every morning (default 07:30), a summary of your day

**Safety:** it never sends an email or changes your calendar without asking. You get **✅ Approve / ❌ Reject** buttons first. Only *you* can talk to it.

---

## Setup (about 30–45 minutes, no coding)

You'll collect 4 keys, then paste them into the hosting site. Keep them private, like passwords.

### Step 1: Create the Telegram bot (2 min)
1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot`, then pick a name (e.g. *Jarvis*) and a username ending in `bot`.
3. BotFather replies with a **token** like `123456:ABC-xyz…`. Save it as `TELEGRAM_BOT_TOKEN`.

### Step 2: Get a Claude API key (5 min)
1. Go to **platform.claude.com** and sign in. This is separate from your Claude app subscription.
2. Go to **Billing** and add some credit (start with $5–10). Setting a monthly spend limit is a good idea.
3. Go to **API Keys → Create Key**. Save it as `ANTHROPIC_API_KEY`.

### Step 3: Let it access Google (15 min)
1. Go to **console.cloud.google.com** and create a new project (top bar → *New project* → name it "Assistant").
2. Go to **APIs & Services → Library** and enable these three: **Gmail API**, **Google Calendar API**, **Google Drive API**.
3. Go to **APIs & Services → OAuth consent screen** (may be called *Google Auth Platform*):
   - User type: **External**. App name: "Assistant". Use your email for the support and contact fields.
   - Under **Audience / Test users**, add your own Gmail address.
   - Then click **Publish app** (set the status to *In production*). ⚠️ If you skip this, Google logs the assistant out every 7 days. You don't need verification for personal use.
4. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Desktop app**. Click Create.
   - Save the **Client ID** as `GOOGLE_CLIENT_ID` and the **Client secret** as `GOOGLE_CLIENT_SECRET`.

### Step 4: Put it online with Railway (10 min, about $5/month)
1. Go to **railway.com** and log in **with GitHub**.
2. Click **New Project → Deploy from GitHub repo** and pick this repository.
3. Open the service, go to the **Variables** tab, then **Raw Editor**, and paste:
   ```
   ANTHROPIC_API_KEY=your-key
   TELEGRAM_BOT_TOKEN=your-token
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-secret
   TIMEZONE=Asia/Taipei
   OWNER_NAME=Fabian
   ASSISTANT_NAME=Jarvis
   BRIEFING_TIME=07:30
   DATA_DIR=/data
   ```
4. Add a disk so it remembers things across restarts: right-click the service → **Attach Volume** → mount path `/data`.
5. Wait for the deploy to turn green.

### Step 5: Lock it to you and connect Google (3 min)
1. In Telegram, send your bot any message. It replies with **your Telegram ID**.
2. In Railway → Variables, add `OWNER_TELEGRAM_ID=<that number>`. Railway redeploys automatically.
3. Send `/connect_google` to the bot and follow its three instructions.
4. Try it: *"What's on my calendar this week?"* or `/briefing`.

### Optional: voice messages (5 min, about $0.003 per minute of audio)
Claude can't listen to audio, so voice messages are turned into text by OpenAI's speech-to-text first.
1. Go to **platform.openai.com**, add a little credit under **Billing**, then **API keys → Create new secret key**.
2. In Railway → Variables, add `OPENAI_API_KEY=<that key>`.

The bot shows what it heard (🎤 "...") and then answers as if you had typed it.

### Optional: Strava (10 min, free)
Lets the training coach see runs, rides and other workouts from your watch. Garmin, Apple Watch (via an app like HealthFit), Polar, Coros and others can sync to Strava automatically.
1. Log in at **strava.com**, then open **strava.com/settings/api**.
2. Create an app: name "Ragnar", category "Training", website `http://localhost`, **Authorization Callback Domain** `localhost`. Upload any icon if it asks for one.
3. Copy the **Client ID** and **Client Secret** into Railway → Variables as `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET`.
4. Send `/connect_strava` to the bot and follow its instructions (same copy-the-address trick as Google).

---

## Using it
Just chat normally. Useful commands:

| Command | What it does |
|---|---|
| `/briefing` | Daily summary right now |
| `/tasks` | Open to-dos |
| `/connect_google` | (Re)connect Gmail/Calendar/Drive |
| `/connect_strava` | Connect Strava |
| `/review` | Weekly training review right now (it also comes automatically on Sundays, 19:00) |
| `/skills` | What it can do |
| `/reset` | Clear chat memory (tasks, notes and expenses are kept) |

**Make it yours:** set `EXTRA_INSTRUCTIONS` in Railway, e.g.
`I work at X. Reply to emails in English unless they wrote in Chinese. Keep my mornings before 10:00 free.`

**Costs:** Railway is about $5/month. Claude API use is pay-per-use; light daily use is usually a few dollars a month. To make it cheaper, set `MODEL=claude-haiku-5-5`. For a smarter assistant, set `MODEL=claude-opus-5-5`.

---

## Adding more agents later
The assistant is built from **skills** (specialists) in `assistant/skills/`. Each one is a single file. To add a new one, e.g. a fitness coach, a travel planner or a job-application tracker:

1. Open this repo in **Claude → Code** and say: *"Add a new skill that …"*.
2. Claude creates `assistant/skills/<name>.py` (based on `_template.py`) and registers it in `skills/__init__.py`.
3. Add its key to `ENABLED_SKILLS` in Railway, e.g. `google,tasks,research,admin,fitness`
   (if you never set `ENABLED_SKILLS`, the defaults in `config.py` are used).

Railway redeploys automatically whenever the GitHub repo changes.

## How it works (for the curious)
```
Telegram ──► assistant/main.py (bot, reminders, daily briefing)
                 │
                 ▼
             assistant/agent.py  ── Claude decides which tools to use
                 │                   (risky tools wait for your approval)
                 ▼
             assistant/skills/   google_workspace · tasks · research · admin · …
                 │
                 ▼
             SQLite database in /data (memory, tasks, notes, expenses, Google login)
```

## Troubleshooting
- **Bot doesn't answer:** check Railway → Deployments → Logs. "Missing settings" means a variable is missing.
- **"Google is not connected":** send `/connect_google`. If it keeps happening weekly, publish the Google app (Step 3.3).
- **It forgot everything after a redeploy:** the volume at `/data` is missing (Step 4.4).
- **Run the tests:** `pip install -r requirements.txt pytest && pytest`
