# Security model

This app is designed to be handed to other people who will run it on
their own PCs and give it access to real, sometimes-shared calendars.
That makes "can this be backdoored after it's installed" the central
design question, not an afterthought. This document is the honest answer:
what's in place, what the residual risk is, and what you (the person
distributing it) still have to do.

## Things built into the code

**No update mechanism, no remote code execution, no plugins.**
The single biggest way a legitimate app turns into a backdoor later is an
auto-update feature: it gives whoever controls the update server (or
whoever compromises it) the ability to push arbitrary code to every
installed copy, silently. This app has none of that — no update checker,
no dynamic plugin loading, no `eval`/`exec` of anything, no downloading
and running of remote code, ever. If you want a newer version, you
rebuild and redistribute it yourself, the same way you got this one.

**Read-only, minimal OAuth scope.**
`auth/google_auth.py` requests exactly one scope:
`https://www.googleapis.com/auth/calendar.readonly`. The app cannot
create, modify, or delete events or calendars even if the code were
tampered with to try — Google's API rejects write calls made with a
read-only token. Don't widen this scope without updating this file.

**No phone-home, no third-party servers.**
The only network calls in the codebase go to `googleapis.com` endpoints
for OAuth and Calendar data. There is no analytics SDK, no crash
reporter, no "check for updates" ping, nothing that would give the app a
reason to talk to a server you don't control. Grep for
`requests.get`/`requests.post`/`urlopen`/`httpx` outside of the Google
client libraries if you ever want to re-verify this yourself.

**Tokens never touch disk in plaintext.**
`auth/token_store.py` stores the OAuth refresh token via `keyring`, which
on Windows uses Credential Manager (DPAPI-encrypted, tied to the Windows
user account). Compare that to a `token.json` file sitting in a folder —
a much easier target to exfiltrate. Nothing in the codebase logs token
contents (`app.py`'s logging setup only logs library names/levels, and
`google_auth.py` never prints/logs a `Credentials` object).

**One shared OAuth client across every copy of the app — a deliberate
trade-off, not an oversight.**
By default, `config.py` bundles one `client_secret.json` (from the
Google Cloud project you set up once, README.md §1) into every built
copy of the app, so a recipient never has to touch Google Cloud Console —
they just install and click "Sign in with Google." That's a real
usability win, and it's what you asked for. Be clear-eyed about what it
costs, though:

* **This identifies the *app*, not the person.** Each recipient still
  signs into *their own* Google account and gets *their own* token,
  stored locally on *their own* machine (see "tokens never touch disk in
  plaintext" above) — the shared client doesn't give anyone access to
  anyone else's calendar. What's shared is which Google Cloud project
  Google attributes all of that traffic to.
* **One project, one point of control and one point of failure.** If you
  ever need to revoke access (say, a build leaked somewhere you didn't
  intend), deleting or regenerating the OAuth client in that one project
  breaks every installed copy at once — which is the correct emergency
  response, but means you should know who has copies of the app so you
  can tell them to rebuild/reinstall afterward.
* **Google's per-project user cap applies across everyone you share this
  with, not per person.** If the project is External + Testing (the
  default for a personal `@gmail.com` account), only up to 100 email
  addresses you've explicitly listed as test users can sign in at all,
  and each of their sessions expires every 7 days. This stops mattering
  entirely with **Internal** (Google Workspace org) or a verified
  External app — see README.md §1 Step 0 and Step 5.
* **Treat the Google Cloud project itself as the thing to secure**, not
  just the code. Limit who has "Owner"/"Editor" access to it in Cloud
  Console (**IAM & Admin > IAM**), since anyone with that access could
  regenerate the client secret, add scopes, or see the list of who's
  authorized the app.

If you'd rather have full per-install isolation instead — no shared
project, no single point of failure, at the cost of every recipient
doing the ~15-minute Google Cloud setup themselves — that's still
supported: **Settings > Account > "Use my own Google credentials"** lets
any individual install opt out of the bundled client and bring its own,
which takes priority (`config.py`).

**Least-privilege startup registration.**
`system/startup.py` writes only to
`HKEY_CURRENT_USER\...\Run` — never `HKEY_LOCAL_MACHINE`, never a
scheduled task requiring elevation. It affects only the signed-in user's
own session, and it's a single, inspectable registry value pointing at
the app's own executable — not a generic "run this on every boot" hook
that malware would want to hide behind.

**Parameterized SQL everywhere.**
`database/db.py` never builds a query by string-formatting a value into
SQL — every value is passed as a bound parameter. Even though the current
threat model doesn't have adversarial user-controlled strings in this
data (event titles come from Google, not from a public form), this is
kept as a hard rule so it stays true if the app ever grows a feature that
accepts arbitrary text.

**Single-instance guard.**
Two copies of the app polling the same database at once could both read
"not yet notified" for an event before either writes the notified flag —
a real duplicate-reminder bug, not just a security nicety. `app.py` uses
a `QSharedMemory` lock so a second launch shows a message instead of
running side-by-side.

## Things that are on you when you distribute it

Code review can't secure a supply chain by itself — how the `.exe` (or
the source) actually reaches someone else's PC matters just as much.

1. **Hand it to people directly, or over a channel you trust.** Don't
   drop the built `.exe` in a shared folder other people can also write
   to. A backdoor doesn't need to touch your source code if someone can
   just swap the file after you built it.
2. **Publish a SHA-256 checksum alongside every build** you send out, over
   a different channel than the file itself (e.g. the checksum in a chat
   message, the file via email/drive). Ask recipients to verify it:
   ```powershell
   Get-FileHash CalendarReminder.exe -Algorithm SHA256
   ```
3. **Consider code-signing the executable** with a code-signing
   certificate if you'll be distributing this beyond a small trusted
   circle. An unsigned `.exe` will trigger SmartScreen warnings anyway;
   a signed one lets recipients verify it really came from you and
   wasn't modified since.
4. **Prefer `--onedir` over `--onefile`** when packaging with PyInstaller
   (see README.md) — a onedir build's contents are visible on disk for
   antivirus/inspection rather than unpacked to a temp folder at
   runtime, which makes tampering easier to spot and easier for AV
   engines to actually scan.
5. **Regenerate a hash-locked dependency file before you build**, so
   `pip install` can refuse to install a tampered/compromised package
   version from PyPI:
   ```bash
   pip install pip-tools
   pip-compile --generate-hashes --output-file=requirements.lock.txt requirements.txt
   pip install --require-hashes -r requirements.lock.txt
   ```
6. **If someone else will maintain or modify this code**, treat any pull
   request that touches `auth/`, `system/startup.py`, or adds a new
   outbound network call as security-sensitive and read it line by line
   — that's exactly the surface a backdoor would target.
7. **Recipients should keep Windows Defender (or their AV of choice) on.**
   Nothing here disables or excludes itself from AV scanning, and it
   shouldn't need to.

## What this app deliberately does NOT do

Straight from the spec, and worth restating here because every one of
these would be a plausible-sounding "feature" that quietly becomes a
backdoor:

* Never creates, modifies, or deletes calendar events or calendars.
* Never changes another person's reminder/notification settings.
* Never stores or asks for anyone's Google password.
* Never scrapes the Calendar web UI (API only).
* Never sends calendar data to an external server.
* Never requires a permanently-running cloud component.
* Never uses browser automation to interact with Google on your behalf.
