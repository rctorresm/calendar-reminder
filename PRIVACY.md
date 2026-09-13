# Privacy Policy — Calendar Reminder

_Last updated: 2026-09-13_

Calendar Reminder is a Windows desktop application that watches Google
Calendars you've been given access to and reminds you before events on
them start. This page explains what data it accesses, what it does with
it, and what it never does — matching exactly what the code in this
repository does (see [README.md](README.md) and
[SECURITY.md](SECURITY.md) for the technical detail behind every claim
here).

## What Google data this app accesses

When you sign in with Google, Calendar Reminder requests exactly one
permission:

- **`https://www.googleapis.com/auth/calendar.readonly`** — read-only
  access to the calendars your Google account can see (your own, and any
  shared with you).

It never requests, and cannot obtain, permission to create, edit, or
delete your calendars or events, or access anything else in your Google
account (Gmail, Drive, contacts, etc.).

## What this app does with that data

- Displays your calendars so you can choose which ones to monitor.
- Reads upcoming event details (title, start/end time, location, which
  calendar it belongs to) for the calendars you selected.
- Uses that information locally to show an "Upcoming Events" list and to
  trigger a reminder (a Windows notification and/or an on-screen alert)
  before or at the start of an event, based on your own settings.

That's the entire purpose of the data access — nothing else.

## Where your data is stored

Everything lives only on your own computer, under
`%APPDATA%\CalendarReminder\`:

- **Event details and your settings** (which calendars you selected,
  reminder timing, colors, etc.) are cached in a local database file
  (`calendar_reminder.db`) so the app can work without calling Google's
  servers every second.
- **Your Google sign-in token** is stored using Windows' own Credential
  Manager (via the `keyring` library) — never written to a plain file
  anywhere.
- **A local log file** (`app.log`) records basic operational messages
  (e.g. "synced 3 events") for troubleshooting. It never contains your
  calendar content or sign-in token.

## What this app never does

- **Never sends your calendar data anywhere except Google's own API.**
  There is no other server involved — no analytics, no telemetry, no
  crash reporting, no third-party service of any kind.
- **Never shares, sells, or otherwise discloses your data** to any
  person or company.
- **Never creates, modifies, or deletes** your calendars, events, or any
  other Google account setting.
- **Never uses your data for advertising** or any purpose other than
  showing you the reminder you asked for.

## Your control over this data

- **Sign out** anytime from the app's Settings screen to remove your
  stored sign-in token from this computer.
- **Revoke access entirely** at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
  — this immediately cuts the app off from your Google account, from
  Google's side, regardless of anything happening on this computer.
- **Delete all locally stored data** by deleting the
  `%APPDATA%\CalendarReminder\` folder, or by uninstalling the app.

## Changes to this policy

If what this app accesses or does with your data ever changes, this page
will be updated to reflect it before that change ships.

## Contact

Questions about this policy or how the app handles your data:
**rctorres17@gmail.com**
