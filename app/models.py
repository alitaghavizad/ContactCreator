import enum
from datetime import datetime

from sqlalchemy import Column, Date, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class OutreachChannel(str, enum.Enum):
    linkedin = "linkedin"
    email = "email"


class OutreachStatus(str, enum.Enum):
    drafted = "drafted"
    sent = "sent"
    replied = "replied"
    no_response = "no_response"
    interview = "interview"
    rejected = "rejected"
    failed = "failed"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    profile = relationship("Profile", back_populates="user", uselist=False)


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cv_text = Column(Text, nullable=False)
    skills = Column(Text)
    years_experience = Column(Integer)
    domains = Column(Text)
    target_roles = Column(Text)
    target_locations = Column(Text)
    seniority = Column(String)
    tone = Column(String)

    user = relationship("User", back_populates="profile")


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    domain = Column(String)
    location = Column(String)
    industry = Column(String)
    source = Column(String, default="apollo")


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    title = Column(String)
    linkedin_url = Column(String)
    email = Column(String)
    discovery_source = Column(String, default="apollo")

    company = relationship("Company")


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    channel = Column(SAEnum(OutreachChannel), nullable=False)
    draft_text = Column(Text, nullable=False)
    status = Column(SAEnum(OutreachStatus), default=OutreachStatus.drafted)
    sent_at = Column(DateTime, nullable=True)
    follow_up_due_at = Column(DateTime, nullable=True)

    contact = relationship("Contact")


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    type = Column(String, nullable=False)
    note = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class ApolloUsage(Base):
    __tablename__ = "apollo_usage"
    id = Column(Integer, primary_key=True)
    used = Column(Integer, default=0)
    period_start = Column(Date)
