# Calendar Reminder

A local Windows desktop app that watches shared Google Calendars and gives
a virtual assistant a 15-minute (configurable) heads-up before events on
calendars she's been given access to — without touching anyone else's
calendar settings.

See [SECURITY.md](SECURITY.md) for the security model — read that before
handing this app to anyone else. See [PRIVACY.md](PRIVACY.md) for what
Google Calendar data this app accesses and what it does with it — kept
in sync with the hosted copy linked as the app's privacy policy when
publishing the Google Cloud OAuth consent screen (README.md §1), since
that link needs to work independent of this repository's visibility.

## Architecture

```
Google Calendar API (read-only)
        |
        v
   this app, running on the user's own PC
        |
        v
   local SQLite database (%APPDATA%\CalendarReminder)
        |
        v
   Windows toast notifications
```

No custom server. No analytics. No data leaves the machine except the
read-only calls to Google's own API.

## Who does what, and how many times

* **§1 (Google Cloud setup)** — you, once, ever. Not per person you share
  this with.
* **§2–§6 (install, place the credentials file, package)** — you, once
  per new version you build.
* **Everyone you hand the built app to** — just install and click
  "Sign in with Google" with their own account. No Cloud Console, no
  files to place. (One caveat if you're on **External + Testing** — see
  the note at the end of §1 Step 5. **Internal** or a verified app has
  no such caveat.)

## 1. One-time Google Cloud setup (do this yourself — it needs your own
   Google login and Google won't let anyone, including an AI assistant,
   do this step on your behalf)

This is the only part of the whole project that has to be you, personally,
clicking through Google's own site. Everything else — the code, the
install, running it — I already built and tested. Full baby-step version
below; if a screen doesn't match exactly, Google reshuffles this UI
often, so just tell me what you're looking at and I'll adjust.

### Step 0 — decide External vs. Internal (read this before you start)

Partway through setup Google will ask whether your app's audience is
**External** or **Internal**. This choice matters a lot and can't be
changed later without starting over:

* **Internal** — only available if the Google account you're using is a
  **Google Workspace** account (a paid company account, e.g.
  `you@yourcompany.com` managed by an admin) — *not* a free `@gmail.com`
  account. Internal apps skip all of Google's review process and the
  token never expires. **Pick this if it's available to you.**
* **External** — the only option for a regular `@gmail.com` account.
  Because this app reads calendar data, Google classifies it as a
  "sensitive scope" app. Until you complete Google's verification
  process (optional, takes a few days, requires a public privacy policy
  page), the app stays in **Testing** mode, where Google logs the
  assistant out automatically **every 7 days** — she'd click
  "Reconnect Google" in Settings once a week. That's a real limitation,
  not a bug in this app. If that's not acceptable, verification is the
  fix; ask me and I'll walk you through what it requires.

### Step 1 — create a project

1. Go to https://console.cloud.google.com/projectcreate (sign in with
   the Google account the assistant will use).
2. Project name: something like `VA Calendar Reminder`. Leave the rest
   as default. Click **Create**. Wait for the notification bell to show
   it's done, then make sure that new project is selected in the
   project dropdown at the top of the page.

### Step 2 — turn on the Calendar API

1. Go to
   https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
   (with your new project still selected).
2. Click **Enable**.

### Step 3 — set up the consent screen ("Google Auth Platform")

1. Go to https://console.cloud.google.com/auth/overview
2. Click **Get Started**.
3. **App Information**: enter an app name (e.g. `Calendar Reminder`) and
   pick your email as the support email. Click **Next**.
4. **Audience**: choose **External** or **Internal** per Step 0 above.
   Click **Next**.
5. **Contact Information**: enter your email again. Click **Next**.
6. Agree to the terms yourself (this is Google's checkbox, not
   something I can tick for you) and click **Continue** / **Create**.

### Step 4 — add the calendar scope

1. Still in the Google Auth Platform pages, open the **Data Access** tab
   on the left.
2. Click **Add or Remove Scopes**.
3. In the filter box, search `calendar`, and check the box for:
   `.../auth/calendar.readonly` — "See and download any calendar you
   can access using your Google Calendar"
4. Click **Update**, then **Save**.

### Step 5 — add test users

Only needed if you chose **External** in Step 0.

1. Open the **Audience** tab.
2. Under **Test users**, click **Add users**, and add the Gmail
   address of *everyone* who will run this app — not just yourself.

**This is the one place the "install like normal software" story breaks
down for External + Testing apps**: until you complete Google's
verification, only the up-to-100 email addresses listed here are allowed
to sign in at all — anyone else gets an "access denied" screen the moment
they try. If you're going to hand this app to more people later, come
back to this Audience page and add their email first. This limitation
disappears entirely with **Internal** (any address in your Workspace
org can sign in, no list needed) or with a verified External app (any
Google account can sign in).

### Step 6 — create the Desktop OAuth client and download it

1. Open the **Clients** tab.
2. Click **Create Client**.
3. Application type: **Desktop app**. Name it anything, e.g.
   `Calendar Reminder Desktop`.
4. Click **Create**.
5. Click the download icon next to the new client to save the JSON
   file — this is your `client_secret.json`.

### If you see "Access blocked by your administrator"

That means your company's Workspace admin has restricted which
third-party apps can connect — that's their policy working as intended,
not an error to work around. Ask the admin to approve this app, or use
the **Internal** option from Step 0 if you're a Workspace admin
yourself.

**Each person/company that runs this app should go through the above
with their own Google account** rather than reusing someone else's
`client_secret.json`. See [SECURITY.md](SECURITY.md) for why.

## 2. Install (you, on your own dev machine)

Requires Python 3.11+ on Windows.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Place the credentials file

Put the `client_secret.json` you downloaded in §1 directly in the
project's root folder — next to `app.py`. This is the file that gets
bundled into the app in §6, so anyone you build a copy for never sees
this step. It's already excluded from git (see `.gitignore`) so it
won't end up committed if you ever push this project somewhere.

## 4. Run

```bash
python app.py
```

The first run walks through: sign in with Google → pick which calendars
to monitor → done. The app then runs in the system tray; closing the
window does not stop monitoring — use **Quit** from the tray menu (or
**Pause Monitoring** to temporarily stop reminders without exiting).

### Open in Google Calendar

Every alert window — meeting reminders (including second and snoozed
ones) and new / changed / canceled-meeting alerts — has an **Open in
Google Calendar** button. It opens that meeting in your browser; for a
canceled or moved meeting (whose own link would just say "event not
found") it opens that day instead. It doesn't close the window.

### Second (backup) reminder

Off by default. In **Settings > Reminder**, tick **"Also send a second
(backup) reminder"** to enable the **Second reminder** time picker
(grayed out until then) — same choices as the main reminder. You then
get a second meeting reminder at that time, identical to the first but
labeled **SECOND REMINDER**. It can come before or after the main one.
If both would come due at the same moment (e.g. the app was opened 3
minutes before the meeting) you get one reminder, not two; if both are
set to the same time, it's just one reminder. Meeting-change alerts
never get a second reminder.

### Snoozing a reminder

Meeting reminder windows have a **Snooze** button next to OK. It closes
the reminder (and stops the flashing), then brings the same reminder
back — window, flashing border, notification and sound — after the time
set in **Settings > Reminder > Snooze for**: 3, 5, 10, 15, 20 or 30
minutes, or 1 hour (default 5 minutes). You can snooze again as many
times as you like.

A snoozed reminder is dropped instead of coming back if the meeting was
canceled, moved (the new time gets its own reminder), or has already
ended. Pending snoozes are kept only while the app is running. Meeting-
change alerts don't have a Snooze button.

### Looking at other days

The main window opens on **today** — the live list of what's still
coming up, with countdowns. Use **◀ / ▶** to step a day at a time,
**Today** to jump back, or the date box's calendar popup to jump
straight to any day up to **24 months back or ahead**. Every meeting on
that day from every monitored calendar is listed, all-day items first,
tinted with each calendar's color.

Other days are fetched from Google only when you look at them — one
small request per monitored calendar, for just that day — and kept in
memory for 5 minutes (refreshed automatically if you stay on that day,
never saved to disk). The once-a-minute background check is unchanged.
If you leave the window on another day, it returns to today on its own
after 10 minutes.

### Meeting-change alerts

On every sync (once a minute) the app compares each monitored calendar
against what it saw on the previous sync and alerts when a meeting in the
next week — today plus the next six days, on a rolling basis — was:

| Change | Alert window icon |
| --- | --- |
| **Added** | big **+**, "NEW MEETING" |
| **Canceled / deleted / moved more than 7 days out** | big **✕**, "MEETING CANCELED / MOVED" |
| **Changed** (time or day, title, location, description) | big **pencil**, "MEETING CHANGED", old → new |

Every change alert has the same dark banner and a black-and-white
striped screen border that double-blinks — no color of its own, because
color in this app means "whose calendar" (shown as a small dot next to
the calendar name). They're deliberately unlike the "meeting starting"
reminder (solid border at the screen edge in the calendar's color, slow
breathing, no banner or icon).

Both kinds of window open in the **center of the main screen** (if
several are open, each is nudged a little down and right so none hides
another); the flashing border still shows on every monitor.
Like reminders, they stay up until you click OK. Turn them off in
**Settings > Notifications**.

Not reported as changes: a meeting that simply ended, a new day's
meetings coming into the 7-day window at midnight, RSVP-only updates, and losing access to a
calendar. The first sync after the app starts (or after a calendar is
newly ticked) only records a baseline, so changes made while the app was
closed don't produce alerts.

## 5. Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The test suite covers the logic that has to be exactly right with no
network access: duplicate-notification prevention, event-moved handling,
cancelled/all-day event filtering, timezone parsing, and the sleep/resume
catch-up check.

## 6. Package as a standalone .exe (to hand to someone else)

```bash
pip install -r requirements-dev.txt
pyinstaller --name CalendarReminder --windowed --onedir --icon=assets/icon.ico ^
    --add-data "client_secret.json;." --add-data "assets;assets" app.py
```

The `--add-data "client_secret.json;."` flag is what bundles your
credentials file into the built app, next to `CalendarReminder.exe`, so
the person you send it to never has to touch Google Cloud Console — they
install, run it, and click "Sign in with Google" with their own account.
(They still need to be on the Audience test-user list from §1 Step 5 if
you're on External + Testing.) `--icon` sets the .exe's own file icon;
`--add-data "assets;assets"` is separate and required too — it's what
lets the *running* app find `assets/icon.ico` for the window and system
tray icon, since `--icon` alone only affects how the file looks in
Explorer.

Prefer `--onedir` over `--onefile` — a onedir build is far easier for a
recipient (or an antivirus engine) to inspect, since the Python bytecode
and dependencies sit as visible files rather than being unpacked to a
temp directory at runtime. The whole `dist\CalendarReminder\` folder is
what you hand over (zip it up). See SECURITY.md before sending the
build to anyone else — in particular, everyone who runs it is now
relying on the one Google Cloud project you set up in §1, so treat that
project (and who has access to it) as something worth keeping secure on
your end.

## Where your data lives

Everything is under `%APPDATA%\CalendarReminder\`:

* `calendar_reminder.db` — cached event list, calendar selections, and
  which reminders have already fired.
* `app.log` — local log file. Token values are never written to it.

`client_secret.json` is **not** stored here by default — it ships bundled
inside the app itself (next to the `.exe`, or next to `app.py` when
running from source). If someone uses **Settings > Account > "Use my own
Google credentials"** to opt out of the shared one, *that* copy goes in
`%APPDATA%\CalendarReminder\client_secret.json` and takes priority.

The OAuth refresh token itself is **never** in either location — it's
stored in Windows Credential Manager via `keyring`.

## Project layout

```
calendar-reminder/
├── app.py                 # entry point, scheduler, AppController
├── config.py               # local file paths
├── auth/
│   ├── google_auth.py      # OAuth flow, read-only scope
│   └── token_store.py      # Credential Manager token storage
├── calendar_app/
│   ├── calendar_service.py # calendarList
│   ├── change_detector.py  # added / removed / changed between syncs
│   ├── day_view.py         # calendar view: day bounds, range, cache
│   ├── event_sync.py       # events.list + parsing
│   └── models.py
├── reminders/
│   ├── reminder_service.py # due-event logic, dedupe
│   └── notifications.py    # Windows toast
├── database/
│   └── db.py                # schema embedded as a string (see comment)
├── ui/
│   ├── main_window.py
│   ├── settings_window.py
│   ├── reminder_alert.py    # "meeting starting" window
│   ├── change_alert.py      # "meeting added/removed/changed" window
│   └── calendar_selector.py
├── system/
│   ├── tray.py
│   └── startup.py           # HKCU Run key, no admin required
└── tests/
```
