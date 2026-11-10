# Liquid and Powder Acrylic Enhancement CPD Course: how v1.1 was built, and what it fixes

Built 27 October 2026 from the school's own `A01 Acrylic Learner Manual v1.docx` (the file uploaded to application #20893 on 26 October 2026 and now with the assessor). The v1 file is kept untouched in this folder; `submit-to-cpd/` holds v1.1 and the new pack. The assessor's report of 22 July 2026 was never captured (the course was back in review before it could be read), so v1.1 answers the points the assessors have made on the other three courses, which are the same framework letters every time.

## What v1 had wrong

The v1 manual was written on the same template as the Builder Gel and Gel Polish manuals, and the gel-polish wording had not all been converted. Found by a scripted sweep for lamp, cure and gel terms, then read:

| Where | v1 said | v1.1 says |
|---|---|---|
| Figure 13 (the only technique figure) | The gel-polish apex image: titled "Figure 3", "Gel-polish scope is the top panel only", "Separate builder-gel training required", "Outside this course" | Redrawn as Figure 15, apex and the three zones for an enhancement |
| Two unplaced images in the file | The gel-polish photopolymerisation and nail-shapes drawings, embedded but never shown | Removed from the file |
| Figure 2 caption, Ch. 3 and 4 | "Do not apply or reapply gel polish"; "keep uncured gel away"; "incompatible lamps, thick coats"; "unable to keep hands in the lamp" | Enhancement, wet product, ratio, extension length |
| Ch. 5 consultation and plan | "compatible lamp", "cure times", "base, colour and top", "French finish or nail art" | Tip or form, length and shape, infill interval; full set, overlay, infill and rebalance, repair, removal |
| Ch. 9 | "uncured gel, inhibition layer" as a skin route; "lamp touch points"; "do not continue gel application"; "lamp and extraction" | Monomer, wet product, primer, dust; extractor; product application |
| Ch. 10 | "as at August 2026"; "Electrical and lamp checklist" for "the gel system"; TPO row with no acrylic relevance; lamps in the Electricity and WEEE rows; ASA table "cosmetic colour coating", "Completed the Gel Nail Polish CPD Course", "chip-free for 14 days" | October 2026; extraction checklist; TPO row explains why it is there; extractor; acrylic claims and the right course name |
| Ch. 17 | "heat spike during cure", "uncured gel in fold", "do not apply gel", "document product/lamp/batch", "coating separates" | Warmth as product sets, wet product on skin, enhancement cracks |
| Ch. 17 and 18 | "wiping gel onto gloves, towels or lamp surfaces"; "residual gel contamination"; "prise the coating"; "removal/reapplication every 2 to 3 weeks" | Dappen dish, brush and desk; dust from unset product; enhancement; infill every two to three weeks |
| Forms A, C, D, E, G, H | "Previous gel service"; "ability to use the lamp"; "Lamp make/model and cure schedule"; "Cure schedule"; Form G "Product and lamp compatibility record" with base/colour/top and cure-time columns; "use compatible products and lamps" | Enhancement history; tip or form, length and shape; Form G is a product system record (monomer, powder, primer, SDS, supplier, date) |
| Title | "Liquid-and-Powder" with hyphens | "Liquid and Powder Acrylic Enhancement CPD Course", as the application has it |

## What was added for the framework

- **Content and Creativity:** thirteen original figures where the assessors have asked for images every time, in Chapters 6, 7, 8, 9, 11, 12, 13, 14 and 15 (how acrylic sets; reading the bead; apex and zones; the three views; nail shapes; files; dust and vapour controls; preparation; tip and form; building in zones; filing and refining; infill and rebalance; removal). Drawn by `build/figures.py`; the school owns them.
- **Treatment information per the "6 Simple Steps" guide:** Chapter 2 gained "Where liquid-and-powder acrylic came from" and "Service time, pricing and promotion" (framework only, no figures).
- **Tested:** Chapter 1 now states the seven safety-critical practical criteria, the model requirement and where A02 to A04 live; the theory line says 38 questions. The pack itself is new: A02 paper, A03 mark scheme, A04 marking sheet (20 criteria, 7 safety-critical), A05 lesson plan (7.5 guided learning hours on the day; 19.5 hours in all, matching the manual's duration table), A06 cover note.
- **Conclusion:** new Chapter 19 (recap of the ten outcomes, feedback and reflection, certificate and insurance, building confidence, further training); old 19 to 21 became 20 to 22.
- **Accuracy:** the MMA position was checked. MMA is not in Annex II of the retained Cosmetics Regulation (no annex entry exists for it), so the manual's "not illegal, but unsafe" line stands; added that some licensing authorities prohibit it by name (Dundee City Council's nail bar conditions) and that ECHA's Risk Assessment Committee recommended in March 2021 that it be classified as a respiratory sensitiser as well as a skin sensitiser. HSE SR13 exists and says what the manual says (LEV as a downdraught table or hood; face coverings are not a control; health surveillance for asthma and dermatitis); its PDF is dated 2019, so the reference year was corrected from 2025. The 1950s dentist origin and the late-1970s FDA action are from Braintree District Council's technician update (2012) and consistent trade histories. Four references added.

## Hours

Kept at 19.5 (3 pre-course, 7.5 on the day, about 9 for three case studies) because that is what the v1 manual says and, presumably, what the application says. If the application says something else, the application wins: change the duration table, the Chapter 1 hours line, A05 and A06 together.

## Build

- `build/figures.py` draws Figures 13 to 25.
- `build/build_manual.py` rewrites paragraphs and cells by prefix, drops the old Figure 13, inserts the figures, Chapter 2 sections, Chapter 1 additions, Chapter 19 and the new references, restarts every numbered list, tidies the form tables and strips the orphan images. It prints any rewrite that did not land.
- `build/build_pack.py` writes A02 to A06 with python-docx.
- `A01 ... v1.1.pdf` here is a Word export for checking (66 pages after the 27 October redraw, no blank pages). The A02 to A06 PDFs were not produced: on this machine Word's automation hangs on python-docx-built files, so those five were checked against the schema (all pass) and structurally. Open them in Word before uploading.
- Once Jess has edited a .docx by hand, do not re-run the build over it.

## Verdict on v1.1 as built

Everything the assessors have asked for across the four courses is now structurally present. The risks are the ones only Jess can close: the July report's specific points (unknown), the author CV, the application's Description and duration fields, and photographs of real technique if she wants to go beyond drawings.

## Figures redrawn 27 October 2026

Jess rejected the Gel Polish manual's nail drawings on 27 October (not realistic, free edge not shown), and this course's drawings came from a copy of the same crude helpers. Figures 15, 16, 17 and 20 to 25 were redrawn with the shared helpers now in `build/figures.py`, identical to the Builder Gel and Gel Polish scripts: `finger_top` (rounded fingertip, lateral folds, proximal fold and cuticle line, lunula, graded bed, smile line, free edge projecting past the fingertip in any of eight shapes, optional product layer), `tip_top` (a plastic tip fitted over the free edge from above), `finger_side` (the finger in profile with a rounded pad, a curved plate and whitish free edge, and a plastic tip or a sculpting form beyond it, the form optionally dropped or tilted for the fault panels), `enhancement` (product along that profile: hairline gap, apex, credit-card edge wrapped at the end; flat coats, a regrowth ledge, a flat spot) and `nail_end` (the barrel view, even or uneven). Figures 13, 14, 18 and 19 have no nail in them and are unchanged. The manual was rebuilt (66 pages, 25 figures, no blank pages, validated). `build_manual.py` now honours an `A01_OUT` environment variable so it can build elsewhere while the real file is open in Word.

## Jess's pictures in, 9 November 2026 (manual v1.2, pack v1.2)

Fourteen WhatsApp pictures arrived in the course folder at 11:36 with the note that the first goes under "what liquid and powder is", the second in the infill and rebalance section, the third shows the EL Nail Systems product used on the course, and the rest replace figures. `working-files/build/apply_photos_2026-11-09.py` takes v1.1 to v1.2: the finished dark set after the "What liquid-and-powder acrylic is" text (page 6, 4 in wide), the red almond set after Figure 24 in the infill section (page 53, 4 in), the powder pot closing Chapter 8 after the storage bullets (page 33, 4.5 in), all three captioned without a figure number; Figures 1, 14, 15, 16, 19, 20, 21, 22, 23, 24 and 25 replaced under the same numbers at 6.3 in (pages 9, 25, 27, 29, 39, 46, 48, 49, 51, 52, 54), the drawings they replaced in `figures/drawn-v1.1/` (Figure 1's old image extracted from the document as `fig01_nail_unit_drawn.jpg`); crops where a picture repeated text the manual prints: Figure 1 at 585 px (its caption), Figure 14 at 630 px (the set-time panel and bead-size examples; the section of that name follows the figure), Figure 15 at 668 px (the "four things" table), Figure 16 at 752 px ("Check from every angle"), Figure 19 to rows 165 to 1140 (blank top, caption and credit), Figure 20 at 880 px (caption), Figure 21 at 782 px (caption); Figures 22 to 25 whole. Credit lines on the eleven now "Original photographs and artwork © The Looking Glass Beauty School, 2026"; the IP paragraph on page 2 says "Original diagrams and photographs". Figures 13, 17 and 18 remain drawings. Version line "Version 1.2 — November 2026"; 71 pages (was 66); validator passed. `bump_pack_2026-11-09.py` renamed A02 to A06 to v1.2 ("Version 1.2, November 2026"), updated the A06 enclosures table and its sentence about the images, and exported the PDFs. Received files are in `figures/source-2026-11-09/`.
