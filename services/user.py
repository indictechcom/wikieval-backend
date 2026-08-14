from model import User, db


def get_or_create_user(username):
    user = User.query.filter_by(username=username).first()
    if user:
        return user

    user = User(username=username)
    db.session.add(user)
    db.session.commit()

    return user


def ensure_users(usernames):
    names = [u for u in (usernames or []) if u]
    if not names:
        return

    existing = {
        u.username for u in User.query.filter(User.username.in_(names)).all()
    }
    created = False
    for username in names:
        if username not in existing:
            db.session.add(User(username=username))
            existing.add(username)
            created = True
    if created:
        db.session.commit()

