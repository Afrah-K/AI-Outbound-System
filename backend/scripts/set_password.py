"""
Set (or reset) the password for an account, from the command line - e.g. so
the account that owns your existing data (Google sign-in only by default)
can also sign in with email + password.

USAGE (from backend/):
    python scripts/set_password.py afrahkausar2020@gmail.com
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import User, UserSession  # noqa: E402
from app.services.auth import check_password_strength, hash_password, normalize_email  # noqa: E402
from app.tenancy import system_context  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    email = normalize_email(sys.argv[1])

    init_db()
    with system_context():
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                print(f"No account for {email}.")
                sys.exit(1)

            password = getpass.getpass(f"New password for {email}: ")
            problem = check_password_strength(password)
            if problem:
                print(problem)
                sys.exit(1)
            if getpass.getpass("Type it again: ") != password:
                print("The passwords don't match.")
                sys.exit(1)

            user.password_hash = hash_password(password)
            # Sign out everywhere else, as a password reset should
            db.query(UserSession).filter(UserSession.user_id == user.id).delete()
            db.commit()
            print(f"Password set for {email}. Sign in with it on the login page.")
        finally:
            db.close()


if __name__ == "__main__":
    main()
