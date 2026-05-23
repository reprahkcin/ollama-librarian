# Ollama Tutor Mode: Product + Technical Architecture

## 1) Goal

Add a second app mode, "Ollama Tutor", that turns any user query or source dataset into:

- A structured lesson with clear concept progression
- A navigable glossary
- Embedded scored assessments
- Forward/backward concept navigation prompts
- Zoom controls for shallow/deep explanations
- A persistent knowledge map across sessions/topics

This mode should work with both freeform chat input and document-grounded input.

## 2) User Experience Definition

### 2.1 Entry

User selects Mode: `Chat` or `Tutor`.

In Tutor mode, user provides:

- Topic/query (required)
- Optional source context (uploaded docs / pasted text)
- Target depth: intro, intermediate, advanced
- Assessment style: end-only or throughout

### 2.2 Tutor Session Outputs

For each tutor session, system produces:

1. Lesson brief
2. Concept map (ordered graph)
3. Glossary (terms linked to concepts)
4. Lesson sections (chunked learning path)
5. Assessments (scored)
6. Next-step prompts (forward/backward/zoom)

### 2.3 In-session Controls

- `Next concept`
- `Previous concept`
- `Zoom in`
- `Zoom out`
- `Quiz now`
- `Show glossary`
- `Show map`

## 3) Pedagogical Framework (Generic, Topic-Agnostic)

Use a 6-stage learning pipeline for any topic:

1. Scope: define boundaries, assumptions, prerequisite level
2. Decompose: extract core concepts + dependencies
3. Sequence: produce topological order from prerequisites
4. Explain: provide concise explanation per concept with examples
5. Assess: ask objective + short-form questions and score
6. Adapt: route learner based on score and confidence

### 3.1 Concept Object

Each concept should carry:

- `concept_id`
- `title`
- `summary`
- `prerequisites[]`
- `difficulty` (1-5)
- `glossary_terms[]`
- `learning_objective`
- `explanation_layers` (L1/L2/L3)
- `checkpoints[]` (assessment item ids)

### 3.2 Explanation Layers (Zoom)

For each concept, generate 3 depth layers:

- L1: 3-5 sentence plain-language overview
- L2: structured explanation + one concrete example
- L3: deeper mechanics, edge cases, tradeoffs

`Zoom out` moves L3 -> L2 -> L1 and compresses detail.
`Zoom in` moves L1 -> L2 -> L3 and expands detail.

## 4) Assessment Model

### 4.1 Assessment Types

Per concept, include:

- 1 recall check (definition/fact)
- 1 comprehension check (explain in own words)
- 1 transfer check (apply to new scenario)

### 4.2 Scoring

Each item returns:

- `score` (0-100)
- `rubric_tags[]` (correctness, completeness, precision)
- `feedback`
- `recommended_action` (advance, review, remediate)

Concept mastery score:

`mastery = 0.3 * recall + 0.3 * comprehension + 0.4 * transfer`

Routing rules:

- `>= 80`: unlock next concept
- `60-79`: allow next + recommend optional review
- `< 60`: trigger remediation micro-lesson + retest

### 4.3 Placement

Support both:

- End-only assessment (final cumulative quiz)
- Interleaved assessment (after each concept or every N concepts)

## 5) Navigation Prompt Engine

For each concept C_i, prebuild actionable prompts:

- Forward: "Advance to next concept" (targets C_i+1)
- Backward: "Review previous concept" (targets C_i-1)
- Zoom in: "Explain this concept in more depth"
- Zoom out: "Summarize this concept at a high level"
- Bridge: "Show how this relates to [neighbor concept]"

Store these as structured actions, not just text, so UI buttons can call deterministic endpoints.

## 6) Persistent Knowledge Map

## 6.1 Purpose

Maintain learner progress across all topics with visible strengths/gaps.

## 6.2 Data Structure

Graph model:

- Node: concept/topic
- Edge: prerequisite/related-to/applied-by

Per-user per-node metrics:

- `attempt_count`
- `mastery_score_latest`
- `mastery_score_trend`
- `last_seen_at`
- `confidence_self_reported`

### 6.3 Visualization

Minimum viable visualization:

- Node color by mastery bucket (red/yellow/green)
- Node size by exposure count
- Edge arrows for prerequisites
- Filter by topic family/date range

## 7) Integration with Current App

Current app already has:

- Chat + Ollama call path
- JSON persistence patterns (history/stash/update state)
- PDF grounding/indexing flow

Tutor mode should reuse this architecture and add a separate tutor state store.

## 8) Proposed API Surface (MVP)

- `POST /api/tutor/session/start`
  - input: topic, level, assessment_mode, source_mode
  - output: tutor_session_id + initial lesson graph

- `GET /api/tutor/session/{id}`
  - output: session state, current concept, mastery summary

- `POST /api/tutor/session/{id}/navigate`
  - input: action (`next|prev|zoom_in|zoom_out|show_map|show_glossary`)
  - output: rendered concept payload

- `POST /api/tutor/session/{id}/assess`
  - input: concept_id, answers
  - output: scoring + routing decision

- `GET /api/tutor/session/{id}/glossary`
  - output: terms linked to concepts

- `GET /api/tutor/map`
  - output: persistent knowledge graph for user

## 9) Storage Plan

Add SQLite tables (or JSON first, SQLite preferred):

- `tutor_sessions`
- `tutor_concepts`
- `tutor_glossary_terms`
- `tutor_assessments`
- `tutor_attempts`
- `tutor_knowledge_nodes`
- `tutor_knowledge_edges`

Keep `session_id` and timestamps on all rows.

## 10) Prompt Contracts for Deterministic Outputs

Use strict JSON contracts for model generation:

1. Lesson planner prompt -> returns concept graph JSON
2. Concept explainer prompt -> returns L1/L2/L3 layers
3. Quiz generator prompt -> returns item set + answer key/rubric
4. Grader prompt -> returns score + feedback + recommendation

Reject/regenerate responses that are not valid JSON.

## 11) MVP Delivery Plan

Phase 1 (Core Tutor):

- Tutor mode toggle
- Session start from query
- Concept sequencing + glossary
- Next/prev/zoom controls

Phase 2 (Assessment):

- Interleaved and end-only quiz modes
- Scoring + routing rules
- Concept mastery summary card

Phase 3 (Persistent Map):

- Knowledge graph persistence
- Mastery visualization panel
- Trend over time

Phase 4 (Refinement):

- Better remediation lessons
- Difficulty adaptation
- Topic transfer recommendations

## 12) Acceptance Criteria

- Any valid topic prompt yields a structured lesson graph.
- User can navigate forward/backward without losing context.
- User can zoom explanation depth at any concept.
- At least one scored assessment is available per concept.
- Mastery and feedback are persisted and visible across sessions.
- Glossary terms are clickable and linked to concept nodes.

## 13) Risks and Mitigations

Risk: Hallucinated concept dependencies
Mitigation: require evidence snippets from source context when available.

Risk: Unstable JSON outputs
Mitigation: strict schema validation + retry with repair prompt.

Risk: Assessment grading drift
Mitigation: fixed rubric tags and deterministic grading template.

Risk: Overly long lessons
Mitigation: cap concept count (for example 5-9 per session) and allow expansion.

## 14) Immediate Next Build Tasks

1. Add Tutor mode UI toggle and session state container.
2. Implement lesson planner JSON schema + endpoint.
3. Render concept panel + glossary panel + navigation controls.
4. Implement assessment item generation/scoring endpoint.
5. Persist results to SQLite and expose map endpoint.
