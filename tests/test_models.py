from sqlalchemy.orm import Session

from app.db import SessionLocal, engine
from app.models import Base, Profile, User


def test_create_user_and_profile():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        user = User(email="ali@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)

        profile = Profile(
            user_id=user.id,
            cv_text="Experienced Java developer...",
            skills='["Java", "Spring"]',
            years_experience=5,
            domains='["banking", "call-center"]',
            target_roles='["Backend Engineer"]',
            target_locations='["Yerevan", "EU remote"]',
            seniority="mid-senior",
            tone="professional",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

        fetched = db.query(Profile).filter_by(user_id=user.id).first()
        assert fetched is not None
        assert fetched.cv_text.startswith("Experienced Java developer")
        assert fetched.years_experience == 5
    finally:
        db.close()
