"""Generate docs/bot.drawio: two pages about the chat bot.

Page 1, "Bot architecture": the AWS pieces behind the Messenger and Instagram bot
(AWS 2024 icon set, mxgraph.aws4) and the outside services they talk to.
Page 2, "Bot workflow and personas": what happens to one DM, from the webhook to
the reply or the hand-over, next to the three registers Jess's persona switches
between and the hand-over rules. Both follow src/bot/handler.py, persona/jess.md and
docs/architecture.md; update them together.

Run from the repo root:
    python scripts/make_bot_drawio.py            # writes docs/bot.drawio
    python scripts/make_bot_drawio.py --url 2    # prints a viewer.diagrams.net link for page 2
Open the file at app.diagrams.net or in the draw.io desktop app.
"""
from __future__ import annotations

import base64
import html
import pathlib
import sys
import urllib.parse
import xml.dom.minidom
import zlib

OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "bot.drawio"
STAMP = "2026-11-08"

PTS = ("points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],[0,1,0],[0.25,1,0],[0.5,1,0],[0.75,1,0],[1,1,0],"
       "[0,0.25,0],[0,0.5,0],[0,0.75,0],[1,0.25,0],[1,0.5,0],[1,0.75,0]];")


def res(icon: str, fill: str) -> str:
    return (f"sketch=0;{PTS}outlineConnect=0;fontColor=#232F3E;fillColor={fill};strokeColor=#ffffff;dashed=0;"
            f"verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=11;fontStyle=0;aspect=fixed;"
            f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{icon};")


def gen(shape: str) -> str:
    return (f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor=#232F3E;strokeColor=none;dashed=0;"
            f"verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=11;fontStyle=0;aspect=fixed;"
            f"pointerEvents=1;shape=mxgraph.aws4.{shape};")


ORANGE, PINK, PURPLE, RED = "#ED7100", "#E7157B", "#C925D1", "#DD344C"
KIND = {
    "lambda": res("lambda", ORANGE), "apigw": res("api_gateway", PINK), "ddb": res("dynamodb", PURPLE),
    "sns": res("sns", PINK), "sched": res("eventbridge", PINK), "secrets": res("secrets_manager", RED),
    "ssm": res("systems_manager", PINK), "market": res("marketplace", "#232F3E"),
    "mobile": gen("mobile_client"), "email": gen("email_2"),
}
EXT = "rounded=1;whiteSpace=wrap;html=1;fillColor=#F2F3F3;strokeColor=#545B64;fontColor=#232F3E;fontSize=11;align=center;"
CLOUD = ("points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],"
         "[0,0.75],[0,0.5],[0,0.25]];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=14;fontStyle=1;"
         "container=0;pointerEvents=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;"
         "grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;verticalAlign=top;align=left;"
         "spacingLeft=30;fontColor=#232F3E;dashed=0;")
EDGE = ("edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endFill=1;"
        "strokeColor=#545B64;fontColor=#232F3E;fontSize=10;labelBackgroundColor=#ffffff;")
NOTE = "text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=11;fontColor=#545B64;"
TITLE = "text;html=1;align=left;verticalAlign=top;fontSize=22;fontStyle=1;fontColor=#232F3E;"
SUB = "text;html=1;align=left;verticalAlign=top;fontSize=11;fontColor=#545B64;"
ZONE = ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#545B64;dashed=1;fontColor=#545B64;fontSize=12;"
        "fontStyle=1;align=left;verticalAlign=top;spacingLeft=6;spacingTop=2;")

# flowchart shapes for page 2
STEP = "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#232F3E;fontColor=#232F3E;fontSize=11;align=left;spacingLeft=6;spacingRight=6;"
DECISION = "rhombus;whiteSpace=wrap;html=1;fillColor=#FFF4E5;strokeColor=#ED7100;fontColor=#232F3E;fontSize=11;"
QUIET = "rounded=1;whiteSpace=wrap;html=1;fillColor=#F2F3F3;strokeColor=#545B64;fontColor=#545B64;fontSize=11;align=left;spacingLeft=6;spacingRight=6;"
SEND = "rounded=1;whiteSpace=wrap;html=1;fillColor=#E8F5E9;strokeColor=#7AA116;fontColor=#232F3E;fontSize=11;align=left;spacingLeft=6;spacingRight=6;"
HANDOVER = "rounded=1;whiteSpace=wrap;html=1;fillColor=#FCE4EC;strokeColor=#E7157B;fontColor=#232F3E;fontSize=11;align=left;spacingLeft=6;spacingRight=6;"
CLAUDE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#EDE7F6;strokeColor=#8C4FFF;fontColor=#232F3E;fontSize=11;align=left;spacingLeft=6;spacingRight=6;"
CARD = ("rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#545B64;fontColor=#232F3E;fontSize=11;align=left;"
        "verticalAlign=top;spacingLeft=8;spacingRight=8;spacingTop=4;")
PANEL = ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#545B64;dashed=1;fontColor=#545B64;fontSize=12;"
         "fontStyle=1;align=left;verticalAlign=top;spacingLeft=6;spacingTop=2;")


class Page:
    def __init__(self, name: str, width: int, height: int):
        self.name, self.width, self.height = name, width, height
        self.cells: list[str] = []
        self.n = 1

    def add(self, style: str, value: str, x=0, y=0, w=0, h=0, *, edge=False, src="", dst="", extra="", points=()) -> str:
        self.n += 1
        i = f"c{self.n}"
        v = html.escape(value, quote=True).replace("\n", "&lt;br&gt;")
        if edge:
            pts = ("<Array as=\"points\">" + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points) + "</Array>") if points else ""
            self.cells.append(f'<mxCell id="{i}" value="{v}" style="{style}{extra}" edge="1" parent="1" source="{src}" target="{dst}">'
                              f'<mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>')
        else:
            self.cells.append(f'<mxCell id="{i}" value="{v}" style="{style}{extra}" vertex="1" parent="1">'
                              f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return i

    def node(self, kind: str, label: str, x: int, y: int, size: int = 52) -> str:
        return self.add(KIND[kind], label, x, y, size, size)

    def edge(self, a: str, b: str, label: str = "", extra: str = "", points=()) -> str:
        return self.add(EDGE, label, edge=True, src=a, dst=b, extra=extra, points=points)

    def xml(self, diagram_id: str) -> str:
        return (f'<diagram id="{diagram_id}" name="{html.escape(self.name, quote=True)}">'
                f'<mxGraphModel dx="1400" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
                f'page="1" pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0">'
                f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{"".join(self.cells)}</root></mxGraphModel></diagram>')


# --------------------------------------------------------------------------- page 1
def architecture() -> Page:
    p = Page("Bot architecture", 1600, 780)
    p.add(TITLE, "The Looking Glass chat bot: high-level architecture", 40, 20, 1000, 32)
    p.add(SUB, "One Lambda package behind one HTTP API, deployed twice (Messenger, Instagram); both run the same five steps. "
               "Terraform in terraform/, code in src/bot/, voice in persona/. Solid arrows: inside AWS. Dashed arrows: outside "
               f"services. State as of {STAMP}.", 40, 54, 1400, 20)
    p.add(CLOUD, "AWS Cloud: account tlg, eu-west-2 London", 340, 100, 960, 600)
    p.add(ZONE, "Bot Lambda, one package deployed twice: tlg-prod-messenger-bot and tlg-prod-instagram-bot (CHANNEL env). "
                "What each run does, left to right:", 360, 130, 920, 290)

    # outside, left
    clients = p.node("mobile", "Salon clients<br>Messenger and Instagram DMs", 90, 160)
    meta = p.add(EXT, "Meta platform<br>Messenger app and Instagram app:<br>webhooks in, Graph API replies out,<br>client's name from the profile API", 40, 300, 200, 80)
    # outside, right
    claude = p.node("market", "Claude Platform on AWS<br>Opus 5.5, London workspace,<br>IAM auth, billed via Marketplace", 1360, 160)
    fresha = p.add(EXT, "Fresha<br>public booking pages: real availability<br>(no login); internal dashboard API with<br>the owner's stored session: book, cancel,<br>create client, patch-test status", 1360, 300, 200, 100)
    telegram = p.add(EXT, "Telegram team group<br>one hand-over line per thread<br>for Jess, Lori-Dee and Carmen", 1340, 440, 200, 60)
    email = p.node("email", "Jess and ops<br>email record of hand-overs<br>and bookings", 1360, 560)

    # inside the zone
    bot_m = p.node("lambda", "tlg-prod-messenger-bot", 385, 245)
    bot_i = p.node("lambda", "tlg-prod-instagram-bot", 385, 330)
    persona = p.add(EXT, "Baked in at deploy: persona/jess.md, voice-guide.md and vocabulary.md (written from the real message history) "
                         "and the Terraform salon config (staff, services, prices, hours, booking links)", 480, 160, 380, 62)
    SX, SY, SW, SH = [480, 640, 800, 960, 1120], 240, 150, 160
    s1 = p.add(STEP, "<b>1. Receive and check</b><br>Verify Meta's signature, drop a duplicate delivery, fetch the client's name once, "
                     "store and stay quiet if the sender is staff or the thread is locked to Jess.", SX[0], SY, SW, SH)
    s2 = p.add(STEP, "<b>2. Gather the persona</b><br>System prompt = jess.md + voice-guide.md + vocabulary.md + the salon config, "
                     "then the thread so far and today's date and time.", SX[1], SY, SW, SH)
    s3 = p.add(CLAUDE, "<b>3. Decide with Claude</b><br>Opus 5.5 returns JSON: reply, escalate, who (jess, lori-dee, carmen), area, kind. "
                       "Tools on Fresha: check availability, book, cancel, create client, patch-test status.", SX[2], SY, SW, SH)
    s4 = p.add(SEND, "<b>4. Message the client</b><br>Record the turn, show typing dots, wait until about 10 s have passed, send the "
                     "reply through the Graph API. An opening message that is not ours gets nothing.", SX[3], SY, SW, SH)
    s5 = p.add(HANDOVER, "<b>5. Hand over when told</b><br>Lock the thread (quiet with Jess, watching with Lori-Dee or Carmen), one "
                         "Telegram line to the team group, an SNS email record.", SX[4], SY, SW, SH)

    # below the zone
    apigw = p.node("apigw", "API Gateway HTTP API<br>tlg-prod-webhook", 380, 480)
    conv = p.node("ddb", "DynamoDB conversations<br>last turns, seen ids,<br>hand-over lock, 30-day TTL", 560, 480)
    secrets = p.node("secrets", "Secrets Manager<br>app secrets, page tokens,<br>Telegram token", 740, 480)
    ssm = p.node("ssm", "SSM Parameter Store<br>Fresha owner session,<br>Telegram chat id", 940, 480)
    sns = p.node("sns", "SNS tlg-prod-escalations<br>hand-over and booking emails", 1140, 480)
    p.add(NOTE, "Not shown: the weekly Instagram token renewal, CloudWatch alarms, and the other stacks (client texts, Fresha watch, "
                "menu sync, Academy). The next page follows one message through step 3 and the persona rules.", 360, 650, 920, 36)

    p.edge(clients, meta, "DM", "exitX=0.3;exitY=1;entryX=0.3;entryY=0;")
    p.edge(meta, clients, "reply", "exitX=0.7;exitY=0;entryX=0.7;entryY=1;dashed=1;")
    p.edge(meta, apigw, "signed webhook POST", "exitX=1;exitY=0.25;entryX=0;entryY=0.5;")
    p.edge(apigw, bot_m, "", "exitX=0;exitY=0.5;entryX=0;entryY=0.5;", points=[(366, 506), (366, 271)])
    p.edge(apigw, bot_i, "", "exitX=0;exitY=0.5;entryX=0;entryY=0.5;", points=[(366, 506), (366, 356)])
    p.edge(bot_m, s1, "", "exitX=1;exitY=0.5;entryX=0;entryY=0.19;")
    p.edge(bot_i, s1, "", "exitX=1;exitY=0.5;entryX=0;entryY=0.725;")
    p.edge(persona, s2, "", "exitX=0.62;exitY=1;entryX=0.5;entryY=0;")
    for a, b in ((s1, s2), (s2, s3), (s3, s4), (s4, s5)):
        p.edge(a, b, "", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    p.edge(conv, s1, "thread", "exitX=0.5;exitY=0;entryX=0.7;entryY=1;")
    p.edge(secrets, s1, "tokens", "exitX=0.5;exitY=0;entryX=0.93;entryY=1;", points=[(766, 440), (620, 440)])
    p.edge(ssm, s3, "Fresha session", "exitX=0.5;exitY=0;entryX=0.67;entryY=1;", points=[(966, 440), (900, 440)])
    p.edge(s5, sns, "", "exitX=0.3;exitY=1;entryX=0.5;entryY=0;")
    p.edge(sns, email, "", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    p.edge(s3, claude, "prompt, history, tools", "exitX=0.5;exitY=0;entryX=0;entryY=0.5;dashed=1;", points=[(875, 112), (1345, 112), (1345, 186)])
    p.edge(s3, fresha, "availability, book, cancel", "exitX=0.8;exitY=0;entryX=0;entryY=0.5;dashed=1;", points=[(920, 125), (1330, 125), (1330, 350)])
    p.edge(s4, meta, "reply (Graph API)", "exitX=0.67;exitY=1;entryX=1;entryY=0.75;dashed=1;", points=[(1060, 630), (300, 630), (300, 360)])
    p.edge(s5, telegram, "hand-over line", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;dashed=1;", points=[(1305, 320), (1305, 470)])
    return p


# --------------------------------------------------------------------------- page 2
def workflow() -> Page:
    p = Page("Bot workflow and personas", 1760, 1180)
    p.add(TITLE, "One DM through the bot, and the three shapes Jess's voice takes", 40, 20, 1200, 32)
    p.add(SUB, "Left: what src/bot/handler.py does with each message. Right: the persona rules from persona/jess.md that decide "
               f"who answers and in what register. Grey boxes end with the bot saying nothing. State as of {STAMP}.", 40, 54, 1500, 20)

    X, W = 60, 300          # main column
    QX, QW = 420, 250       # quiet column
    y = 100

    def step(style, text, h=56, x=X, w=W):
        nonlocal y
        i = p.add(style, text, x, y, w, h)
        y += h + 34
        return i

    def quiet(text, at_y, h=56):
        return p.add(QUIET, text, QX, at_y, QW, h)

    s1 = step(STEP, "A client messages the Page on Messenger or Instagram. Meta POSTs the event to the webhook within a second.")
    s2 = step(STEP, "Check the app signature, parse the events, load the thread from DynamoDB (last turns, who has it).")
    y0 = y; d1 = step(DECISION, "Message id already seen?\n(Meta retry)", 70)
    q1 = quiet("Drop it.", y0 + 15, 40)
    y0 = y; d2 = step(DECISION, "Sender on the staff list, or test mode without the trigger word?", 90)
    q2 = quiet("Store the message, say nothing. Staff messaging the Page as themselves are never answered.", y0 + 17)
    y0 = y; d3 = step(DECISION, "Thread locked to Jess?", 70)
    q3 = quiet("Jess has it. Store the message, stay quiet until she clears the lock.", y0 + 7)
    s3 = step(STEP, "Mark the message seen (a retry during the call is now a duplicate), show the typing dots, check the Fresha owner session is alive.")
    y0 = y; d4 = step(DECISION, "Picture or attachment with no text?", 70)
    h1 = p.add(HANDOVER, "Holding line \"give me a little time to have a think\", hand over to Jess as a quote.", QX, y0 + 7, QW, 56)
    s4 = step(CLAUDE, "Ask Claude (Opus 5.5). System prompt = persona (jess.md, voice-guide.md, vocabulary.md) + salon config "
                      "(staff, services, prices, hours, booking links) + thread context. Tools on Fresha: check_availability, "
                      "book_appointment, cancel_appointment, create_client, patch_test_status. Answer is JSON: reply, escalate, "
                      "escalate_to (jess, lori-dee, carmen), area, escalation_kind, reason.", 130)
    y0 = y; d5 = step(DECISION, "Thread with Lori-Dee or Carmen, and this message is theirs?", 90)
    q5 = quiet("Theirs to answer in the inbox. Store it, stay quiet; keep reading for nails or beauty.", y0 + 17)
    y0 = y; d6 = step(DECISION, "escalate?", 60)
    send = p.add(SEND, "Record the turn, wait until about 10 s have passed since the message, send the reply through the Graph API.",
                 QX, y0 + 2, QW, 56)
    y0 = y; d7 = step(DECISION, "Locks the thread? complaint, quote, enquiry, cancellation fee, can't assist, no kind given, or anything hair", 110)
    h2 = p.add(HANDOVER, "No: a booking, a move or a patch test the bot handled or could not. Tell the team, keep talking.", QX, y0 + 27, QW, 56)
    s5 = step(HANDOVER, "First message on the thread: no reply at all, Jess answers first. Mid-thread: the holding line already in the reply.", 56)
    s6 = step(HANDOVER, "Lock the thread to the person named: Jess (quiet), Lori-Dee or Carmen (watching).", 56)
    s7 = step(HANDOVER, "One Telegram line to the team group (who, area, kind, reason, link to the thread) and an SNS email record.", 56)

    p.edge(s1, s2); p.edge(s2, d1); p.edge(d1, d2, "no"); p.edge(d2, d3, "no"); p.edge(d3, s3, "no"); p.edge(s3, d4)
    p.edge(d4, s4, "no"); p.edge(s4, d5); p.edge(d5, d6, "no"); p.edge(d6, d7, "yes"); p.edge(d7, s5, "yes"); p.edge(s5, s6); p.edge(s6, s7)
    p.edge(d1, q1, "yes"); p.edge(d2, q2, "yes"); p.edge(d3, q3, "yes"); p.edge(d4, h1, "yes"); p.edge(d5, q5, "yes")
    p.edge(d6, send, "no"); p.edge(d7, h2, "no")
    y_s7 = y - 34 - 56 + 28  # centre of the last step
    p.edge(h1, s7, "", "exitX=1;exitY=0.5;entryX=1;entryY=0.5;", points=[(700, y_s7)])
    p.edge(h2, s7, "then", "exitX=0.5;exitY=1;entryX=1;entryY=0.25;")
    p.edge(h2, send, "and", "exitX=1;exitY=0.5;entryX=1;entryY=0.75;", points=[(680, y_s7 - 20)])

    # ---- personas panel
    PX, PY, PW = 760, 100, 960
    CW, CH, GAP = 460, 250, 20
    p.add(PANEL, "Always Jess, three shapes: the register follows the treatment, the thread follows the person", PX, PY, PW, 30 + 2 * CH + 2 * GAP + 70)
    cx1, cx2 = PX + 20, PX + 20 + CW + GAP
    cy1 = PY + 30
    cy2 = cy1 + CH + GAP
    cy3 = cy2 + CH + GAP

    p.add(CARD, "<b>Jess, her own voice</b>: nails, beauty, lashes, aesthetics, parties, anything general<br><br>"
                "<b>Sounds like</b>: \"Hey lovely\", \"absolutely\", \"pop you in\", one or two sentences, \"xx\", at most one heart. "
                "British, Shropshire, never corporate.<br><br>"
                "<b>Does</b>: standard prices from the salon details (\"from £48\"); points to Fresha and offers to book it \"this end\"; "
                "looks up real free times and offers two or three; once the slot is settled books it straight away (no \"shall I pop you in?\") "
                "and reads it back as one statement; asks once about add-ons; cancels or moves outside 24 hours.<br><br>"
                "<b>Hands to Jess</b>: complaints, refunds, fee disputes; any price not on the list or anything from a picture (holding line, then quiet); "
                "jobs, collabs, models, giveaways (one line, then quiet); health questions; groups and parties; aesthetics advice "
                "(Bernadette answers); anything unsure.", cx1, cy1, CW, CH)
    p.add(CARD, "<b>Lori-Dee's shape</b>: hair<br><br>"
                "<b>Sounds like</b>: \"Hiya\", calmer, a single \"x\".<br><br>"
                "<b>Never books hair in chat.</b> Answers a plain list question (price, what is included, the patch-test rule), nothing more.<br><br>"
                "<b>Three doors</b>: Sophie named, one message in Jess's voice with Sophie's WhatsApp line. Lori-Dee named, \"that's one for Lori, "
                "she'll pick this up with you here\", hand over to Lori-Dee. Nobody named, ask once which hairdresser; never choose for them.<br><br>"
                "Colour is consultation and patch test first and priced from the hair, so a colour price is a quote for Lori-Dee.<br><br>"
                "Then quiet on hair, but still reading: nails or beauty from the same client get answered. A hair complaint is Jess's and locks.",
          cx2, cy1, CW, CH)
    p.add(CARD, "<b>Carmen's shape</b>: tattoos<br><br>"
                "<b>Sounds like</b>: low key, \"hey lovely\", one \"x\".<br><br>"
                "<b>Can say</b>: consultations are free, touch-ups are free once healed.<br><br>"
                "\"I want a tattoo\" gets one question: discuss it, or book a free consultation with Carmen? The consultation is booked from "
                "Carmen's free times, the only tattoo appointment the bot makes; the tattoo itself is booked by Carmen.<br><br>"
                "A price, a design, a picture, a cover-up, placement: one message in Carmen's own words (first person, the one exception) "
                "sending them to her WhatsApp, hand over to Carmen, quiet.", cx1, cy2, CW, CH)
    p.add(CARD, "<b>Hand-over rules, all shapes</b><br><br>"
                "Every hand-over names <b>who</b> (jess, lori-dee, carmen), <b>area</b> (nails, hair, tattoos, aesthetics, beauty, general) and "
                "<b>kind</b> (complaint, booking, cancellation or rebooking, cancellation fee, quote, can't assist anymore, spam, patch test).<br><br>"
                "<b>Lock</b> (bot goes quiet until a person clears it): complaint, quote, enquiry, cancellation fee, can't assist, no kind, "
                "and anything hair. On an opening message the bot sends nothing at all.<br><br>"
                "<b>Tell and carry on</b>: a booking or a move the bot made or could not make, a patch test booked with a treatment.<br><br>"
                "<b>Watching</b>: with Lori-Dee or Carmen the bot keeps reading and answers only its own areas.<br><br>"
                "Never \"it's Lori\" or \"Carmen here\": they say that themselves. Staff on the quiet list are never answered.",
          cx2, cy2, CW, CH)
    p.add(NOTE, "Sources: persona/jess.md (identity and rules), persona/voice-guide.md (how a reply is built), persona/vocabulary.md "
                "(the team's words), all derived from the Page's real message history (docs/voice-analysis.md). Salon facts are not in the "
                "persona: they come from terraform/salon.auto.tfvars and the Fresha-generated menu file at deploy time.",
          cx1, cy3, CW * 2 + GAP, 50)
    return p


def mxfile(pages) -> str:
    return (f'<mxfile host="app.diagrams.net" modified="{STAMP}T00:00:00.000Z" agent="tlg-automation" version="24.7.17" type="device">'
            + "".join(pg.xml(f"tlg-bot-{i}") for i, pg in enumerate(pages, 1)) + "</mxfile>")


def viewer_url(doc: str) -> str:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = c.compress(urllib.parse.quote(doc, safe="").encode()) + c.flush()
    return "https://viewer.diagrams.net/?highlight=0000ff&nav=1&title=bot.drawio#R" + urllib.parse.quote(base64.b64encode(data).decode(), safe="")


def main() -> None:
    pages = [architecture(), workflow()]
    doc = mxfile(pages)
    xml.dom.minidom.parseString(doc)
    if len(sys.argv) == 3 and sys.argv[1] == "--url":
        print(viewer_url(mxfile([pages[int(sys.argv[2]) - 1]])))
        return
    OUT.write_text(doc, encoding="utf-8")
    print("ok", OUT, [len(pg.cells) for pg in pages], "cells")


if __name__ == "__main__":
    main()
