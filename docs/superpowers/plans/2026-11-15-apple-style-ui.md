# Apple-style UI in UTCC colours Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the whole frontend in an Apple-like design language with UTCC colours, add an Apple-style landing page that teaches the workflow, and replace the left stage rail with a top bar plus horizontal stage bar.

**Architecture:** The look lives in `frontend/src/index.css` (Tailwind v4 `@theme` tokens + `@layer components` classes); pages already use those classes, so restyling them restyles every page. Token *names* stay, only values change. The shell in `StageLayout.tsx` is split into `TopBar` and `StageBar`; a new `Landing` page takes `/` and the program list moves to `/programs`.

**Tech Stack:** Vite 8, React 19, TypeScript 6, Tailwind CSS v4, react-router-dom 7. No test runner exists in `frontend/`; verification is `npm run build`, `npm run lint`, grep checks with exact expected output, and a visual check in mock mode (`npm run dev:mock`, port 5174, needs no backend).

**Spec:** `docs/superpowers/specs/2026-11-15-apple-style-ui-design.md` (read it; the mockup it cites is `.superpowers/brainstorm/945-1794715137/content/look-v3.html`, open it in a browser for the visual target).

## Global Constraints

- Frontend only (`frontend/`). No backend, API or data change; no page changes what it does.
- No UTCC name, logo or seal anywhere. No Apple logo, no SF Pro font files, no Apple imagery.
- Token names stay (`paper`, `sheet`, `sunk`, `hair`, `hair-strong`, `graphite`, `pencil`, `lead`, `stamp*`, `mandate*`, `marker*`, KSEC `k/s/ec/e/c`); values change. Pages use component classes, never Tailwind palette colours (`gray-*`, `blue-*` …).
- Colour values (verbatim from spec): stamp `#2e3191`, stamp-deep `#202570`, stamp-wash `#eceefa`; marker `#ffc709`, marker-wash `#fff6d6`, marker-ink `#7a5a00`; mandate `#c4161c`, mandate-deep `#9e1015`, mandate-wash `#fdecec`; paper `#f5f5f7`; sheet `#ffffff`; graphite `#1d1d1f`, pencil `#6e6e73`, lead `#86868b`; hair `#d2d2d7`, hair-strong `#c7c7cc`. Cyan `#00b1eb` only on the landing page, carrying no meaning.
- Fonts: UI `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", "Noto Sans Thai", sans-serif`; record (PLO/Need text) `"Sarabun", "Noto Sans Thai", sans-serif`. Google Fonts loads Noto Sans Thai 400/500/600/700 and Sarabun 400/500 only. Trirong, Anuphan, Chakra Petch are removed.
- Thai body line-height ≥ 1.6. Layout works at 360 px wide.
- Technical terms in labels are English; sentences, buttons and notices stay Thai; page `h1` titles are Thai (table in Task 2).
- Every commit: `git branch --show-current` must print `feat/four-agent-pipeline`; stage by explicit path; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Each task ends with `npm run build` and `npm run lint` passing (run inside `frontend/`).

## Review Focus

1. A single-agent program: stage bar shows only Program, Evidence, Needs, PLO, Report and no Pipeline link — Task 4 step "single-agent check".
2. `/intake` opened from "เริ่มหลักสูตรใหม่" (creating mode): stage bar says "หลักสูตรใหม่", nothing reached, no running-job line — Task 4 step "creating check".
3. A work page with no program selected: stage bar shows the "ยังไม่ได้เลือกหลักสูตร" prompt linking to `/programs`, never to `/` — Task 3 grep check + Task 4 visual check.
4. 360 px wide: top bar does not wrap or overflow, stage pills scroll horizontally, landing tiles stack — Task 4 and Task 3 visual checks.
5. "วิธีใช้" clicked from a work page lands on `/` scrolled to the steps section — Task 3 step "hash check".

---

### Task 1: Design system in `index.css` and `index.html`

**Files:**
- Modify: `frontend/src/index.css` (whole `@theme` block and `@layer base`/`@layer components`; keep the run-dial keyframes and `@property` rules working)
- Modify: `frontend/index.html` (Google Fonts link, `theme-color`)

**Interfaces:**
- Produces: the same class names as today (`page-title`, `section-title`, `eyebrow`, `panel`, `btn`, `btn-sm`, `btn-primary`, `btn-secondary`, `btn-quiet`, `btn-danger`, `btn-danger-quiet`, `link`, `field-label`, `field-hint`, `input`, `chip`, `chip-neutral`, `chip-stamp`, `chip-mandate`, `chip-marker`, `notice`, `notice-error`, `notice-warn`, `notice-info`, `table`, `record`, `marker`, `stamp`, `stamp-mandate`, `stamp-pending`, `map-mark*`, `run-dial*`, `data`), plus one new class `btn-text` (tertiary text action, navy, trailing " ›" added by the caller, no background). Later tasks use these names only.

- [ ] **Step 1: Replace token values** in `@theme` with the Global Constraints values; set `--font-ui` and `--font-record` to the stacks above; point `--font-display` and `--font-label` at the UI stack (keeps existing `font-display`/`font-label` utilities valid). Keep KSEC hues unless one is unreadable on `#f5f5f7`.

- [ ] **Step 2: Restyle base and components** to the mockup:
  - body: ground `paper`, text `graphite`, UI font, 15px, line-height 1.6; `::selection` marker; focus ring 2px `stamp`, offset 2px.
  - `page-title`: ~2.5rem (40px), weight 700, letter-spacing -0.02em, line-height 1.2 (allow Thai marks); `section-title` ~1.25rem/600.
  - `eyebrow`: UI font, 0.8125rem, 600, colour `stamp`, no letter-spacing.
  - `panel`: `sheet`, no border, radius 18px.
  - `btn`: radius 980px (pill), px 1.25rem py 0.625rem, 15px/500; `btn-sm` 13px px 1rem py 0.5rem; `btn-primary` filled `stamp` → hover `stamp-deep`; `btn-secondary` transparent with 1px `stamp` border and `stamp` text, hover `stamp-wash`; `btn-quiet`/`btn-danger*` keep roles in pill shape; new `btn-text` = no border/background, `stamp` text, hover underline.
  - `link`: `stamp`, no underline until hover.
  - `input`: radius 12px, 1px `hair-strong`, focus border `stamp` + ring `stamp`/20.
  - `chip*`: pill radius, px 0.625rem, 12px/500, UI font, no ring on `chip-neutral` (background `paper`, text `pencil`).
  - `notice*`: radius 14px, no left border, padding 0.875rem 1rem; colours unchanged by role.
  - `table th`: UI font, no uppercase.
  - `stamp`: soft pill — no rotation, no double border, no blend; `stamp` = `stamp-wash` bg / `stamp` text; `stamp-mandate` = `mandate-wash`/`mandate`; `stamp-pending` = `marker-wash`/`marker-ink`.
  - `record`: Sarabun stack, 1.125rem, line-height 1.7.
  - `.data` and `.eyebrow` that used Chakra Petch: UI font with `font-variant-numeric: tabular-nums`.

- [ ] **Step 3: Update `index.html`**: replace the font `<link>` with `https://fonts.googleapis.com/css2?family=Noto+Sans+Thai:wght@400;500;600;700&family=Sarabun:wght@400;500&display=swap`; set `<meta name="theme-color" content="#f5f5f7">`.

- [ ] **Step 4: Verify**

Run (in `frontend/`): `npm run build && npm run lint`
Expected: both exit 0.
Run: `grep -cE "Trirong|Anuphan|Chakra" index.html src/index.css`
Expected: `index.html:0` and `src/index.css:0`.
Run: `grep -c "rotate(" src/index.css`
Expected: `0` (the only `rotate(` today is the stamp's tilt).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/index.css frontend/index.html
git commit -m "feat(ui): Apple-style design tokens and components in UTCC colours"
```

---

### Task 2: Labels, page titles and the review-note chip

**Files:**
- Modify: `frontend/src/constants/stages.ts` (labels, single-mode override, `STAGE_LABELS`)
- Modify: `frontend/src/constants/stakeholder.ts` (`KSEC_LABEL`)
- Modify: `frontend/src/pages/Intake.tsx` (`AGENT_MODE_OPTIONS`, h1)
- Modify: page `h1` in `StakeholderNeeds.tsx`, `SkillExtraction.tsx`, `NeedAnalysis.tsx`, `PloSynthesis.tsx`, `PloReview.tsx`, `PloReport.tsx`
- Create: `frontend/src/components/ReviewNoteChip.tsx`
- Modify: soft-flag chip sites `PloSynthesis.tsx:~830`, `PloReview.tsx:~429,~455`, `PloReport.tsx:~677,~687`

**Interfaces:**
- Produces: `StageDef.label` values in English; `AGENT_MODE_LABEL_TH` keeps its name, values `'Multi-agent'` / `'Single-agent'`; `ReviewNoteChip({ count?: number }): JSX.Element`.

- [ ] **Step 1: Stage labels** in `STAGES`: intake `Program`, stakeholder_needs `Evidence`, skill_extraction `Skills`, need_analysis `Needs`, plo_synthesis `PLO`, plo_review `Review`, plo_report `Report`. `summary` and `gateNote` stay Thai. In `stagesFor('single')` the plo_synthesis override sets `label: 'PLO'` (keep its Thai summary and the review's gateNote). `STAGE_LABELS` keeps `` `ขั้นที่ ${s.ordinal}: ${s.label}` ``.

- [ ] **Step 2: Mode and KSEC labels.** `AGENT_MODE_LABEL_TH = { multi: 'Multi-agent', single: 'Single-agent' }`. `KSEC_LABEL = { K: 'Knowledge', S: 'Skill', EC: 'Ethics & Character', E: 'Ethics', C: 'Character' }`. Intake options: `'Multi-agent (4 agents): แต่ละขั้นมีตัวแทนของตัวเอง มีการโหวตและตรวจซ้ำ'` and `'Single-agent: LLM ตัวเดียวทำทุกขั้นและตรวจงานตัวเอง'`. Search every other use of `KSEC_LABEL` and of a hard-coded `'K · '`, `'S · '` style label and keep them reading the map.

- [ ] **Step 3: Page titles (Thai, exact)**

| File | h1 |
|---|---|
| `Intake.tsx` | ข้อมูลพื้นฐานของหลักสูตร |
| `StakeholderNeeds.tsx` | ข้อมูลผู้มีส่วนได้ส่วนเสีย |
| `SkillExtraction.tsx` | สกัดทักษะ |
| `NeedAnalysis.tsx` | วิเคราะห์ความต้องการ |
| `PloSynthesis.tsx` | สังเคราะห์ผลลัพธ์การเรียนรู้ (both modes; drop the `single ? 'ตรวจ PLO'` branch) |
| `PloReview.tsx` | ทบทวนผลลัพธ์การเรียนรู้ |
| `PloReport.tsx` | รายงานผลลัพธ์การเรียนรู้ |

`Pipeline.tsx` and `Programs.tsx` keep their titles.

- [ ] **Step 4: `ReviewNoteChip`** — renders `<span className="chip chip-marker" title="AI แนะนำให้ทบทวน ไม่บล็อกการอนุมัติ — อาจารย์ตัดสินเองว่าจะแก้หรือไม่" style={{cursor:'help'}}>` with text `ข้อสังเกต` or `` `ข้อสังเกต ${count}` `` when `count` is given. Use it:
  - `PloReview.tsx` and `PloReport.tsx`: replace each `<span className="chip chip-marker mr-1.5">ข้อสังเกต</span>` with `<ReviewNoteChip />` (keep the `mr-1.5` spacing via a wrapper or a `className` prop — add `className?: string` to the props if needed).
  - `PloSynthesis.tsx`: before the per-flag chips, add `<ReviewNoteChip count={p.soft_flags.length} />`; the per-flag chips stay (they name the criterion).

- [ ] **Step 5: Verify**

Run (in `frontend/`): `npm run build && npm run lint` → both exit 0.
Run: `grep -rn "หลายตัวแทน\|ตัวแทนเดียว:\|'ตรวจ PLO'\|K · ความรู้" src`
Expected: no output.
Run: `grep -rn "chip chip-marker mr-1.5\">ข้อสังเกต" src`
Expected: no output.
Run: `grep -rln "ReviewNoteChip" src/pages`
Expected: `PloReport.tsx`, `PloReview.tsx`, `PloSynthesis.tsx` (any order).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/constants/stages.ts frontend/src/constants/stakeholder.ts frontend/src/components/ReviewNoteChip.tsx frontend/src/pages/Intake.tsx frontend/src/pages/StakeholderNeeds.tsx frontend/src/pages/SkillExtraction.tsx frontend/src/pages/NeedAnalysis.tsx frontend/src/pages/PloSynthesis.tsx frontend/src/pages/PloReview.tsx frontend/src/pages/PloReport.tsx
git commit -m "feat(ui): English technical labels, Thai page titles, one review-note chip"
```

---

### Task 3: Routes and the landing page

**Files:**
- Create: `frontend/src/pages/Landing.tsx`
- Modify: `frontend/src/App.tsx` (routes)
- Modify: every link to `/` that means "choose a program": `StageLayout.tsx:215,369`, `NeedAnalysis.tsx:284`, `Pipeline.tsx:408`, `PloReport.tsx:335`, `PloReview.tsx:196`, `PloSynthesis.tsx:330`, `SkillExtraction.tsx:193`, `StakeholderNeeds.tsx:300,351`, and `SingleRedirect.tsx` (its default target). `src/mock/MockPanel.tsx`'s `window.location.assign('/')` stays (it reloads the app).

**Interfaces:**
- Consumes: `CREATING_INTAKE` from `constants/intakeMode.ts`; classes from Task 1 (`btn btn-primary`, `btn-text`, `panel`, `eyebrow`).
- Produces: route `/` → `Landing`, route `/programs` → `Programs`; the landing page's steps section has `id="steps"`.

- [ ] **Step 1: Routes.** In `App.tsx` inside the `StageLayout` element route: `<Route index element={<Landing />} />` and `<Route path="programs" element={<Programs />} />`.

- [ ] **Step 2: Repoint links.** Every site listed above goes to `/programs` (`<Link to="/programs">`, `navigate('/programs')`). The three links labelled "ไปหน้า Intake" (NeedAnalysis, PloSynthesis, SkillExtraction) change their text to "เลือกหลักสูตร", since they open the program picker, not intake.

- [ ] **Step 3: `Landing.tsx`** — static, calls no API. Sections and exact copy from the spec's "Landing page" section and the mockup `look-v3.html` (hero with eyebrow "Curriculum Design Agent", headline "จากเสียงผู้มีส่วนได้ส่วนเสีย สู่ PLO ที่ตรวจสอบได้", lead, primary pill "เริ่มหลักสูตรใหม่" → `navigate('/intake', { state: CREATING_INTAKE })`, text link "ดูวิธีใช้ใน 4 ขั้น ›" → `#steps`, sample PLO card; `<section id="steps">` "ใช้งานใน 4 ขั้น" with four tiles Program / Evidence / Needs / PLO and the "คุณอนุมัติ" tag on Evidence, Needs, PLO; modes section Multi-agent / Single-agent; three trust points (100% traceability, SMART, HITL); closing `stamp-deep` band with "เริ่มหลักสูตรใหม่" and "หลักสูตรของฉัน" → `/programs`). Sample PLO card's KSEC chip reads "Skill". Tiles stack below 760 px. Sections break out of the layout's max-width container to full width (use a negative-margin/full-bleed wrapper or render Landing outside the container — Task 4 removes the container for `/`, so here a plain section is acceptable).

- [ ] **Step 4: Hash scroll.** In `Landing`, a `useEffect` on `useLocation().hash`: when it is `#steps`, `document.getElementById('steps')?.scrollIntoView({ behavior: 'smooth' })`.

- [ ] **Step 5: Verify**

Run (in `frontend/`): `npm run build && npm run lint` → exit 0.
Run: `grep -rnE "to=\"/\"|navigate\('/'\)" src --include=*.tsx`
Expected: no output.
Hash check: `npm run dev:mock`, open `http://localhost:5174/plo-synthesis`, then load `http://localhost:5174/#steps` → page shows the landing scrolled to "ใช้งานใน 4 ขั้น". At 360 px the four tiles are one column.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/Landing.tsx frontend/src/components/StageLayout.tsx frontend/src/components/SingleRedirect.tsx frontend/src/pages/NeedAnalysis.tsx frontend/src/pages/Pipeline.tsx frontend/src/pages/PloReport.tsx frontend/src/pages/PloReview.tsx frontend/src/pages/PloSynthesis.tsx frontend/src/pages/SkillExtraction.tsx frontend/src/pages/StakeholderNeeds.tsx
git commit -m "feat(ui): Apple-style landing page at /, program list at /programs"
```

---

### Task 4: Shell — top bar and stage bar replace the rail

**Files:**
- Create: `frontend/src/components/TopBar.tsx`
- Create: `frontend/src/components/StageBar.tsx`
- Modify: `frontend/src/components/StageLayout.tsx` (remove `StageRail`, `GateLegend`, `GateNote`, `RailLink`, `ProgramBar`; keep `RunningJobLine`, the program fetch, `creating`, `JobsProvider`)

**Interfaces:**
- Consumes: `stagesFor`, `stageIndex`, `AGENT_MODE_LABEL_TH`, `StageDef` (Task 2 labels); `CREATING_INTAKE`/`isCreatingIntake`; `ProgramRow` type already used in `StageLayout`; `SESSION_STATUS_LABELS` (already imported there).
- Produces:
  - `TopBar({ showPipeline, showCreate }: { showPipeline: boolean; showCreate: boolean }): JSX.Element`
  - `StageBar({ program, programId, creating, stages, reached, pathname }: { program: ProgramRow | null; programId: string | null; creating: boolean; stages: StageDef[]; reached: number; pathname: string }): JSX.Element`

- [ ] **Step 1: `TopBar`** — sticky top, height 48px, `background: rgb(251 251 253 / .8)` + `backdrop-filter: saturate(180%) blur(20px)`, 1px bottom hair, z above content. Left: text wordmark "Curriculum Design Agent" (`<Link to="/">`, weight 600, no logo). Right: "วิธีใช้" → `/#steps`; "หลักสูตรของฉัน" → `/programs`; "Pipeline" → `/pipeline` when `showPipeline`; `btn btn-primary btn-sm` "เริ่มหลักสูตรใหม่" → `navigate('/intake', { state: CREATING_INTAKE })` when `showCreate`. At 360 px the links may hide behind a compact layout but nothing may overflow horizontally (hide "วิธีใช้" text below 400 px if needed).

- [ ] **Step 2: `StageBar`** — sticky under the top bar (top 48px), translucent white, bottom hair. Left block: program name (`program?.name_th || program?.field || programId`; in creating mode the text "หลักสูตรใหม่") with a second line: faculty · `AGENT_MODE_LABEL_TH[mode]`; then the session status as `stamp`/`stamp stamp-mandate`/`stamp stamp-pending`/`chip chip-neutral`, same mapping as the old `ProgramBar`. In creating mode, keep the "หลักสูตรที่เลือกไว้: <id>" hint as a small line. With no `programId` and not creating: render only "ยังไม่ได้เลือกหลักสูตร" + `<Link to="/programs" className="link">เลือกจากรายการหลักสูตร</Link>`. Right block: one pill per stage (`NavLink` to `stage.route`), `overflow-x: auto` so it scrolls on narrow screens; pill states: current route = filled `graphite` with white text; index ≤ `reached` = navy dot before label; ahead = `pencil` text. A stage with `gateNote` shows a small navy check-circle mark after its label. `title` = `` `ขั้นที่ ${ordinal} · ${summary}${gateNote ? ' · ' + gateNote : ''}` ``.

- [ ] **Step 3: `StageLayout` composition.** `bare = pathname === '/' || pathname === '/programs'`. Render: `TopBar` (always; `showPipeline = !bare && program?.agent_mode !== 'single' && !!programId`, `showCreate = bare`); when `!bare`: `StageBar`, then `RunningJobLine` unless `creating`; then `<main>`: on `/` no padding/max-width wrapper (Landing is full-bleed); otherwise `px-4 py-8 sm:px-6 lg:px-10` and `mx-auto max-w-5xl` as today. Restyle `RunningJobLine` to a rounded `stamp-wash` strip inside the content width. `JobsProvider` still wraps everything below the top bar.

- [ ] **Step 4: Verify build** — `npm run build && npm run lint` → exit 0. `grep -n "StageRail\|GateLegend\|RailLink\|rail-width" src -r` → no output (also delete `--rail-width` from `index.css` if Task 1 kept it).

- [ ] **Step 5: Visual checks in mock mode** (`npm run dev:mock`, http://localhost:5174, use the MOCK panel to pick scenarios). Check, at 1280 px and at 360 px:
  - multi-agent program on `/need-analysis`: seven pills, Needs current, earlier stages dotted, Pipeline in top bar;
  - **single-agent check:** a single-agent program shows Program, Evidence, Needs, PLO, Report and no Pipeline link;
  - **creating check:** `/programs` → "เริ่มหลักสูตรใหม่" → `/intake` shows "หลักสูตรใหม่", nothing reached, no running-job line;
  - a page with a running job shows the running line; `/` and `/programs` show neither stage bar nor running line;
  - 360 px: top bar on one line, stage pills scroll sideways, no page-wide horizontal scroll.
  Report any check that could not be done in mock mode.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/TopBar.tsx frontend/src/components/StageBar.tsx frontend/src/components/StageLayout.tsx frontend/src/index.css
git commit -m "feat(ui): translucent top bar and horizontal stage bar replace the rail"
```

---

### Task 5: Docs and memory note

**Files:**
- Modify: `C:\Users\netic\.claude\projects\e--SideProject-Agent-Curriculum-Design\memory\frontend-visual-identity.md` and its line in `MEMORY.md` (controller does this, not a subagent)
- Modify: comment header of `frontend/src/index.css` if Task 1 left the old "paper/stamp desk" rationale (it must describe the new roles: navy = designer's act, gold = look at this, red = mandate)

- [ ] **Step 1:** Rewrite the memory note: identity of 2026-11-15 — Apple-style, UTCC colours without UTCC identity, token names kept with roles, fonts, top bar + stage bar, landing at `/`, programs at `/programs`, spec path.
- [ ] **Step 2:** Commit any repo file changed (`frontend/src/index.css` only), message `docs(ui): describe the new colour roles in index.css`.
