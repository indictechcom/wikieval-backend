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
| GET | `/api/contests/<id>/child-requests` | user | Child-campaign requests for a group (all for its organizers; own otherwise) |
| POST | `/api/contests/<id>/child-requests` | user | Request a child campaign under a group |
| POST | `/api/contests/<id>/child-requests/<rid>/review` | group organizer | Approve / reject a child-campaign request |
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
`automated_settings`, `description`, and `project_link`.

**Scoring** — a contest is scored either by simple accept/reject marks
(`marks_setting_accepted` / `marks_setting_rejected`) or, when
`scoring_parameters.enabled` is true, by **points-per-parameter**. Each
parameter is allocated a maximum number of `points`; `max_score` is the sum of
those allocations. A jury awards each submission `0..points` per parameter, and
the final `score` is the sum of the awarded points:
```json
{
  "enabled": true,
  "max_score": 7,
  "parameters": [
    { "name": "Quality", "points": 5, "description": "..." },
    { "name": "Sources", "points": 2, "description": "..." }
  ]
}
```
The final score is computed by the client and sent as `score` on review (with
the per-parameter breakdown in `parameter_scores`, e.g. `{ "Quality": 4,
"Sources": 2 }`). For a points-based contest `marks_setting_accepted` equals
`max_score` and `marks_setting_rejected` is `0`.

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

## Campaign hierarchy (group / child / individual)

Every contest object carries `is_group` (bool), `parent_id` (int|null),
`parent_name` (string|null) and `child_count`. Pre-existing contests are
standalone *individual* campaigns (`is_group: false`, `parent_id: null`).

- A **group** campaign (`is_group: true`) is a parent: it takes **no
  submissions** (every submission endpoint returns `400`), and its
  `submission_count` is the sum over its children. Its own rules, scoring,
  jury and organizers serve as the defaults the client pre-fills when creating
  a child. A group is **`active` from creation** (listed, never locked; `/start`
  returns `409`), since it has no submission window of its own.
- A **child** campaign is an ordinary contest with `parent_id` set; it keeps
  its own details, submissions, reviews and leaderboard. **Organizers of the
  parent implicitly organize every child** (edit, start, see all submissions,
  add on behalf), so a child's organizer can't lock the group out;
  `effective_organizers` lists own + parent organizers, while `organizers` stays
  the child's own editable list.
- `children_start_date` / `children_end_date` on a group are the earliest child
  start and latest child end (`null` end if any child is open-ended), so the
  client can bucket a group by what its children are doing; the group's own
  dates are informational.
- The hierarchy is two levels: a parent must be a group, and a group can never
  be a child.
- Attach, detach and create-child actions are written to the review audit log
  (`hierarchy contest=… action=… actor=… parent=… previous_parent=…`).

## GET `/api/contests/<id>/children`

A group campaign's child campaigns, oldest first, each as a contest object
plus per-child aggregates. Public; draft (`pending`) children are shown only to
superadmins and organizers of the parent or of that child.

| Status | When | Body |
|--------|------|------|
| `200` | ok | `{ "children": [ { <contest object>, "submission_count", "accepted_count", "rejected_count", "pending_count", "participant_count" }, ... ] }` |
| `400` | not a group campaign | `{ "error": "Not a group campaign" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

## POST `/api/contests`

Create a contest. Requires login **and** `can_create_contest`.

**Request body** — `name`, `project_name`, and `start_date` are required; all
other contest fields are optional. Dates are ISO strings (`YYYY-MM-DD`).

Submission constraints live in the **`rules`** JSON object (enforced at submit
time): `min_byte_count`, `min_reference_count`, `min_word_count`, and
`allowed_submission_type` (`new` | `expansion` | `both`).
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
    "min_word_count": 300,
    "allowed_submission_type": "new"
  }
}
```

`min_reference_count` and `min_word_count` are checked against stats from
[XTools](https://xtools.wmcloud.org); if a contest sets one of these but the
stat can't be fetched (XTools unavailable), evaluation **fails** with a
try-again error rather than accepting an unverifiable article.

| Status | When | Body |
|--------|------|------|
| `201` | created (status `pending`) | contest object |
| `400` | missing `name`/`project_name`/`start_date`, or bad date | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | lacks contest-creation rights | `{ "error": "You do not have contest-creation rights" }` |

`is_group: true` creates a group campaign. `parent_id: <id>` creates a child
of that group campaign; this needs the caller to be an organizer of the parent
(else `403`), and such an organizer may create children **without** holding the
global contest-creation right. Both together is `400`.

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

`parent_id` attaches the contest to a group campaign (or `null` detaches it)
and stays editable after the contest has started. Attaching requires being an
organizer of **both** the contest and the target group (`403` otherwise).
Detaching requires an organizer of the **current parent** group (a child's own
organizer cannot leave a group on their own). `is_group` cannot be changed
after creation (ignored).

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

## Child-campaign requests

A local organizer asks, from a group campaign's page, for a child campaign
under it. The requester supplies only the child's **name**, its **local
organizers** (at least one) and optionally its **jury**; the project, dates,
timezone, eligibility rules and scoring are copied from the group on approval
(and the group's jury is used when the request names none). The group's
organizers (or a superadmin) review the request — the global contest-creation
right is not involved in asking, and no `/admin` queue is: each group has its
own list. There is no withdraw/cancel action on a pending request.

**Request object**

```json
{
  "id": 1,
  "parent_id": 7,
  "parent_name": "Wikipedia Asian Month",
  "user_id": 12,
  "username": "LocalOrg",
  "name": "Asian Month India",
  "organizers": ["LocalOrg", "Helper"],
  "jury_members": ["JurorA"],
  "status": "pending",
  "reviewed_by": null,
  "reviewer_username": null,
  "reviewed_at": null,
  "rejection_reason": null,
  "contest_id": null,
  "contest_name": null,
  "created_at": "2026-11-06T10:00:00+00:00"
}
```

`contest_id` / `contest_name` are set once the request is approved (the child
campaign that was created).

### GET `/api/contests/<id>/child-requests`

| Status | When | Body |
|--------|------|------|
| `200` | ok | `{ "requests": [ <request object>, ... ], "can_review": bool }` |
| `400` | not a group campaign | `{ "error": "Not a group campaign" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

Newest first. An organizer of the group (or a superadmin) gets every request
with `can_review: true`; any other logged-in user gets only their own requests
(so they can see whether each is pending, approved or rejected).

### POST `/api/contests/<id>/child-requests`

```json
{ "name": "Asian Month India", "organizers": ["LocalOrg"], "jury_members": ["JurorA"] }
```

| Status | When | Body |
|--------|------|------|
| `201` | created | the request object (`status: "pending"`) |
| `400` | not a group; missing name; no organizer; name clashes with an existing child or another pending request (case-insensitive) | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

Any logged-in user may ask; a rejected request may be re-submitted.

### POST `/api/contests/<id>/child-requests/<rid>/review`

```json
{ "decision": "approve", "organizers": ["LocalOrg", "Lead"], "jury_members": ["JurorB"] }
```

or

```json
{ "decision": "reject", "rejection_reason": "Please coordinate with the Nepal team first" }
```

`organizers` / `jury_members` are optional on approve: the reviewer may edit
either list before the child is created (an empty organizer list is refused).

| Status | When | Body |
|--------|------|------|
| `200` | reviewed | the updated request object |
| `400` | bad `decision`, missing `rejection_reason`, empty organizers, or already reviewed | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | not an organizer of the group (a child's own organizer or the requester doesn't count) | `{ "error": "<message>" }` |
| `404` | no such contest / request, or the request belongs to another group | `{ "error": "<message>" }` |

Approving:

- creates the child campaign (`parent_id` = the group) named as requested,
  with the group's `project_name`, `start_date`, `end_date`, `timezone`,
  `eligibility_rules`, `marks_setting_*`, `scoring_parameters` and
  `reviews_required`, the request's `organizers` and `jury_members` (group jury
  if none). The requester is the child's creator, so always one of its
  organizers. The child starts as a draft (`pending`) so its local organizers
  can adjust it (dates, rules, …) and then `/start` it; it is listed under
  `/children` to the group's and its own organizers right away, and publicly
  once started;
- sets the requester's `can_create_contest` to `true`;
- writes a `hierarchy … action=create-child` line to the audit log.

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
| `byte_count` | current article size in bytes (MediaWiki) |
| `word_count` | readable-prose word count (XTools) |
| `creator`, `creator_id` | first-revision author (page creator) |
| `created_at` | creation timestamp (ISO 8601) |
| `ref_new_count`, `ref_reused_count` | references — unique vs reused (XTools) |
| `image_count` | files embedded on the page (MediaWiki `prop=images`) |
| `outgoing_links`, `incoming_links` | mainspace links out / in — full counts (XTools) |

Stats marked *(XTools)* come from the [XTools](https://xtools.wmcloud.org) API;
if XTools is unavailable they may be `null` (see the eligibility note under
`/evaluate`). Everything else comes from the MediaWiki API.

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
- references (total = unique + reused) ≥ `rules.min_reference_count` (if set);
- readable-prose word count ≥ `rules.min_word_count` (if set);
- if `rules.allowed_submission_type` is **`new`**, the article must be created
  **on/after** the contest `start_date`;
- if it is **`expansion`**, the article must be created **before** the `start_date`.

If a contest sets `min_reference_count` or `min_word_count` but the corresponding
stat can't be fetched (XTools unavailable), evaluation returns a `400`
try-again error instead of accepting the article.

**One article, one participant** — an article can be in a contest only once:
- if **another participant** already submitted the link, evaluation fails with
  `400` ("…already been submitted to this contest by another participant…");
- if the **logged-in user** already submitted it, evaluation still succeeds and
  the response carries `existing_submission` (below) so the client can offer to
  keep the existing entry or refresh its stats (see step 2's `update` flag).

**Request body**
```json
{ "article_link": "https://hi.wikipedia.org/wiki/भारत" }
```

**Response** `200` — `article_metadata` holds all the fields listed above, and
`rules` echoes the contest's requirements so the UI can show the article's stats
against them (e.g. word count vs `min_word_count`).
```json
{
  "article_link": "https://hi.wikipedia.org/wiki/भारत",
  "article_metadata": {
    "article_title": "भारत", "page_id": 59, "revision_id": 1234567,
    "namespace": 0, "byte_count": 221658, "word_count": 8500,
    "creator": "SomeUser", "created_at": "2004-01-05T12:00:00Z",
    "ref_new_count": 110, "ref_reused_count": 40, "image_count": 30,
    "outgoing_links": 1200, "incoming_links": 9000
  },
  "hash": "<signed token carrying the metadata>",
  "rules": { "min_word_count": 300, "min_byte_count": 500, "min_reference_count": 3 },
  "existing_submission": {
    "id": 42, "status": "accepted", "score": 7, "already_reviewed": true,
    "reviewed_by_username": "SomeJuror", "reviewed_at": "2026-10-20T10:00:00+00:00",
    "submitted_at": "2026-10-18T09:00:00+00:00"
  }
}
```
`existing_submission` is present **only** when the logged-in user already
submitted this article to this contest.

| Status | When | Body |
|--------|------|------|
| `200` | evaluated | info + hash + rules (above) |
| `400` | empty link, contest not active, non-article namespace, ineligible for a `new`/`expansion` contest, or already submitted by another participant | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

## POST `/api/contests/<id>/submissions`

Step 2. Confirm the submission using the `hash` from `/evaluate`. Requires
login; the contest must be `active`.

**Request body**
```json
{ "hash": "<the hash returned by /evaluate>", "update": false }
```
The link and metadata are taken from the signed hash; any `article_metadata` in
the body is ignored. `update` (optional, default `false`) is for the case where
`/evaluate` returned `existing_submission`: with `update: true` the user's
existing submission of this article is **updated in place** — its article stats
are replaced by the fresh evaluation and any **jury review is removed** (status
back to `pending`, score 0, reviewer/comment/parameter scores cleared) so it is
reviewed again from scratch. The removal is written to the review audit log.

| Status | When | Body |
|--------|------|------|
| `201` | created (status `pending`) | submission object |
| `200` | `update: true` and the user's existing submission was refreshed | submission object |
| `400` | missing/invalid hash, hash for a different contest, contest not active, article already submitted by another participant, or own duplicate without `update` | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

An article can be submitted to a contest **once, by one participant only**.
This is enforced by the application on every new submission (not by a DB
constraint, so contests that already contained duplicates before this rule
are unaffected). The `hash` is a signed token (via the app `SECRET_KEY`);
tampering with it or its metadata is rejected.

## GET `/api/contests/<id>/submissions`

List a contest's submissions, newest first. Requires login. The contest
**creator**, its **jury members**, and **superadmins** see all submissions;
everyone else sees only their own. The response also includes the contest's
`rules`, so a jury can compare each submission's stats against the requirements.

| Status | When | Body |
|--------|------|------|
| `200` | ok | `{ "rules": { <contest rules> }, "submissions": [ <submission object>, ... ] }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `404` | no such contest | `{ "error": "Contest not found" }` |

## Multiple jury reviews per article

A contest's `reviews_required` (integer ≥ 1, default **1**) sets how many
jury reviews an article needs before its result is final. Every pre-existing
contest has 1, which keeps the original rule: the first review is final and only
its author may edit it.

With 2 or more, each jury member adds their own review (and may edit it later).
Until the required number is reached the submission stays `pending` with
`score` 0 (`already_reviewed: false`, `review_count` > 0). Once reached, the
**majority decision** wins; a **tie** keeps it pending for one more reviewer.
The final `score` is the **average** of the reviews that agree with the
decision (rounded to a whole number; `parameter_scores` are averaged per
parameter, to 2 decimals). Further jury members are blocked once the result
is final.

Submission objects carry `reviews` (one entry per jury member: `reviewer_id`,
`reviewer_username`, `decision`, `score`, `parameter_scores`,
`review_comment`, `reviewed_at`), `review_count` and `reviews_required`. The
aggregate fields (`status`, `score`, `parameter_scores`, `reviewed_by*`,
`reviewed_at`, `review_comment` = latest review's comment) are derived from
`reviews`.

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
| `400` | invalid `decision`, or the submission already has its required review(s) from other jury members | `{ "error": "<message>" }` |
| `401` | not logged in | `{ "error": "Login required" }` |
| `403` | not a jury member | `{ "error": "Only a contest jury member can review submissions" }` |
| `404` | no such submission | `{ "error": "Submission not found" }` |
