"""Builds the HTML for the three course outline pages and the register-interest page on the
public website, from the same facts as academy/content/courses.json. Output: website/academy/pages/*.html,
each a block-editor Custom HTML block body. Run after editing courses.json."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "pages"
OUT.mkdir(exist_ok=True)
courses = {c["id"]: c for c in json.loads((ROOT / "academy" / "content" / "courses.json").read_text(encoding="utf-8"))["courses"]}
SLUGS = {"builder-gel": "builder-gel-cpd-course", "gel-polish": "gel-polish-nails-cpd-course", "acrylic": "acrylic-enhancement-cpd-course", "efile": "electric-file-cpd-course", "lash-brow": "lash-and-brow-tint-and-wax-cpd-course"}

CSS = """<style>
  .tlg-course { font-family: inherit; color: #1f2a28; max-width: 900px; margin: 0 auto; }
  .tlg-course * { box-sizing: border-box; }
  .tlg-course .tlg-banner { display: inline-block; background: #c9a24b; color: #1f2a28; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; font-size: .8rem; padding: .35rem .9rem; margin-bottom: 1rem; }
  .tlg-course p, .tlg-course li { line-height: 1.6; font-size: 1.1rem; }
  .tlg-course h2 { font-size: 1.6rem; color: #123d3a; margin: 1.8rem 0 .5rem; }
  .tlg-course dl { display: grid; grid-template-columns: max-content 1fr; gap: .4rem 1.2rem; margin: 1rem 0; }
  @media (max-width: 600px) { .tlg-course dl { grid-template-columns: 1fr; } }
  .tlg-course dt { font-weight: 700; color: #123d3a; }
  .tlg-course dd { margin: 0; }
  .tlg-course ol.tlg-syllabus { padding-left: 1.3rem; }
  .tlg-course ol.tlg-syllabus li { margin-bottom: .5rem; }
  .tlg-course .tlg-cta { display: flex; flex-wrap: wrap; gap: .8rem; margin: 1.8rem 0; }
  .tlg-course .tlg-btn { display: inline-flex; align-items: center; justify-content: center; min-height: 46px; padding: .6rem 1.4rem; border: 1px solid #123d3a; background: #123d3a; color: #fff; text-decoration: none; font-size: 1.05rem; letter-spacing: .03em; }
  .tlg-course .tlg-btn:hover { background: #0b2927; color: #fff; }
  .tlg-course .tlg-btn-gold { background: #c9a24b; border-color: #c9a24b; color: #1f2a28; }
  .tlg-course .tlg-btn-gold:hover { background: #b38d3b; color: #1f2a28; }
  .tlg-course .tlg-btn-outline { background: #fff; color: #123d3a; }
  .tlg-course .tlg-status { border-left: 4px solid #c9a24b; background: #fff8e6; padding: .8rem 1rem; margin: 1rem 0; }
  .tlg-course .tlg-small { font-size: .95rem; color: #5d6b68; }
</style>
"""

e = html.escape
for cid, c in courses.items():
    hours = f"{c['hours']:g} hours. {c['hours_breakdown']}" if c["hours"] else c["hours_breakdown"]
    syllabus = "".join(f"<li><strong>{e(s['title'])}.</strong> {e(s['detail'])}</li>" for s in c["syllabus"])
    outcomes = "".join(f"<li>{e(o)}</li>" for o in c["outcomes"])
    page = f"""{CSS}<div class="tlg-course">
  <span class="tlg-banner">Coming soon</span>
  <p>{e(c['description'])}</p>
  <div class="tlg-cta"><a class="tlg-btn tlg-btn-gold" href="/academy/register-interest/">Register your interest</a><a class="tlg-btn tlg-btn-outline" href="/academy/">All courses</a></div>
  <h2>Course details</h2>
  <dl>
    <dt>Course title</dt><dd>{e(c['title'])}</dd>
    <dt>Delivery</dt><dd>{e(c['delivery'].replace(' on this academy', '').replace(' and support materials on this academy', ''))}</dd>
    <dt>Duration</dt><dd>{e(hours)}</dd>
    <dt>Entry requirements</dt><dd>{e(c['prerequisites'])}</dd>
    <dt>Assessment</dt><dd>{e(c['assessment'])}</dd>
    <dt>Certificate</dt><dd>{e(c['certificate'])}</dd>
    <dt>Tutor</dt><dd>Jessica Jane Preston: VTCT Level 2 NVQ Diploma in Nail Services, Award in Education and Training, fourteen years in the industry, teaching since 2021.</dd>
  </dl>
  <h2>What you will learn</h2>
  <ul>{outcomes}</ul>
  <h2>Syllabus</h2>
  <ol class="tlg-syllabus">{syllabus}</ol>
  <h2>Accessibility</h2>
  <p>Tell us about any additional learning, accessibility or support needs when you register or at any time before the course. We provide large-print and digital materials, extra time for assessments, one-to-one support and other reasonable adjustments. The salon and training room are wheelchair accessible.</p>
  <div class="tlg-status"><strong>CPD accreditation status:</strong> this course has been submitted to The CPD Group for assessment against their ACCREDITED framework. It is not yet CPD accredited; this page will show the accredited activity number and a link to The CPD Register once accreditation is confirmed.</div>
  <div class="tlg-cta"><a class="tlg-btn tlg-btn-gold" href="/academy/register-interest/">Register your interest</a></div>
  <p class="tlg-small">The Looking Glass Beauty School (TLG Beauty Limited) is an approved provider with The CPD Group, provider number 789824. Approved provider status does not mean a course is accredited.</p>
</div>
"""
    (OUT / f"{SLUGS[cid]}.html").write_text(page, encoding="utf-8")
    print("wrote", SLUGS[cid], len(page))

interest = """<style>
  .tlg-interest { max-width: 760px; margin: 0 auto; color: #1f2a28; }
  .tlg-interest p { font-size: 1.1rem; line-height: 1.6; }
  .tlg-interest .tlg-small { font-size: .95rem; color: #5d6b68; }
</style>
<div class="tlg-interest">
  <p>Tell us which course you are interested in and we will email you when enrolment opens, with dates, prices and how to book. No obligation. Your details are used only to contact you about the academy; see our <a href="/privacy-policy/">privacy policy</a>.</p>
</div>
"""
(OUT / "register-interest.html").write_text(interest, encoding="utf-8")
print("wrote register-interest")
