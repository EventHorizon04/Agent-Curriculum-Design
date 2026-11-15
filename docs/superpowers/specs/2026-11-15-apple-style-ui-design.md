# Apple-style UI with UTCC colours

Date: 2026-11-15 · Branch: `feat/four-agent-pipeline` · Scope: `frontend/` only

## Intent

The app goes to UTCC faculty for real use. The designer wants it to look and feel like
apple.com — clean, generous whitespace, large clear type, pill buttons, rounded cards, a thin
translucent top bar — in UTCC's colours, **without showing UTCC** (no name, no logo, no seal).
The first page becomes an Apple-style launch page that doubles as a guide to using the app.
Technical terms in labels stay in English (Multi-agent, Single-agent, Need, PLO, SMART,
Knowledge, Skill …); explanatory sentences stay Thai.

## Goals

- One visual system across every page, done mostly through the shared tokens and component
  classes in `frontend/src/index.css`, so page markup barely changes.
- A new landing page at `/` that explains the workflow in four steps and the two agent modes.
- The left stage rail becomes a horizontal stage bar under a thin global top bar.
- Labels: technical terms in English, consistently.

## Non-goals

- No page-by-page re-layout of the dense work pages (PLO Synthesis, Need Analysis, Review,
  Report, Stakeholder Needs). They get the new look through the shared classes; a page that
  still feels cramped is a later, separate change.
- No backend, API or data change. No change to what any page does.
- No UTCC name, logo, seal or UTCC-specific font files.

## Anti-goals (a failure even if it works)

- Copying Apple's assets: no Apple logo, no SF Pro font files, no Apple product imagery or
  copy. Only the design language.
- Losing the meaning carried by colour today (see "Colour roles"). A restyle that makes an
  error look like an approval is a regression.
- Breaking any workflow, the single-agent rail rules, the running-job line, or mobile layout.

## Constraints

- Stack stays: Vite, React 19, Tailwind v4 (`@theme` tokens in `index.css`), react-router 7.
- Pages use component classes, not Tailwind palette colours (existing project rule). Counted
  today: `btn` 55, `notice` 53, `chip` 42, `btn-sm` 35, `panel` 31, plus ~60 direct token
  utilities (`text-mandate`, `bg-stamp`, `bg-marker-wash` …).
- Thai text needs generous line-height (stacked vowels/tone marks); keep body ≥ 1.6.
- Must work at 360 px wide.
- `npm run build` (tsc + vite) and `npm run lint` must pass; mock mode (`npm run dev:mock`)
  is the way to see every page without a backend.

## Approaches considered

- **A. Token + component + shell re-skin, new landing page (chosen by the designer).** Rewrite
  `index.css` tokens and component classes in the Apple language, rebuild the shell in
  `StageLayout.tsx` (top bar + stage bar), add the landing page, move the program list to
  `/programs`, switch labels to English technical terms. Pages inherit the look. Medium size,
  low workflow risk; dense pages keep their current arrangement.
- B. Redesign every page (13 pages, ~7.9k lines). Closest to Apple, very large, high risk of
  breaking working flows.
- C. Colours and fonts only, plus landing page. Cheapest, but the Apple feel comes from
  spacing, the nav and the type scale, so it would not read as Apple.

## Decisions taken with the designer

1. Approach A.
2. Audience: UTCC faculty, real use. UTCC colours yes, UTCC identity no.
3. `/` is an Apple-style launch page that teaches the workflow.
4. Labels: `multi-agent`/`single-agent` and other technical terms in English, not translated.
5. KSEC chips use full English names, no abbreviations: **Knowledge, Skill, Ethics,
   Character, Ethics & Character** (replaces `KSEC_LABEL` in `constants/stakeholder.ts`).
6. The soft SMART flag chip reads **"ข้อสังเกต N"** everywhere (PLO Synthesis, Review,
   Report — Review and Report already say "ข้อสังเกต"), with a hover tooltip:
   "AI แนะนำให้ทบทวน ไม่บล็อกการอนุมัติ — อาจารย์ตัดสินเองว่าจะแก้หรือไม่".
7. The left rail moves to a horizontal stage bar under the top bar.

Mockup the designer reviewed: `.superpowers/brainstorm/945-1794715137/content/look-v3.html`
(gitignored scratch; it is the visual reference for this spec).

## Design

### Colour roles (tokens)

The three meaning-bearing inks keep their meanings; only their hues move to UTCC's palette.
Token **names stay** (`stamp`, `mandate`, `marker`, `paper`, `sheet`, `graphite`, `pencil`,
`lead`, `hair` …) so no page class has to change; only values change.

| Role (token family) | Meaning (unchanged) | New value |
|---|---|---|
| `stamp` | the designer's act or approval, primary action, passed check | UTCC navy `#2e3191`; deep `#202570`; wash `#eceefa` |
| `marker` | warnings, soft flags (ข้อสังเกต), quoted evidence | UTCC gold `#ffc709`; wash `#fff6d6`; ink `#7a5a00` |
| `mandate` | requirement / สภาวิชาชีพ, blocking error, destructive | red `#c4161c`; deep `#9e1015`; wash `#fdecec` |
| ground (`paper`) | page ground | `#f5f5f7` |
| `sheet` | cards | `#ffffff` |
| text (`graphite` / `pencil` / `lead`) | primary / secondary / tertiary text | `#1d1d1f` / `#6e6e73` / `#86868b` |
| `hair` / `hair-strong` | dividers | `#d2d2d7` / `#c7c7cc` |

UTCC cyan `#00b1eb` is available as an accent for the landing page only; it carries no
meaning in the work pages. KSEC hues stay low-chroma categorical colours (current values
may be kept or lightly adjusted to sit on the new ground).

### Type

- UI and headings: system stack in the Apple manner —
  `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "Noto Sans Thai", sans-serif`
  (no SF font files shipped; Apple devices use their own, others fall back).
- Thai UI face: **Noto Sans Thai** from Google Fonts (400/500/600/700).
- PLO and Need statements (`record` class) stay **Sarabun**: it is the TH Sarabun New
  face มคอ.2 is typed in.
- Trirong, Anuphan and Chakra Petch are dropped. Labels/identifiers that used Chakra Petch
  use the UI face with `tabular-nums`.
- Scale: page titles ~40 px bold with tight tracking (`-0.02em`); landing hero clamp up to
  64 px; body 15–17 px.

### Components (in `index.css`)

- `btn`: pill (`border-radius: 980px`), `btn-primary` filled navy, `btn-secondary` navy
  outline, `btn-sm` smaller; a text-link style ("ดูหลักฐาน ›") for tertiary actions.
- `panel`: white card, radius ~18 px, no border, generous padding; sits on the `#f5f5f7`
  ground.
- `chip`: pill, small, soft wash backgrounds; KSEC chips use full names.
- `notice` / `notice-warn` / `notice-error`: rounded (~14 px) soft-wash blocks, no left rule.
- `stamp`, `record`, `marker`, `map-mark` and the rest keep their roles in the new style.
- Focus ring stays visible (navy).

### Shell (`StageLayout.tsx`)

- **Global top bar**: 48 px, sticky, translucent (`backdrop-filter: blur`), thin bottom hair.
  Left: wordmark "Curriculum Design Agent" (text, no logo) linking to `/`. Right: "วิธีใช้"
  (to the landing page's steps section), "หลักสูตรของฉัน" (`/programs`), "Pipeline"
  (`/pipeline`, hidden for single-agent programs as today), and a primary pill
  "เริ่มหลักสูตรใหม่" on the landing page.
- **Stage bar** (on work pages, not on `/` or `/programs`): sticky under the top bar,
  translucent. Left: the working program's name with faculty and mode
  ("Multi-agent"/"Single-agent") beneath. Right: the stages as pills, from `stagesFor(mode)`
  (single-agent still drops Skills and Review). Reached stages show a navy dot; the current
  stage is a dark filled pill; checkpoint stages (`gateNote`) carry a small marker meaning
  "คุณอนุมัติที่ขั้นนี้". On narrow screens the stage list scrolls horizontally.
- Stage labels shorten to English technical names: **Program, Evidence, Skills, Needs, PLO,
  Review, Report**. The Thai `summary` stays (tooltip on the pill and on each page).
- The session-status stamp and the running-job line keep their behaviour, restyled
  (running line = navy wash rounded strip).
- The old rail's gate legend (● ◐ ○) is replaced by the gate marker on the pills plus the
  explanation on the landing page.

### Routes

- `/` → new `Landing` page.
- `/programs` → the current `Programs` list (moved from `/`). Every link/navigation to `/`
  that means "program list" (about 10 sites, including "หลักสูตรทั้งหมด" and the
  "ยังไม่ได้เลือกหลักสูตร" link) points to `/programs`.

### Landing page (`/`)

Sections, top to bottom, as in the mockup:

1. Hero on `#f5f5f7`: eyebrow "Curriculum Design Agent", headline
   "จากเสียงผู้มีส่วนได้ส่วนเสีย สู่ PLO ที่ตรวจสอบได้", one-line lead, primary pill
   "เริ่มหลักสูตรใหม่" (→ `/intake` in creating mode, as the Programs page's create button
   does today) and a text link "ดูวิธีใช้ใน 4 ขั้น ›"; below, a floating card showing a
   sample PLO (static content).
2. "ใช้งานใน 4 ขั้น": four tiles — Program, Evidence, Needs, PLO — each with one Thai line
   and an "คุณอนุมัติ" tag on the checkpoint steps.
3. "เลือกวิธีให้ AI ทำงาน": Multi-agent and Single-agent tiles with 3 bullets each.
4. Three trust points: traceability to evidence, SMART checked by code rules, HITL.
5. Closing navy band with "เริ่มหลักสูตรใหม่" and "หลักสูตรของฉัน".

All landing copy is static; it calls no API.

### Labels

- `AGENT_MODE_LABEL_TH` → `Multi-agent` / `Single-agent`; the Intake mode options keep their
  Thai explanation after the English name.
- `KSEC_LABEL` → full English names (decision 5).
- Soft-flag chip → "ข้อสังเกต N" + tooltip (decision 6) on PLO Synthesis, Review, Report.
- Other labels that translate a technical term into Thai switch to the English term where
  the term is the app's own vocabulary (Need, PLO, SMART, Skill extraction, Pipeline …).
  Sentences and instructions stay Thai.

## Calls made after the builder check (author's calls, not the designer's)

1. **Links to `/`.** Every link or `navigate('/')` that means "choose a program" goes to
   `/programs`, including the "ไปหน้า Intake"-labelled links that point at `/` today
   (they send a designer with no program selected to the picker), `SingleRedirect`'s default
   target, and StageLayout's `picking` test (`pathname === '/programs'`). Only the top-bar
   wordmark and "วิธีใช้" go to the landing page. Nothing in a work flow lands on `/`.
2. **Layouts.** `/` and `/programs` render the top bar only: no stage bar, no program bar, no
   running-job line (today's `/` hides the last two as well). Every other route, `/pipeline`
   and `/intake` included, gets top bar + stage bar + running-job line. On `/intake` in
   creating mode the stage bar shows "หลักสูตรใหม่" in place of the program name, Program as
   current, nothing reached (today's `reached = -1`), and no running-job line (as today).
   The "หลักสูตรที่เลือกไว้: <id>" hint stays on that bar.
3. **Top bar items.** Wordmark → `/`; "วิธีใช้" → `/#steps` (the landing page scrolls to the
   element with that id after navigation); "หลักสูตรของฉัน" → `/programs`; "Pipeline" only on
   work pages of a multi-agent program; the primary pill "เริ่มหลักสูตรใหม่" on `/` and
   `/programs` only.
4. **Stage labels.** Multi-agent: Program, Evidence, Skills, Needs, PLO, Review, Report.
   Single-agent: Program, Evidence, Needs, PLO, Report (its PLO step stays the checkpoint
   and keeps the single-mode summary). `STAGE_LABELS` keeps its "ขั้นที่ N: label" shape with
   the English label. The ordinal moves into the pill's tooltip with the Thai summary
   ("ขั้นที่ 5 · หนึ่ง Need เป็นหนึ่ง PLO …").
5. **Label scope.** English technical terms apply to constants, the shell, and each page's
   `h1` title (which matches its stage pill, e.g. "PLO Synthesis", "Need Analysis",
   "Skill Extraction", "Stakeholder Evidence", "PLO Review", "PLO Report", "Pipeline").
   Buttons, notices and body sentences inside pages stay as they are.
6. **Fonts.** Loaded from Google Fonts as today (Noto Sans Thai + Sarabun replace the four
   current families). Self-hosting is a separate change if campus networks block it.
7. **Status stamp.** The session-status stamp drops the rotated double-rule frame and
   becomes a soft pill (navy wash for completed, gold wash for awaiting the designer, red
   wash for rejected/failed). Other `stamp` uses follow the same pill style.

## Left to the builder

- Exact spacing scale, shadow values, and how each existing component class maps onto the
  new look, guided by the mockup.
- KSEC hue tweaks, if any, to sit well on the new ground.
- Landing page responsive breakpoints (tiles stack below ~760 px).
- Which remaining Thai labels are "technical terms" — when unsure, keep Thai.
- Update `index.html` (Google Fonts link, `theme-color` → `#f5f5f7`) and the memory note on
  the old visual identity is superseded by this spec.

## Verification

- `npm run build` and `npm run lint` pass.
- Every page viewed in mock mode (`npm run dev:mock`, port 5174) at desktop width and at
  360 px: landing, programs, intake (create and edit), each multi-agent stage page, a
  single-agent program (stage bar drops Skills and Review; Pipeline hidden), the running-job
  line, an error notice, a warning notice, a soft-flag chip with its tooltip.
- No page uses a Tailwind palette colour introduced by this change.
