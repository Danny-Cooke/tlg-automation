# Electric File (E-File) Nail Technique CPD Course: how v1.0 was built

Built 6 November 2026 from scratch, to the standard of the Gel Polish course (`../gel-polish-course`), as the fifth course on the provider contract (slot free; no application yet). The user asked for "an efile course and supporting documents just like the gel polish ... but make sure the syllabus is correct".

## The source material and why it was not used

`source/Efile Training _EVO Academy.doc` is a purchased manual (EVO Academy, BAAS-accredited footer). It was read for scope only. Its text is a short aims page, a generic hygiene section, a "drill anatomy" page, a bit list and a set of technique notes with rpm figures; its six images are a supplier's product shots and an Amazon-style bit chart. None of it could be reused: the images are not the school's to use, and several of its facts are wrong or unsafe (an autoclave "heating water under pressure to 100°", Barbicide and ammonia as "chemical sterilisation", a UV cabinet as a steriliser, "20 000 to 30 000 rpm" for the natural nail surface alongside "if you exceed 15 000 rpm you can severely damage the nail", 2 000 rpm for prepping). A plain-text copy is beside it for the record.

## What the course teaches (the syllabus)

Chapters 2, 6, 7, 8, 11, 12, 13, 14 and 15 are new; the other chapters are the school's own Builder Gel base rewritten for electric-file work. Technical content was written from first principles and checked against the standards and guidance in Chapter 21:

- The machine: control unit, handpiece, chuck (twist, push-pull, lever), 3/32 in (2.35 mm) shank versus 1/8 in hobby bits, speed versus torque, forward and reverse changed only when stopped, the pre-use check, what to look for in a machine (UKCA/CE marking, instructions in English, torque at low speed).
- Bits: carbide (flutes shave), diamond (grit scratches), ceramic, sanding bands (single use), silicone polishers, stone (porous, not used); shapes (large and small barrel, tapered barrel, cone, safety, flame, needle, backfill, mandrel) with where each never goes; grit, with the dental ISO 6360 colour code for diamond and the warning that carbide rings vary by maker; lifespan.
- Physics: friction heat from speed × pressure × grit × time on one spot; the flat bit; rotation versus travel (switch direction for the far sidewall); the heat check with the client as the thermometer; rings of fire; reading the dust and the sound.
- Speed ranges by task (Chapter 8 table, repeated in Chapter 7's task table and the figure captions): cuticle area 3 000 to 8 000 rpm with a safety bit; de-shining 3 000 to 5 000; gel polish to the base coat 8 000 to 15 000; builder gel 10 000 to 18 000; hard gel and acrylic bulk 15 000 to 25 000 falling as the layer thins; shaping 10 000 to 18 000; under the edge and polishing 5 000 to 12 000. Written as starting points, moved down by the plate and the hand, never up.
- Natural-nail preparation: the free edge by hand file; fold pushed back with a pusher; safety bit flat on the plate beside the fold; de-shining with a 240 band, shine only; hand tools on a thin plate or a client who cannot feel heat.
- Reduction and removal by product category (gel polish to base coat; soak-off builder reduced then soaked; file-off and hard gel reduced to a thin layer and hand-finished; acrylic bulk reduced then soaked 15 to 20 minutes; unknown product not filed): "the last layer is not yours".
- Shaping and finishing cured product; backfills shown, not assessed.
- Health and safety: dust (acrylate polymer and keratin, respirable, irritant and sensitiser; HSE SR13; LEV at source, less dust, fitted FFP2/FFP3, client offered mask and glasses); vibration (HAVS, Control of Vibration at Work Regulations 2005, RIDDOR-reportable); PUWER 1998; Supply of Machinery (Safety) Regulations 2008; Electricity at Work; WEEE including batteries; the TPO row and references removed as not relevant to the tool.
- Bit decontamination: brush, clean (detergent or ultrasonic), rinse, dry and inspect, disinfect for the contact time or autoclave where the maker allows, store dry; UV cabinet is storage; bands binned.

Deliberate decisions: no brand or machine named; "electric file" not "drill" throughout, with a boxed note explaining why; toenails in scope only for product removal on healthy nails; thickened nails, hard skin and podiatry out of scope; prerequisite of a product qualification plus current experience, because the practical needs a model wearing product and the course does not teach application.

## Documents

- `E01 ... Learner Manual v1.0.docx`: 21 chapters, 22 figures (Figures 1 to 12 carried from the base, Figure 1 the re-lettered version from Gel Polish v2.2 at 5.3 in wide; Figures 13 to 22 drawn by `build/figures.py`), 42 tables, about 23 200 words, 85 pages in Word (every chapter starts on a new page). Validated against the base with the docx skill's validator.
- `E02` theory paper (28 MCQ + 8 short + 2 scenarios, 50 marks, pass 40), `E03` mark scheme, `E04` practical sheet (20 criteria, 7 SC), `E05` lesson plan (15 hours: 1.5 + 7.5 + 6; practice on pre-coated fingers before the model), `E06` cover note (new application), `E07` reflective practice form (CPD template 64): `build/build_pack.py` and `build/make_reflective_form.py`.
- `JESS - what to do in each file.md/.docx` with the paste-ready application text; `build/make_checklist.py`.
- Website: `academy/content/courses.json` has an `efile` entry (placeholder, 15 hours) and `website/academy/pages/electric-file-cpd-course.html` is generated; the card is in `website/academy/courses-section.html`. Publishing needs the WordPress login.

## Build

- `build/nail_helpers.py` is the first 299 lines of the Gel Polish `figures.py` (the fingertip, profile and end-on drawing helpers and the palette), copied so the course is self-contained.
- `build/figures.py` draws Figures 13 to 22 with matplotlib (bits drawn as shank plus head with flute, grit, band or silicone texture). Figure numbers follow the order the figures appear in the text; the rotation figure is 17 and sits in Chapter 8 before rings of fire (18).
- `build/build_manual.py` opens the Builder Gel base, drops its product chapters, inserts the new chapters, rewrites every carried-over paragraph and cell that mentioned gel, lamps or builder gel (REWRITE, CELL, CELL_BY_TEXT, ADD_ROWS, DROP_PARAS), restarts numbered lists, swaps Figure 1, sets page breaks before chapters and keep-with-next on figures and captions. Its leftover check prints any carried-over text that still mentions gel or lamp; everything it prints now is deliberate.
- PDF export with Word COM for checking (`working-files/E01 ... v1.0.pdf`); upload the .docx files.

## Open points for Jess

Listed in her checklist: the title wording, the entry requirement, the speed ranges, the pre-coated practice fingers, the insurer line, whether backfills are assessed, photographs to replace the drawings, the CV, the evaluation form, and the website page needing the WordPress login.
