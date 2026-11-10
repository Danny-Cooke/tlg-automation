# Gel Polish Nails CPD Course: how v2.0 was built, and what it answers

Built 26 October 2026 from scratch, to the standard of the Builder Gel course (`../builder-gel-course`). The June 2026 manual that went to The CPD Group as application #21252 is not in the repo and was not used; the assessor's report on it (`../../cpddocs/our-courses/gel-polish-nails-21252-assessment-report.md`) was.

## What the assessor still had open on #21252 (19 August 2026)

| Framework letter | Finding | Where v2.0 answers it |
|---|---|---|
| Content | Images on pages 9, 20 and 21 not anatomically correct | All clinical photographs are openly licensed medical images with author, licence and source credited (Figures 2 to 12); the nail-unit diagram (Figure 1) is the one that passed on Builder Gel |
| Content | Manual text-heavy; add images in anatomy, contraindications, nail conditions, equipment and treatment protocol sections | 22 figures: 11 photographs in Chapters 3 to 4, 11 original drawings in Chapters 6 to 8 and 11 to 14; 40 tables; boxed key points; every chapter opens with a one-line summary |
| Eligibility | Prerequisites in the Description | Level 2 prerequisite in Chapter 1, in G05 and in the paste-ready Description in `JESS - what to do in each file.md` |
| Details | Description is a web link; title lacks "CPD Course" | Title is "Gel Polish Nails CPD Course" on every document; Description written |
| Expertise | Author CV requested | Jess to write on the CPD template (resource 49) |

The letters already passed (Accessible, Creativity, Relevant, IP, Tested, Duration) are kept passing: same accessibility text, same 15 hours (1.5 + 7.5 + 6), separate theory and practical assessments now actually supplied (G02 to G04), a lesson plan (G05) with matching hours.

## Sources used for the gel-polish-specific content

- The CPD Group, "6 Simple Steps to writing your training materials" (portal resource 46): chapter order (introduction, legislation and health and safety, anatomy, treatment information with history, consultation, pricing and promotion, assessment, conclusion).
- British Association of Dermatologists press release, 9 August 2018, "Dermatologists issue warning about UK artificial nail allergy epidemic": the 4,931-patient audit, 2.4 per cent positive to a (meth)acrylate, 1.5 per cent to HEMA; gel polish described as a premixed hybrid of gel and varnish; under-curing and home kits as allergy risks. Cited in Chapter 6 (already in the reference list).
- American Academy of Dermatology, "Dermatologist's secret for removing gel nail polish at home" (Dr Shari Lipner): acetone soak about 10 minutes, never pick, scrape or file; petroleum jelly to protect skin; the nail takes about six months to grow out. Used for Chapter 14 and the never-peel advice.
- Regulation (EU) 2020/1682 (HEMA and di-HEMA TMHDC, professional use only) and SI 2026/23 and 2026/109 (TPO): carried over from the Builder Gel manual, where they were verified on legislation.gov.uk.
- Industry history (coloured lacquer in the 1920s and 1930s, light-cured gels from the 1980s, hybrid gel polish systems from 2010): consistent across trade sources; no single primary source, so Chapter 2 states it in general terms and names no brand except Shellac as a trade mark.
- Cure times, soak times and coat counts are written as "the manufacturer's time" and "10 to 15 minutes" because they vary by system; Jess checks them against the system she teaches with.

## What was carried over from the Builder Gel manual, and why that is legitimate

The Builder Gel manual is the school's own document. Its chapters on anatomy, conditions, consultation, chemistry, health and safety, legislation, contra-actions, aftercare, forms and references apply to every light-cured nail service and were kept, with every builder-gel-specific sentence rewritten (a scripted sweep plus hand edits; the only remaining mentions of builder gel are deliberate comparisons, the scope boundary and the "removing other products" table). The treatment chapters (2, 7, 12, 13, 14, 15) and the assessment pack were written fresh for gel polish.

## Build

- `build/figures.py` draws Figures 13 to 22 with matplotlib (original, school-owned).
- `build/build_manual.py` assembles G01 from the Builder Gel base, drops and inserts chapters, swaps figures, rewrites paragraphs and cells, restarts every numbered list, and sweeps the carried-over text for builder gel wording.
- `build/build_pack.py` writes G02 to G06 from scratch with python-docx.
- `G01 ... v2.0.pdf` in this folder is a Word export for checking (63 pages); upload the .docx files. The G02 to G06 PDFs could not be produced on 26 Oct: Word's automation hung on every python-docx-built file even after they passed schema validation, so those five were checked structurally only. Open them in Word before uploading.

## Figures redrawn 27 October 2026

Jess reviewed the manual and rejected Figures 15 and 16: not realistic, and the free edge not shown. The cause was the two shared drawing helpers in `build/figures.py` (a pentagon for the finger from above, a box for the finger in profile), so both were replaced rather than patched: `finger_top` draws a rounded fingertip with lateral folds, a proximal fold band and cuticle line, a lunula, a graded nail bed, a smile line and a free edge that projects past the fingertip in any of eight shapes (round, oval, square, squoval, short, almond, coffin, stiletto), with an optional colour coat (hairline gap, to the sidewalls, capped) and French tip; `nail_side` draws the finger in profile with a rounded pad, a plate that curves over the bed and projects as a whitish free edge, coats that follow the curve and wrap the edge; `nail_end` draws the free edge end-on with the cap. Every figure that used the old helpers was re-rendered and checked: 14, 15, 16, 18, 19, 21 and 22. Figure 16 grew from 7.3 to 8.6 inches tall and now fills page 29 on its own. The manual was rebuilt (still 63 pages, 22 figures, no blank pages) and the builder gained the `w:zoom` fix the Builder Gel base needs to pass schema validation. The acrylic course's figures use a separate copy of the old helpers and have not been redrawn yet.

## Verdict on v2.0 as built

Structurally it meets everything the assessor asked for on this course and on Builder Gel. The risks are the ones only Jess can close: no author CV yet, drawn rather than photographed technique figures, and the application's Description field. Expect a pass or a single minor round once those are done.

## Photographs added 2 November 2026 (manual v2.1)

Jess sent ten images by WhatsApp (originals in `photos-2026-11-02/`). Seven carry their own
"Figure N" titles and replace the drawn Figures 14, 15, 18, 19, 20, 21 and 22 under the same
numbers; four of them (15, 18, 20, 21) also had the caption and credit line baked into a bottom
strip, which was cropped off so the manual's own caption is not shown twice. Two photographs of
a finished red set went into Chapter 2 after "What gel polish is not", side by side in a
borderless table (two inline images in one paragraph wrap in Word), and the EL Nail Systems
"Gel Polish System Kit List" closes Chapter 8, after the LIGHT AND HEAT box. Both new insertions
are captioned without a figure number so the numbering in the images stays true. Every figure
and caption paragraph now has keep-with-next, so a caption can no longer fall onto the page
after its picture (this happened to Figures 19 and 22 on the first pass). 66 pages.

Done by `build/apply_photos_2026-11-02.py`, which reads the v2.0 build (now in this folder)
and writes v2.1 into `submit-to-cpd/`; it does not touch `build_manual.py`, so a rebuild of
v2.0 followed by this script reproduces v2.1. The drawings it replaced are in
`figures/drawn-v2.0/`; Figures 13, 16 and 17 are still drawings. The cover note went to v2.1
(`build/update_cover_note_2026-11-02.py`) and G07, the reflective practice form, was made from
The CPD Group's template 64 by `build/make_reflective_form.py`. Open questions for Jess are in
her checklist: whether the red-set photographs and the kit image are the school's own work
(credit lines), and whether the acid primer in the kit image becomes a standard step.

Later on 2 November Jess confirmed the pictures are the school's own (credit lines stand) and
that the acid primer is a standard step with the EL Nail Systems kit: `apply_photos_2026-11-02.py`
now also rewrites Chapter 11 step 9 and the kit-table row, and G04 went to v2.1 with the matching
preparation criterion (old G04 in this folder). The Figure 18 picture still says "bonder only if
the system uses one" in its step 6; only a re-exported picture can change that.

## Assessor's recommendations, 5 November 2026 (manual v2.2)

The CPD Group reviewed v2.1 and recommended enlarging the labels on Figure 1 (page 9) so they
read when printed; Jess also sent four more pictures on 4 November (Figures 18, 20, 21 and 22,
originals in `photos-2026-11-05/`). Figure 1 is the nail-unit drawing that passed on Builder
Gel and its drawing script was session scratch, so `build/fig01_relabel_2026-11-05.py` keeps
the artwork and changes only the lettering: it paints out the old 11 px labels, cuts the two
panels out of the 1780 px canvas, stacks the sagittal section under the dorsal view, and
rewrites every label at 28 px on a 1060 px layout, about 11 pt when the figure prints 5.3 in
wide (page 9: figure, caption and credit, then the Structures table heading). The old image is
`figures/drawn-v2.0/fig01_nail_unit.jpg`, the new one `figures/fig01_nail_unit.jpg` (2120 x
2998). Two leader lines that the old text touched were redrawn; one is anti-aliased on the output
canvas because PIL's own lines are not.

`build/apply_review_2026-11-05.py` reads v2.1 (now in this folder) and writes v2.2 into
`submit-to-cpd/`: Figure 1 at 5.3 in wide, Figures 18, 20, 21 and 22 replaced (bottom caption
strips cropped off; the 2 November versions kept in `figures/photo-v2.1/`), the credit under the
seven photographic figures changed to "Original photographs and artwork", version 2.2. Still 66
pages; validated against v2.1. G06 went to v2.2 (`build/update_cover_note_2026-11-05.py`) with a
paragraph saying what v2.2 answers. The Figure 18 picture still carries "bonder only if the
system uses one" in its step 6.

