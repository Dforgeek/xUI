from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

    users = relationship("User", back_populates="department")
    surveys = relationship("Survey", back_populates="department")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    is_manager = Column(Boolean, default=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)

    department = relationship("Department", back_populates="users")
    invitations = relationship("Invitation", back_populates="user")

class Survey(Base):
    __tablename__ = "surveys"
    id = Column(Integer, primary_key=True)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="open")  # open, reminding, finalized
    summary = Column(Text, nullable=True)

    department = relationship("Department", back_populates="surveys")
    invitations = relationship("Invitation", back_populates="survey")

class Invitation(Base):
    __tablename__ = "invitations"
    id = Column(Integer, primary_key=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    reminder_sent = Column(Boolean, default=False)

    survey = relationship("Survey", back_populates="invitations")
    user = relationship("User", back_populates="invitations")
    responses = relationship("Response", back_populates="invitation")

class Response(Base):
    __tablename__ = "responses"
    id = Column(Integer, primary_key=True)
    invitation_id = Column(Integer, ForeignKey("invitations.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    invitation = relationship("Invitation", back_populates="responses")

