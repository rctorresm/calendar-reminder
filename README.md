# Calendar Reminder

A local Windows desktop app that watches shared Google Calendars and gives
a virtual assistant a 15-minute (configurable) heads-up before events on
calendars she's been given access to — without touching anyone else's
calendar settings.

See [SECURITY.md](SECURITY.md) for the security model — read that before
handing this app to anyone else.

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
│   └── calendar_selector.py
├── system/
│   ├── tray.py
│   └── startup.py           # HKCU Run key, no admin required
└── tests/
```
