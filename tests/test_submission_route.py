"""Tests for the submission routes (evaluate / submit / list / review)."""

from model import User
from services.contest import create_contest, start_contest
from services.submission import create_submission, evaluate_article

ARTICLE = "https://en.wikipedia.org/wiki/Cat"


def make_user(db, username, can_create=False):
    user = User(username=username, can_create_contest=can_create)
    db.session.add(user)
    db.session.commit()
    return user


def active_contest(db, creator_name="Creator", **fields):
    creator = make_user(db, creator_name, can_create=True)
    fields.setdefault("start_date", "2026-01-01")
    fields.setdefault("marks_setting_accepted", 10)
    contest = create_contest(creator.id, "C", "commons", **fields)
    start_contest(contest)
    return creator, contest


def _submit(contest, user, link=ARTICLE):
    """Create a submission via the service (evaluate + create), for setup."""
    ev = evaluate_article(contest, link)
    return create_submission(user.id, contest, ev["hash"])


def _evaluate(client, contest_id, link=ARTICLE):
    resp = client.post(
        f"/api/contests/{contest_id}/submissions/evaluate", json={"article_link": link}
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["hash"]


# --- evaluate ---

def test_evaluate_requires_login(client, db):
    _creator, contest = active_contest(db)
    resp = client.post(f"/api/contests/{contest.id}/submissions/evaluate",
                       json={"article_link": ARTICLE})
    assert resp.status_code == 401


def test_evaluate_returns_info_and_hash(client, db, login_as):
    _creator, contest = active_contest(db)
    make_user(db, "Alice")
    login_as(client, "Alice")

    resp = client.post(f"/api/contests/{contest.id}/submissions/evaluate",
                       json={"article_link": ARTICLE})
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["hash"]
    assert body["article_metadata"]["article_title"] == "Cat"


def test_evaluate_rejects_pending_contest(client, db, login_as):
    creator = make_user(db, "Creator", can_create=True)
    contest = create_contest(creator.id, "C", "commons", start_date="2026-01-01",
                             marks_setting_accepted=10)   # not started
    make_user(db, "Alice")
    login_as(client, "Alice")

    resp = client.post(f"/api/contests/{contest.id}/submissions/evaluate",
                       json={"article_link": ARTICLE})

    assert resp.status_code == 400


# --- submit (confirm with hash only) ---

def test_submit_requires_login(client, db):
    _creator, contest = active_contest(db)
    resp = client.post(f"/api/contests/{contest.id}/submissions", json={"hash": "x"})
    assert resp.status_code == 401


def test_participant_can_submit(client, db, login_as):
    _creator, contest = active_contest(db)
    make_user(db, "Alice")
    login_as(client, "Alice")

    h = _evaluate(client, contest.id)
    resp = client.post(f"/api/contests/{contest.id}/submissions", json={"hash": h})
    body = resp.get_json()

    assert resp.status_code == 201
    assert body["status"] == "pending"
    assert body["username"] == "Alice"
    assert body["article_link"] == ARTICLE
    assert body["article_metadata"]["article_title"] == "Cat"


def test_submit_requires_prior_evaluation(client, db, login_as):
    _creator, contest = active_contest(db)
    make_user(db, "Alice")
    login_as(client, "Alice")

    resp = client.post(f"/api/contests/{contest.id}/submissions", json={"hash": "deadbeef"})

    assert resp.status_code == 400


def test_submit_to_missing_contest_404(client, db, login_as):
    make_user(db, "Alice")
    login_as(client, "Alice")

    resp = client.post("/api/contests/9999/submissions", json={"hash": "x"})

    assert resp.status_code == 404


def test_duplicate_submission_rejected(client, db, login_as):
    _creator, contest = active_contest(db)
    make_user(db, "Alice")
    login_as(client, "Alice")
    client.post(f"/api/contests/{contest.id}/submissions",
                json={"hash": _evaluate(client, contest.id)})

    resp = client.post(f"/api/contests/{contest.id}/submissions",
                       json={"hash": _evaluate(client, contest.id)})

    assert resp.status_code == 400


def test_submission_metadata_is_not_tamperable(client, db, login_as):
    _creator, contest = active_contest(db)
    make_user(db, "Alice")
    login_as(client, "Alice")
    h = _evaluate(client, contest.id)

    # Client tries to inject fake metadata alongside the hash — it must be ignored.
    resp = client.post(
        f"/api/contests/{contest.id}/submissions",
        json={"hash": h, "article_metadata": {"byte_count": 999999}},
    )
    body = resp.get_json()

    assert resp.status_code == 201
    assert body["article_metadata"]["byte_count"] == 1234   # server's value


# --- list ---

def test_list_requires_login(client, db):
    _creator, contest = active_contest(db)
    resp = client.get(f"/api/contests/{contest.id}/submissions")
    assert resp.status_code == 401


def test_participant_sees_only_own(client, db, login_as):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    bob = make_user(db, "Bob")
    _submit(contest, alice, "https://en.wikipedia.org/wiki/A")
    _submit(contest, bob, "https://en.wikipedia.org/wiki/B")
    login_as(client, "Alice")

    resp = client.get(f"/api/contests/{contest.id}/submissions")
    links = [s["article_link"] for s in resp.get_json()["submissions"]]

    assert resp.status_code == 200
    assert links == ["https://en.wikipedia.org/wiki/A"]


def test_creator_sees_all(client, db, login_as):
    creator, contest = active_contest(db, "Creator")
    alice = make_user(db, "Alice")
    _submit(contest, alice, "https://en.wikipedia.org/wiki/A")
    _submit(contest, creator, "https://en.wikipedia.org/wiki/C")
    login_as(client, "Creator")

    resp = client.get(f"/api/contests/{contest.id}/submissions")

    assert resp.status_code == 200
    assert len(resp.get_json()["submissions"]) == 2


# --- review (jury only) ---

def test_jury_member_can_review(client, db, login_as):
    _creator, contest = active_contest(db, "Creator",
                                       jury_members=["Judge"], marks_setting_accepted=8)
    alice = make_user(db, "Alice")
    s = _submit(contest, alice)
    login_as(client, "Judge")

    resp = client.post(f"/api/submissions/{s.id}/review", json={"decision": "accept"})
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "accepted"
    assert body["score"] == 8


def test_organizer_sees_all_submissions(client, db, login_as):
    _creator, contest = active_contest(db, "Creator", organizers=["Helper"])
    alice = make_user(db, "Alice")
    bob = make_user(db, "Bob")
    _submit(contest, alice, "https://en.wikipedia.org/wiki/A")
    _submit(contest, bob, "https://en.wikipedia.org/wiki/B")
    login_as(client, "Helper")   # organizer, not the creator

    resp = client.get(f"/api/contests/{contest.id}/submissions")

    assert resp.status_code == 200
    assert len(resp.get_json()["submissions"]) == 2


def test_jury_member_sees_all_submissions(client, db, login_as):
    _creator, contest = active_contest(db, "Creator", jury_members=["Judge"])
    alice = make_user(db, "Alice")
    bob = make_user(db, "Bob")
    _submit(contest, alice, "https://en.wikipedia.org/wiki/A")
    _submit(contest, bob, "https://en.wikipedia.org/wiki/B")
    login_as(client, "Judge")

    resp = client.get(f"/api/contests/{contest.id}/submissions")

    assert resp.status_code == 200
    assert len(resp.get_json()["submissions"]) == 2


def test_creator_cannot_review(client, db, login_as):
    creator, contest = active_contest(db, "Creator")   # creator is not jury
    alice = make_user(db, "Alice")
    s = _submit(contest, alice)
    login_as(client, "Creator")

    resp = client.post(f"/api/submissions/{s.id}/review", json={"decision": "accept"})

    assert resp.status_code == 403


def test_superadmin_cannot_review(client, db, login_as):
    _creator, contest = active_contest(db, "Creator")
    alice = make_user(db, "Alice")
    s = _submit(contest, alice)
    login_as(client, "Jayprakash12345")   # superadmin, not jury

    resp = client.post(f"/api/submissions/{s.id}/review", json={"decision": "accept"})

    assert resp.status_code == 403


def test_review_requires_login(client, db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    s = _submit(contest, alice)

    resp = client.post(f"/api/submissions/{s.id}/review", json={"decision": "accept"})

    assert resp.status_code == 401
