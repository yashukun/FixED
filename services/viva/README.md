# Viva Service Deep-Dive

This document explains exactly how the Viva (oral interview/exam) feature works in the current FixED implementation.

## 1) What This Service Does

`services/viva/main.py` implements an end-to-end oral viva flow:

- Starts a viva session for a selected book/topic/chapter
- Generates viva questions (initial + follow-up)
- Evaluates answers and computes per-question scores
- Monitors camera frames for proctoring (presence + identity match)
- Applies warning policy (3 warnings, terminate on 4th)
- Finalizes and stores a complete results/audit record
- Exposes history and audit endpoints for evaluator review

## 2) High-Level Architecture

### Runtime components

- **API layer**: FastAPI routes in `services/viva/main.py`
- **Prompting layer**: `services/viva/prompting.py`
- **Providers**:
  - Voice/STT/TTS: `services/viva/providers/voice.py`
  - Face/proctor check: `services/viva/providers/face.py`
- **Persistence**: shared SQLAlchemy models in `services/shared/db/models.py`
- **Cost tracking**: shared `record_cost()` from `services/shared/cost.py`

### Related frontend pieces

- Viva UI page: `frontend/src/pages/VivaPage.jsx`
- Viva API client calls: `frontend/src/services/api.js`
- Proxy routing:
  - dev: `frontend/vite.config.js`
  - docker nginx: `frontend/nginx.conf`

## 3) Session Lifecycle

### Status enum

`VivaSessionStatus` values:

- `pending`
- `active`
- `completed`
- `terminated_proctoring`
- `terminated_timeout`

### Typical lifecycle

1. `POST /viva/sessions/start`
2. `POST /viva/sessions/{id}/reference-photo`
3. Repeated:
   - `POST /viva/sessions/{id}/proctor/frame`
   - `POST /viva/sessions/{id}/answer`
4. End via:
   - auto-complete on final question
   - manual finish: `POST /viva/sessions/{id}/finish`
   - terminate by proctor policy
   - terminate by timeout
5. Retrieve outcome:
   - `GET /viva/sessions/{id}/results`

## 4) Detailed Flow

## 4.1 Start Session

Endpoint: `POST /viva/sessions/start`

Input:

- `file_id`
- `topic`
- optional `chapter_number`
- `question_count` in `[5..10]`
- `per_question_limit_seconds` (minimum 20)
- optional `session_limit_seconds` (defaults to `question_count * per_question_limit_seconds`)

Behavior:

- Validates limits
- Generates a full base question bank using LLM (`_generate_question_bank_with_llm`)
- Creates:
  - `VivaSession` row (status `active`)
  - all `VivaQuestion` rows upfront (order 1..N)
  - proctor event `session_start`
- Returns session summary + first question (+ optional TTS audio)

## 4.2 Reference Enrollment

Endpoint: `POST /viva/sessions/{id}/reference-photo`

Behavior:

- Stores `reference_photo_b64` in session
- Uploads reference image to object storage and stores path metadata
- Adds proctor event `reference_photo`

## 4.3 Proctor Frame Check

Endpoint: `POST /viva/sessions/{id}/proctor/frame`

Behavior:

- Runs `verify_face(reference_photo_b64, frame_b64, threshold)` using OpenAI vision model inference
- Determines:
  - `is_present`
  - `is_match`
  - confidence score
- If failed:
  - evaluate anomaly in rolling window and cooldown
  - increment warning count only when buffered policy threshold is reached
  - terminate on strike 4
- Saves `VivaProctorEvent` with:
  - reason
  - frame object path (`details.frame_object_path`) for audit review
- On termination: finalizes session and returns terminated payload

## 4.4 Answer Submission

Endpoint: `POST /viva/sessions/{id}/answer`

Input:

- `transcript` or `audio_b64`
- optional `latency_ms`

Behavior:

- Enforces session and question timeout checks
- Uses STT if transcript not provided and audio is present
- Evaluates answer against expected points (`_evaluate_answer`)
- Writes `VivaTurn`
- If last question:
  - marks complete
  - finalizes result
- Else:
  - rewrites next pre-generated base question into an answer-driven follow-up for at least 60% of transitions
  - returns next question

## 4.5 Finish Session

Endpoint: `POST /viva/sessions/{id}/finish`

Behavior:

- Adds `manual_finish` proctor event
- Finalizes result (`_finalize_session_with_db`)

## 4.6 Results

Endpoint: `GET /viva/sessions/{id}/results`

Behavior:

- Returns stored `VivaResult` + session summary + proctor events
- If result missing but session ended, computes and returns finalized payload

## 4.7 History + Audit

### History

Endpoint: `GET /viva/history/sessions`

Query:

- optional `file_id`
- optional `status`
- pagination: `limit`, `offset`

Returns compact items:

- session summary
- metrics:
  - overall/max score
  - turn count
  - proctor event count

### Full audit

Endpoint: `GET /viva/sessions/{id}/audit`

Returns:

- session summary
- reference photo
- full questions array
- full turns array
- full proctor event timeline (including stored frame snapshots)
- result object

## 5) Persistence Model

Core DB tables:

- `viva_sessions`
  - configuration, status, warning count, timing, reference photo
- `viva_questions`
  - question order, text, expected points
- `viva_turns`
  - transcript/audio, score, feedback, latency
- `viva_proctor_events`
  - event type, presence/match, confidence, warning/action, details
- `viva_results`
  - overall score, strengths, weak areas, recommendations, per-question breakdown

Migration artifact:

- `services/shared/db/migrations/001_viva_tables.sql`

## 6) Proctoring Policy (Current)

- Frame checks are periodic from frontend during live session
- Violation criteria:
  - user absent
  - face mismatch
  - ambiguous/proctoring error signal (configurable, defaults to violation)
- Warning escalation:
  - warning #1, #2, #3 => continue with warning
  - warning #4 => terminate (`terminated_proctoring`)
- Events are saved for post-evaluation review

## 7) Frontend Behavior

`frontend/src/pages/VivaPage.jsx` handles:

- pre-session setup and guards
- camera+mic permission + reference capture
- question rendering + TTS repeat
- speech recognition (browser API) + typed fallback
- proctor check loop and warnings UI
- results rendering
- history list and audit viewer

## 8) Cost Tracking

LLM usage is tracked per phase:

- question generation
- answer evaluation
- final summary
- STT events (if used)

Cost records are written through shared `api_cost_events`.

## 9) Important Config

From `services/viva/config.py`:

- `VIVA_CHAT_MODEL`
- `VIVA_STT_MODEL`
- `VIVA_TTS_MODEL`
- `VIVA_VISION_MODEL`
- `VIVA_DEFAULT_QUESTION_COUNT`
- `VIVA_DEFAULT_PER_QUESTION_LIMIT_SECONDS`
- `VIVA_FACE_MATCH_THRESHOLD`
- `VIVA_PROCTOR_AMBIGUOUS_CONFIDENCE_MIN`
- `VIVA_PROCTOR_VIOLATE_ON_AMBIGUOUS`
- `VIVA_PROCTOR_MIN_FRAME_INTERVAL_MS` (throttles rapid frame checks to reduce vision API spend)
- `VIVA_FOLLOWUP_MIN_RATIO`
- `VIVA_PROCTOR_WINDOW_SIZE`
- `VIVA_PROCTOR_WINDOW_ANOMALY_THRESHOLD`
- `VIVA_PROCTOR_WARNING_MIN_INTERVAL_MS`
- `VIVA_MEDIA_BUCKET`
- `VIVA_STORE_ALL_FRAMES`
- `VIVA_PROCTOR_ACCESSORY_IS_VIOLATION`
- `VIVA_PROCTOR_MIN_ANSWERED_QUESTIONS_FOR_WARNING`

Also uses common:

- `OPENAI_API_KEY`
- vector db environment values (if expanded later)

## 10) Known Limitations (Current)

- Face verification depends on a generic vision model response; it is stronger than heuristics but still not equivalent to a dedicated biometric identity stack
- Proctor event payloads are metadata-first; frame evidence is stored in object storage
- No auth/authorization layer on Viva APIs yet

## 11) Recommended Production Hardening

- Add signed URL generation for evaluator-safe object preview
- Add authenticated evaluator roles for history/audit endpoints
- Add retention policy + redaction controls for biometric artifacts
- Add robust anti-spoof checks and liveness detection
- Add pagination/filter/search and export for evaluator workflows
