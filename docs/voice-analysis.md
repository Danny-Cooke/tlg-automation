# Voice analysis: how the team talks to clients on Messenger

Date: 2026-10-20. Source: every conversation on the Facebook Page, pulled
through the Graph API with the Page token the bots already hold. The persona
in `persona/` (`jess.md`, `voice-guide.md`, `vocabulary.md`) was written
from this, replacing the earlier persona that had been written from guesses.

Re-run with `python scripts/message_history.py dump` then `stats` and
`transcript`. Output lands in `.local/messages/`, which is git-ignored
because it is client data. Instagram is not covered: the Page token does
not have `instagram_manage_messages`, so Instagram DMs cannot be read until
Tlg-app2 gets that permission.

## What was in the history

| | Count |
|---|---|
| Date range | 2026-01-31 to 2026-10-20 |
| Conversations | 283 |
| Messages | 2,853 |
| Sent by clients | 1,361 |
| Sent by the Page | 1,492 |
| Of which auto-replies (removed) | 568 |
| Of which human replies (analysed) | 924 |
| Conversations with at least one human reply | 201 |

## Auto-replies removed

Anything sent by the Page that a person did not type. Found by repetition
and by reply latency under five seconds, then confirmed by reading.

| Kind | Count | Text |
|---|---|---|
| Instant reply | 510 | "Your message has drifted gently into The Looking Glass. 🌷 We'll be along shortly..." |
| Ad greeting | 19 | "Hi [name]! Please let us know how we can help you." |
| Ad system note | 19 | "[name] replied to an ad." |
| Meta Business AI (Oct 2026) | 14 | "I've connected you with our team", "Thanks for reaching out to The Looking Glass Shrewsbury — how can we help", long em-dash replies about Halloween nails |
| "Fresha first" auto-reply (Oct 2026) | 2 | "Hello there. If your message is to book an appointment with us would you mind trying to book through fresha first..." |
| Our own test bot | 3 | "Hi, this is the TLG messenger test bot..." |
| Away message | 1 | "Thanks for your message. We're away and can't respond at this time." |

Two of these matter beyond the analysis. **Meta's Business AI has been
answering clients since mid-October** in a voice nothing like the salon's
(em dashes, "how can we help you today?", 80-word replies). It and the
instant reply will both fire alongside our bot unless they are switched off
in Meta Business Suite (Inbox > Automations). Decision needed before the bot
goes live.

Also removed from the human set: Meta's own "verified badge" and "policy
violation" phishing messages (clients' side), sales pitches, and the
"What's the price of a curly cut?" ad button, which generated 20 identical
one-line threads in a week.

## Who answers

The Page cannot say which person typed a reply, so the three voices were
separated by reading. Jess (signs "Jessie", "it's Jessie the salon manager")
handles nails, parties, jobs, complaints and everything general: most of
the 924. Lori-Dee introduces herself ("Hiya its Lori the hairdresser") and
takes every hair thread. Carmen answers tattoo quotes and some nails, in
lower case, and signs "thankyou carmen". Danny answered a handful on a live
stream night.

## The numbers behind the voice guide

| Measure | Value |
|---|---|
| Words per reply, median | 12 |
| Words per reply, 90th percentile | 35 |
| Replies ending in kisses (x, xx, xxx) | 72.5% |
| Replies containing an emoji | 16.1% |
| Replies containing a question | 27.9% |
| Replies containing an exclamation mark | 6.8% |
| Replies starting in lower case | 10.4% (mostly Carmen) |
| Reply latency, median | 9.8 minutes |
| Replies within 5 minutes | 43.8% |
| Replies within an hour | 66.6% |

Most-used words, as replies containing them: "lovely" 197, "absolutely" 46,
"beaut" 48, "no problem" 36, "amazing" 29, "sure" 25, "deposit" 25, "all
booked" 19, "no worries" 17, "so sorry" 17, "babe" 19, "pop" 15.

Openers: "Hey lovely" 59, "Hiya" 56, "Hi lovely" 32, then "Hey [name]" /
"Hi [name]", "Hey there", "Morning".

Emojis, by use: hearts (❤ ♥️ 💕 ♡ 🧡) 120, laughing (😂 🤣) 41, 💅 9, 😍 7,
😊 7, ✨, 👌, 👑, 🎩.

The reply latency is the evidence for the bot's typing-indicator pause: a
reply in under a second is not what clients are used to, and about half of
real replies land within five minutes.

## What the team actually does, in order

The booking choreography is the same in almost every thread:

1. Opener and answer ("Hey lovely, a luxury pedicure is £53 with gel toes").
2. Offer to book, or ask the one missing detail (treatment, who with).
3. Offer one or two concrete times ("We have 10am tomorrow?").
4. Take name, email and phone "for the system".
5. "All booked for you lovely xx".
6. Deposit: until about June, £10 by bank transfer, with the salon's account
   details pasted into the chat (Lori-Dee uses her own account and fee). From
   June, Fresha's confirmation email asks for card details instead, and the
   team explains "nothing is taken until after, it's just to protect us from
   no-shows".
7. Day-of: "running late" messages get "no worries lovely, see you soon".

The bot cannot do steps 3 to 6 (no Fresha write API, and bank details must
never be sent by a bot), so its version of the choreography is: answer,
narrow, link. That is written into `jess.md` and the voice guide.

## Other patterns worth knowing

- **Inspiration pictures** always get a compliment, then the caveat that no
  two artists are the same and the result will be "our version", then a
  price or a hand-off to Carmen.
- **Hair** is always a consultation first. Lori-Dee asks for photos in
  natural daylight plus inspiration photos before quoting colour, and tells
  curly-cut clients to arrive with clean hair styled as usual.
- **Aesthetics** is redirected every time to Bernadette's own Facebook page
  ("Re Fresh Aesthetics"), because she runs her own diary.
- **Complaints** (two in the history) are answered by Jess at length, in
  full sentences, explaining what happened and what she can offer, signed
  "Jess" or "Jessica". The register changes completely. The bot must not
  attempt these.
- **Cancellation policy** as stated to clients: same-day cancellations are
  chargeable; a late cancel needs a fresh deposit to rebook; an all-day
  tattoo cancelled on the day drew a £60 fee. Not in the repo's salon facts
  yet; listed in `knowledge/from-messages.md` for Jess to confirm.
- **Spam** gets nothing or "No thank you lovely".
- Regulars get a different Jess: "babe", "my love", in-jokes, "flipping
  hell, what did you do?". The bot stays on "lovely".

## What the bot inherits and what it does not

| Inherits | Does not |
|---|---|
| Openers, "lovely", kisses, hearts, short bubbles | "babe", "angel", "my love", "hun", "girl" |
| "Absolutely", "no worries", "pop in", "bless you" | Slot offers, "all booked", "I'll pop you in" |
| Price phrasing: "from £", "depending on length" | Bank details, deposits, fees |
| Picture compliment and "our version" caveat | Tattoo and custom-art quotes |
| Hand-off lines ("Carmen can price that") | Complaint replies, banter, swearing |
| Apology lines | Meta AI's em-dash register |

## Files

- `persona/jess.md`: identity, rules, hand-over triggers (system prompt).
- `persona/voice-guide.md`: the framework, by situation, with examples.
- `persona/vocabulary.md`: the word bank with counts.
- `knowledge/from-messages.md`: facts the team told clients that the repo did
  not have.
- `scripts/message_history.py`: dump, stats, transcript.
