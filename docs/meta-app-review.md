# Meta App Review for Instagram messaging (Tlg-app2)

**Superseded 2026-10-27 (plan job 18):** the Instagram bot moved to the
Instagram Login route, which needs no App Review for an app serving the
business's own account. The operator steps are in `docs/setup.md` section
1 step 6. What follows is kept in case the Facebook Login route is ever
needed again.

Why: Standard Access on `instagram_manage_messages` only delivers DMs from
people with a role on the app, so client Instagram DMs never reach the bot
(found 2026-10-26, see `docs/decisions.md`). Advanced Access needs Business
Verification (submitted 2026-10-26, approved the same day: Security Center
shows "Verified" for TLG Beauty Limited, checked 2026-10-27) and then an App
Review submission on Tlg-app2. As of 2026-10-27 nothing has been added to the
submission yet ("Not submitted"), and `instagram_manage_messages` is still
"Ready for testing".

## Found 2026-10-27: the App Review route needs "Tech Provider" status

Clicking Actions > Add to App Review on `instagram_manage_messages` opens a
dialog: "To add a permission or feature to App Review, become a Tech
Provider ... This decision cannot be reversed." Not clicked. Meta's own
App Review guide for the Instagram Platform says App Review is **not
required** when "My app is only for a business I own or manage" and the
login type is "No login or Instagram Login" (Standard Access), and the
messaging API doc says Standard Access covers "Instagram professional
accounts you own or manage and have added to your app in the App
Dashboard". Our app uses the other route, Instagram API **with Facebook
Login** (Page token, graph.facebook.com), which is the one that needs
Advanced Access and therefore Tech Provider + App Review + screencast.

Business Verification alone did not fix delivery: a client's DM at 23:20 on
26 Oct (after the business was verified that day) never invoked the
Instagram Lambda.

Options:

1. **Become a Tech Provider and submit App Review** (the rest of this
   file). Irreversible status, stricter data-handling obligations, a
   screencast, and a review that third parties say takes one to four weeks.
2. **Switch Tlg-app2 to "API setup with Instagram login"** (recommended):
   add the salon's Instagram account as an Instagram tester on the app,
   generate an Instagram User token for it, point the webhook at the same
   gateway, subscribe `messages`, and change the Instagram Lambda to use
   graph.instagram.com, the Instagram app secret for the signature, the
   `instagram_business_manage_messages` permission and a 60-day token with
   a scheduled refresh. No App Review, no screencast, no Facebook Page in
   the path.

## Where

developers.facebook.com > Tlg-app2 > Use cases > Instagram API > Permissions
and features. For each permission below: Actions > Add to App Review. Then
App Review > Requests > the draft > fill in and submit.

Permissions to request, all used by the bot today:

| Permission | Why we need it (paste) |
|---|---|
| `instagram_manage_messages` | Receive Instagram DMs sent to our own salon account and reply to them from our booking assistant. |
| `instagram_basic` | Read our own Instagram account id and username so the webhook and replies address the right account. |
| `pages_show_list` | Find the Facebook Page our Instagram account is linked to, which the Instagram messaging API routes through. |
| `pages_read_engagement` | Read the Page profile fields the Instagram messaging API returns for the linked Page. |
| `business_management` | Our System User token is issued through the business portfolio that owns the Page and app. |

## The description (paste into "Tell us how you'll use this permission")

> The Looking Glass is a beauty salon in Shrewsbury, UK (TLG Beauty Limited).
> This app is used only by us, on our own Instagram professional account
> (@lookingglassbeautysalons), linked to our own Facebook Page. It is not
> offered to any other business.
>
> When a client sends our salon a DM on Instagram, the app receives it by
> webhook and replies in the salon's voice: it answers questions about our
> services, prices and opening hours, offers appointment times, and books
> nail appointments into our salon software. Anything it cannot handle is
> handed to a member of staff, who replies from Meta Business Suite as
> normal. Clients can ask for a person at any time.
>
> The same assistant already runs on our Facebook Page through Messenger
> (app tlg-app1). We are requesting advanced access so that Instagram DMs
> from clients, not just from our own team accounts, reach the assistant.
>
> Data use: messages are stored in our own AWS account (eu-west-2) only for
> the length of the conversation, so the assistant can keep context, and are
> deleted automatically after it ends. Nothing is shared with third parties
> or used for advertising. Privacy policy: https://tlg-beauty.co.uk/privacy-policy/

## The screencast

Meta wants a screen recording showing the permission in use, end to end:

1. Open Instagram on a phone as a test account that has a role on the app
   (so the DM is delivered today), and send the salon a DM such as "Hi, can I
   book gel nails on Thursday afternoon please?".
2. Show the bot's reply arriving in the Instagram thread within a few seconds.
3. Switch to Meta Business Suite > Inbox and show the same thread, with the
   reply marked as sent by the app, and a staff member able to reply by hand.
4. Optionally show the appointment appearing in Fresha's calendar.

Keep it under two minutes, no cuts, with the app name visible somewhere
(the Business Suite "sent by" label does this). Upload the file in the
submission; a phone screen recording plus a desktop recording stitched
together is fine.

## Also answer

- "Is this app used by a business other than yours?" No.
- "Does your app use Facebook Login?" Facebook Login for Business is on the
  app but only our own System User token is used; say so if asked.
- Test credentials: not applicable, there is no login for reviewers; say the
  app only serves our own account and point them at the screencast.

## While waiting

Instagram DMs from clients only appear in Business Suite, so the team answers
Instagram by hand. The Messenger bot is unaffected.
