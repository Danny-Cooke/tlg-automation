# Fresha to Google Calendar sync

Fresha has a built-in calendar link. It is set per team member, lives entirely
inside Fresha, and has no API, so this is a checklist rather than code.
Source: Fresha help centre, "Link your calendar with Fresha" (read 2026-10-18).

## What it does

Three modes are offered when you link a Google calendar:

| Mode | Fresha wording | Effect |
|---|---|---|
| Export | "Export events to calendar" | Fresha appointments (and optionally blocked time) appear in the person's Google calendar. Fresha stays the source of truth. |
| Import | "Import events to calendar" | Events from a chosen Google calendar appear in Fresha as blocked time, so they cannot be booked over. |
| Two-way | "Two-way sync with your calendar (Google calendar only)" | Both of the above. |

Sync runs within about 15 minutes. Two-way is Google only. One Google calendar
can be linked to more than one Fresha workspace, which matters for team members
who also work elsewhere.

## Which mode to choose

- **Everyone: Export.** This is the mirror you asked for. Each person sees their
  Fresha diary on their phone, and nothing they do in Google can break the salon
  diary.
- **Two-way only for people who run their own diary** (the independents such as
  Bernadette, Carmen, Sophie, Lori-Dee) and who want personal Google events to
  block their Fresha availability. Warn them first: a private event in the
  linked Google calendar becomes blocked time in Fresha and removes those slots
  from online booking. If they pick two-way, set "What to import" to
  "Time and duration" so Fresha only shows a generic block, not the event title.

Export does not send client details into Google by any documented route, but
Fresha's article does not spell out exactly which fields appear in the Google
event. Check one real appointment after the first sync before rolling it out.

## Steps, done by the owner for a team member (recommended)

Needs a desktop browser signed in to Fresha as the account owner. The person
must be able to sign in to their own Google account when prompted, so do it
with them present or send them the self-service steps below.

1. Fresha web > **Team** > **Team members** > select the person.
2. **Actions** > **Edit** > **Settings** > **Linked calendars** > **Link a calendar**.
3. **Choose a calendar to link**: Google calendar > **Next step**. Sign in to the
   Google account to sync > **Continue**.
4. **How should this calendar sync**: pick Export (or Two-way, see above) >
   **Next step**.
5. **Export events to an external calendar**: tick appointments, decide on
   blocked time, pick **Locations to sync** (The Looking Glass Beauty) >
   **Complete**.
6. If Two-way was chosen, also complete **Import events from calendar**: pick
   the Google calendar to read, where imported blocks land, and **What to
   import** = "Time and duration".
7. Wait up to 15 minutes. Status shows **Synced**.

## Steps, done by the team member themselves

Fresha web > profile picture (top right) > **My profile** > **Workspaces** >
**Manage** next to The Looking Glass Beauty > **Linked calendars** > **Link a
calendar**, then steps 3 to 7 above. Fresha's article gives the linking steps
for desktop only; the mobile app can remove a link but the article does not
show it creating one.

## Removing a link

Web: profile picture > **My profile** > **Workspaces** > **Manage** > **Linked
calendars** > **Actions** (three dots) > **Remove**. If the link imported
events, "Delete blocked time imported from this calendar" is ticked by default.
Leave it ticked when someone leaves so their old personal blocks disappear from
the salon diary.

## Rollout order

1. Jess first, export only. Confirm an appointment appears in her Google
   calendar and check what the event shows.
2. The other nail staff (Sav, Carmen, Amber, Lissy), export only.
3. The independents (Lori-Dee, Sophie, Bernadette), export first, two-way if
   they ask for it after hearing the blocked-time caveat.

`terraform output staff_onboarding` prints this checklist per person with
their booking link filled in. Google account addresses are not stored in the
repo; the `calendar_email` field exists if you want them there, but the repo
is on GitHub so leave it empty unless the repo is private.
