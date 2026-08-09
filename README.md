## API Endpoints

### Contest Creator Rights Request

Users without Contest Creator rights can request them here. Requests are auto-approved if the requester has 300+ global Wikimedia edits; otherwise a superadmin reviews them manually.

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/contest-requests` | Logged in | Submit a new request. Body: `{"reason": "..."}` (reason required only if edit count < 300) |
| `GET` | `/api/contest-requests` | Superadmin | List requests. Optional `?status=pending\|approved\|rejected` filter |
| `POST` | `/api/contest-requests/<id>/approve` | Superadmin | Approve a pending request — grants the requester `trusted_member` role |
| `POST` | `/api/contest-requests/<id>/reject` | Superadmin | Reject a pending request. Body: `{"rejection_reason": "..."}` (optional) |

**Example response** (`POST /api/contest-requests`):
```json
{
  "id": 1,
  "user_id": 3,
  "reason": null,
  "edit_count": 1091,
  "status": "approved",
  "reviewed_by": null,
  "reviewed_at": null,
  "rejection_reason": null,
  "created_at": "2026-08-03T10:12:00+00:00"
}
```
