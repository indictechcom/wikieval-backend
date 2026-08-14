# API Reference

Backend HTTP API for WikiEval.

- All request/response bodies are JSON.
- Authentication is via MediaWiki OAuth (flask-mwoauth). Logging in stores an
  OAuth token in the session cookie; on the first authenticated request the
  user is lazily persisted and their id cached in the session. Send the session
  cookie with requests (browsers do this automatically; for CORS the frontend
  must use credentialed requests).

## Endpoints at a glance

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/login` · `/oauth-callback` · `/logout` | — | OAuth handshake / logout |
| GET | `/api/user` | — | Current auth state |
| GET | `/api/contest-creation-request` | user | My contest-creation-rights status |
| POST | `/api/contest-creation-request` | user | Request contest-creation rights |
| GET | `/api/contest-creation-requests` | superadmin | Review queue (all requests) |
| POST | `/api/contest-creation-request/<id>/review` | superadmin | Approve / reject a request |
| GET | `/api/contests` | — | List contests (active; own pending; all for superadmin) |
| GET | `/api/contests/<id>` | — | Contest detail |
| GET | `/api/contests/<id>/leaderboard` | user | Per-participant leaderboard |
| POST | `/api/contests` | user + `can_create_contest` | Create a contest |
| PUT | `/api/contests/<id>` | organizer | Edit (all fields while pending; organizers/jury only once active) |
| POST | `/api/contests/<id>/start` | organizer | Start a contest (locks it) |
| POST | `/api/contests/<id>/submissions/evaluate` | user | Evaluate an article → info + hash |
| POST | `/api/contests/<id>/submissions` | user | Submit using the hash |
| GET | `/api/contests/<id>/submissions` | user | List submissions (own; all for creator/jury/superadmin) |
| POST | `/api/submissions/<id>/review` | jury | Accept / reject a submission |
| GET | `/` · `/index` | — | Serves the frontend (`index.html`) |

## Authentication (flask-mwoauth)

These are provided by the OAuth blueprint, not the app itself:

| Method | Path              | Description                                             |
| ------ | ----------------- | ------------------------------------------------------- |
| GET    | `/login`          | Start the OAuth handshake; redirects to MediaWiki.      |
| GET    | `/oauth-callback` | OAuth callback; stores the access token in the session. |
| GET    | `/logout`         | Clear the session token.                                |

---

## GET `/api/user`

Report the current authentication state. Does not require login.

**Response** `200`

```json
{
  "logged": true,
  "username": "Jayprakash12345",
  "is_superadmin": true,
  "can_create_contest": false
}
```

When not logged in: `{ "logged": false, "username": null, "is_superadmin": false, "can_create_contest": false }`.

---

## GET `/api/contest-creation-request`

Return the logged-in user's contest-creation rights status — their latest
request (or `null` if they never submitted one) and whether they currently hold
rights. This is what a returning user's UI reads to show their status.
Requires login.

**Responses**
| Status | When | Body |
|--------|------|------|
| `200` | ok | status object (see below) |
| `401` | not logged in | `{ "error": "Login required" }` |

**Status object**
```json
{
  "can_create_contest": false,
  "request": {
    "id": 1,
    "user_id": 1,
    "username": "Alice",
    "reason": "I organize monthly edit-a-thons",
    "status": "pending",
    "reviewed_by": null,
    "reviewed_at": null,
    "rejection_reason": null,
    "created_at": "2026-08-13T12:00:00+00:00"
  }
}
```
When the user has never submitted a request: `{ "can_create_contest": false, "request": null }`.

---

## POST `/api/contest-creation-request`

Submit a request for contest-creation rights. Requires login.

**Request body**

```json
{ "reason": "I organize monthly edit-a-thons" }
```

**Responses**
| Status | When | Body |
|--------|------|------|
| `201` | created | the request object (see below) |
| `400` | missing/empty `reason`, already have a pending request, or already have rights | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |

**Response body** `201` — the created contest-creation _request resource_. This
same object shape is also returned by the status (GET), review, and list
endpoints.

```json
{
  "id": 1,
  "user_id": 1,
  "username": "Alice",
  "reason": "I organize monthly edit-a-thons",
  "status": "pending",
  "reviewed_by": null,
  "reviewed_at": null,
  "rejection_reason": null,
  "created_at": "2026-08-13T12:00:00+00:00"
}
```

`status` is one of `pending`, `approved`, `rejected`.

---

## GET `/api/contest-creation-requests`

List all contest-creation requests — the superadmin review queue.
**Superadmin only.** Newest first.

**Responses**
| Status | When | Body |
|--------|------|------|
| `200` | ok | `{ "requests": [ <request object>, ... ] }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | logged in but not a superadmin | `{ "error": "Superadmin rights required" }` |

**Example**
```json
{
  "requests": [
    {
      "id": 2,
      "user_id": 3,
      "username": "Bob",
      "reason": "Running a photo contest",
      "status": "pending",
      "reviewed_by": null,
      "reviewed_at": null,
      "rejection_reason": null,
      "created_at": "2026-08-13T13:00:00+00:00"
    }
  ]
}
```

---

## POST `/api/contest-creation-request/<id>/review`

Record a review decision on a pending request. **Superadmin only.**
Approving sets the requester's `can_create_contest` flag to `true` (the actual
grant of rights); rejecting leaves it unchanged.

**Request body**

```json
{ "decision": "approve" }
```

or

```json
{ "decision": "reject", "rejection_reason": "Insufficient recent activity" }
```

**Responses**
| Status | When | Body |
|--------|------|------|
| `200` | reviewed | the updated request object |
| `400` | `decision` not `approve`/`reject`, missing `rejection_reason` on reject, request not found, or already reviewed | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | logged in but not a superadmin | `{ "error": "Superadmin rights required" }` |

**Example** — approved response

```json
{
  "id": 1,
  "user_id": 1,
  "username": "Alice",
  "reason": "I organize monthly edit-a-thons",
  "status": "approved",
  "reviewed_by": 2,
  "reviewed_at": "2026-08-13T12:30:00+00:00",
  "rejection_reason": null,
  "created_at": "2026-08-13T12:00:00+00:00"
}
```

### Notes

- Superadmins are hard-coded in `auth.py` (`SUPERADMINS`); they are the bootstrap
  reviewers who grant contest-creation rights to others.
- The granted right is recorded on the user as `can_create_contest` (boolean),
  exposed in `User.to_dict()`.

---

# Contests

A contest is created by a user who holds contest-creation rights. It starts in
`pending` status (fully editable). When an organizer **starts** it, it becomes
`active` and its configuration is **locked** — after that only the `organizers`
and `jury_members` lists may still be edited.

The contest object (returned by all endpoints below) includes all contest
fields plus `status` (`pending` | `active`), `created_by`, `creator_username`,
and a computed `submission_count`. Notable fields: `organizers` and
`jury_members` (arrays of usernames; the creator is always an organizer),
`marks_setting_accepted` (> 0) and `marks_setting_rejected` (≤ 0), the `rules`
object, `scoring_parameters` (optional multi-parameter scoring config),
`automated_settings`, `description`, and `outreach_dashboard_url`.

**Scoring** — a contest is scored either by simple accept/reject marks
(`marks_setting_accepted` / `marks_setting_rejected`) or, when
`scoring_parameters.enabled` is true, by weighted parameters:
```json
{
  "enabled": true,
  "max_score": 100,
  "min_score": 0,
  "parameters": [
    { "name": "Quality", "weight": 40, "description": "..." },
    { "name": "Sources", "weight": 30, "description": "..." }
  ]
}
```
The weighted final score is computed by the client and sent as `score` on
review (with the per-parameter breakdown in `parameter_scores`).

## GET `/api/contests`

List contests, newest first. Visibility:
- **everyone** sees `active` contests;
- a **logged-in user** also sees their **own** `pending` contests;
- **superadmins** see all contests (every `pending` too).

**Response** `200` — `{ "contests": [ <contest object>, ... ] }`

## GET `/api/contests/<id>`

Public. Fetch a single contest.

| Status | When |
|--------|------|
| `200` | contest object |
| `404` | no such contest |

## GET `/api/contests/<id>/leaderboard`

Per-participant aggregates for a contest, **ordered alphabetically by
username**. Requires login. One row per user who submitted.

**Response** `200`
```json
{
  "leaderboard": [
    {
      "user_id": 12,
      "username": "Alice",
      "total_submissions": 8,
      "total_marks": 46,
      "reviewed_count": 6,
      "pending_count": 2
    }
  ]
}
```
| Status | When | Body |
|--------|------|------|
| `200` | ok | `{ "leaderboard": [ ... ] }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

## POST `/api/contests`

Create a contest. Requires login **and** `can_create_contest`.

**Request body** — `name`, `project_name`, and `start_date` are required; all
other contest fields are optional. Dates are ISO strings (`YYYY-MM-DD`).

Submission constraints live in the **`rules`** JSON object (enforced at submit
time): `min_byte_count`, `min_reference_count`, and `allowed_submission_type`
(`new` | `expansion` | `both`).
```json
{
  "name": "Photo Contest",
  "project_name": "commons",
  "start_date": "2026-09-01",
  "end_date": "2026-09-30",
  "jury_members": ["Alice", "Bob"],
  "marks_setting_accepted": 10,
  "rules": {
    "min_byte_count": 500,
    "min_reference_count": 3,
    "allowed_submission_type": "new"
  }
}
```

| Status | When | Body |
|--------|------|------|
| `201` | created (status `pending`) | contest object |
| `400` | missing `name`/`project_name`/`start_date`, or bad date | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | lacks contest-creation rights | `{ "error": "You do not have contest-creation rights" }` |

## PUT `/api/contests/<id>`

Edit a contest. **Organizers only** (the creator is always an organizer). While
`pending`, any field may be edited. Once `active`, the config is locked and only
`organizers` / `jury_members` may change — any other field returns `409`. Send
any subset of the contest fields.

| Status | When | Body |
|--------|------|------|
| `200` | updated | contest object |
| `400` | invalid field value (e.g. empty name, bad date, bad marks) | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | not an organizer | `{ "error": "Only a contest organizer can edit it" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |
| `409` | active contest, non-editable field | `{ "error": "Contest is locked; only organizers and jury members can be edited" }` |

## POST `/api/contests/<id>/start`

Start a contest: transitions `pending` → `active` and locks editing.
**Organizers only.**

| Status | When | Body |
|--------|------|------|
| `200` | started (status `active`) | contest object |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | not an organizer | `{ "error": "Only a contest organizer can start it" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |
| `409` | already started | `{ "error": "Contest has already been started" }` |

---

# Submissions

A participant submits an article link to an **active** contest. A **jury member**
(see the review endpoint) accepts/rejects each submission, which sets its
`status` and `score`. Article links are decoded on write, so an
international/percent-encoded link is stored in compact Unicode form.

The submission object includes `id`, `user_id`, `username`, `contest_id`,
`article_link`, `article_metadata`, `status` (`pending`|`accepted`|`rejected`),
`score`, `parameter_scores`, `review_comment`, `reviewed_by`, `reviewed_at`,
`already_reviewed`, and `submitted_at`.

`article_metadata` is the server-computed article info (from MediaWiki), stored
verbatim from the evaluation step:

| Field | Meaning |
|-------|---------|
| `article_title`, `display_title` | canonical / display title |
| `article_url` | full article URL |
| `page_id` | MediaWiki page id |
| `revision_id` | latest revision id — pins the evaluated version |
| `namespace` | namespace id (always `0` = main/article space) |
| `byte_count` | current article size in bytes |
| `creator`, `creator_id` | first-revision author (page creator) |
| `created_at` | creation timestamp (ISO 8601) |
| `ref_new_count`, `ref_reused_count` | `<ref>` counts — new vs reused |
| `image_count` | images used (localized File-namespace aware) |
| `outgoing_links`, `incoming_links` | mainspace links out / in (each capped at 500) |

Submitting is a **two-step, tamper-proof flow**:

1. **Evaluate** — send the article link; the backend processes it (MediaWiki)
   and returns the computed metadata plus a signed `hash`.
2. **Confirm** — the client reviews the info and submits using **only the
   `hash`**. The backend reads the trusted metadata out of the signed hash, so
   the stored submission cannot be tampered with by the client.

## POST `/api/contests/<id>/submissions/evaluate`

Step 1. Process an article link and return its info + a signed `hash`. Nothing
is stored yet. Requires login; the contest must be `active`.

**Eligibility** — checked here (from the contest's `rules`), so an ineligible
article never yields a hash:
- must be a **main-namespace (article)** page — `Talk:`, `User:`, `Category:`, … are rejected;
- article size ≥ `rules.min_byte_count` (if set);
- references (new + reused) ≥ `rules.min_reference_count` (if set);
- if `rules.allowed_submission_type` is **`new`**, the article must be created
  **on/after** the contest `start_date`;
- if it is **`expansion`**, the article must be created **before** the `start_date`.

**Request body**
```json
{ "article_link": "https://hi.wikipedia.org/wiki/भारत" }
```

**Response** `200` — `article_metadata` holds all the fields listed above.
```json
{
  "article_link": "https://hi.wikipedia.org/wiki/भारत",
  "article_metadata": {
    "article_title": "भारत", "page_id": 59, "revision_id": 1234567,
    "namespace": 0, "byte_count": 221658,
    "creator": "SomeUser", "created_at": "2004-01-05T12:00:00Z",
    "ref_new_count": 110, "ref_reused_count": 40, "image_count": 30,
    "outgoing_links": 500, "incoming_links": 500
  },
  "hash": "<signed token carrying the metadata>"
}
```
| Status | When | Body |
|--------|------|------|
| `200` | evaluated | info + hash (above) |
| `400` | empty link, contest not active, non-article namespace, or ineligible for a `new`/`expansion` contest | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

## POST `/api/contests/<id>/submissions`

Step 2. Confirm the submission using the `hash` from `/evaluate`. Requires
login; the contest must be `active`.

**Request body**
```json
{ "hash": "<the hash returned by /evaluate>" }
```
The link and metadata are taken from the signed hash; any `article_metadata` in
the body is ignored.

| Status | When | Body |
|--------|------|------|
| `201` | created (status `pending`) | submission object |
| `400` | missing/invalid hash, hash for a different contest, contest not active, or duplicate article | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

A user cannot submit the same article to the same contest twice. The `hash` is a
signed token (via the app `SECRET_KEY`); tampering with it or its metadata is
rejected.

## GET `/api/contests/<id>/submissions`

List a contest's submissions, newest first. Requires login. The contest
**creator**, its **jury members**, and **superadmins** see all submissions;
everyone else sees only their own.

| Status | When | Body |
|--------|------|------|
| `200` | ok | `{ "submissions": [ <submission object>, ... ] }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

## POST `/api/submissions/<id>/review`

Accept or reject a submission. **Jury members only** — the users listed in the
contest's `jury_members`. The contest creator and superadmins **cannot** review
(unless they are also listed as jury).

**Request body**
```json
{ "decision": "accept", "score": 7, "review_comment": "..." }
```
- `decision` — `accept` or `reject` (required).
- `score` — optional on accept; defaults to the contest's accepted marks.
  Reject uses the contest's rejected marks.
- `review_comment`, `parameter_scores` — optional.

| Status | When | Body |
|--------|------|------|
| `200` | reviewed | submission object |
| `400` | invalid `decision`, or already reviewed | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | not a jury member | `{ "error": "Only a contest jury member can review submissions" }` |
| `404` | no such submission | `{ "error": "Submission not found" }` |
