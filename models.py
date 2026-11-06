"""SQLAlchemy 2.x models for Trainly persistence."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, REAL, Text, text as sql_text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int | None] = mapped_column(Integer, primary_key=True, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    password: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)

class Workspace(Base):
    __tablename__ = 'workspaces'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)

class Membership(Base):
    __tablename__ = 'memberships'
    workspace_id: Mapped[str] = mapped_column(Text, ForeignKey('workspaces.id'), primary_key=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), primary_key=True, nullable=False, unique=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (CheckConstraint("role IN ('creator','learner','admin')"),)

class Invitation(Base):
    __tablename__ = 'invitations'
    token_hash: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    workspace_id: Mapped[str] = mapped_column(Text, ForeignKey('workspaces.id'), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    module_id: Mapped[str | None] = mapped_column(Text, ForeignKey('modules.id'), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    expires: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (CheckConstraint("role IN ('creator','learner')"),)

class LoginSession(Base):
    __tablename__ = 'sessions'
    token: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    csrf: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires: Mapped[int | None] = mapped_column(Integer, nullable=True)

class TrainingModule(Base):
    __tablename__ = 'modules'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    owner: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'local'"))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=sql_text("''"))
    video: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=sql_text("''"))
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default=sql_text('0'))
    status: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=sql_text("'draft'"))
    published_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text('0'))
    pass_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text('70'))
    upload_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    playback_video: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    media_asset_id: Mapped[str | None] = mapped_column(Text, nullable=True)

class MediaAsset(Base):
    __tablename__ = 'media_assets'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    module_id: Mapped[str] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    playback_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    container: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)

class Lesson(Base):
    __tablename__ = 'lessons'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    module_id: Mapped[str | None] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), nullable=True)
    ord: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    start: Mapped[float | None] = mapped_column(REAL, nullable=True)
    end: Mapped[float | None] = mapped_column(REAL, nullable=True)
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'manual'"))

class Question(Base):
    __tablename__ = 'questions'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    module_id: Mapped[str | None] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), nullable=True)
    ord: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[float | None] = mapped_column(REAL, nullable=True)
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'manual'"))

class TranscriptSegment(Base):
    __tablename__ = 'transcript_segments'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    module_id: Mapped[str] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), nullable=False)
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    start: Mapped[float] = mapped_column(REAL, nullable=False)
    end: Mapped[float] = mapped_column(REAL, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'manual'"))
    edited: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text('0'))

class Attempt(Base):
    __tablename__ = 'attempts'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    module_id: Mapped[str | None] = mapped_column(Text, ForeignKey('modules.id'), nullable=True)
    learner: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default=sql_text('0'))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text('0'))

class Answer(Base):
    __tablename__ = 'answers'
    id: Mapped[int | None] = mapped_column(Integer, primary_key=True, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(Text, ForeignKey('attempts.id'), nullable=True)
    question_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    choice: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct: Mapped[int | None] = mapped_column(Integer, nullable=True)

class AttemptProgress(Base):
    __tablename__ = 'attempt_progress'
    attempt_id: Mapped[str | None] = mapped_column(Text, ForeignKey('attempts.id', ondelete='CASCADE'), primary_key=True, nullable=True)
    position: Mapped[float] = mapped_column(REAL, nullable=False, server_default=sql_text('0'))
    completed_lessons: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))

class ModuleVersion(Base):
    __tablename__ = 'module_versions'
    module_id: Mapped[str] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), primary_key=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    video: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    playback_video: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    media_asset_id: Mapped[str | None] = mapped_column(Text, ForeignKey('media_assets.id'), nullable=True)

class Assignment(Base):
    __tablename__ = 'assignments'
    module_id: Mapped[str] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), primary_key=True, nullable=False)
    learner: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True, nullable=False)
    assigned_at: Mapped[int] = mapped_column(Integer, nullable=False)

class ProcessingJob(Base):
    __tablename__ = 'processing_jobs'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    module_id: Mapped[str] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), nullable=False)
    workspace_id: Mapped[str] = mapped_column(Text, ForeignKey('workspaces.id'), nullable=False)
    asset: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'inspection'"))
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'queued'"))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text('0'))
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_state: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'pending'"))
    draft_state: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'pending'"))
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (Index('processing_jobs_state_created', 'state', 'created_at'),)

class GeneratedDraft(Base):
    __tablename__ = 'generated_drafts'
    module_id: Mapped[str | None] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), primary_key=True, nullable=True)
    transcript: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    lessons: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    questions: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'ready'"))
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int | None] = mapped_column(Integer, primary_key=True, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    module_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    meta: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'{}'"))
    __table_args__ = (Index('events_module', 'module_id', 'created_at'), Index('events_name_created', 'name', 'created_at'),)

class AccountSetup(Base):
    __tablename__ = 'account_setups'
    token_hash: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    expires: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (Index('account_setups_user', 'user_id'),)

class Call(Base):
    __tablename__ = 'calls'
    id: Mapped[str | None] = mapped_column(Text, primary_key=True, nullable=True)
    workspace_id: Mapped[str] = mapped_column(Text, ForeignKey('workspaces.id'), nullable=False)
    module_id: Mapped[str] = mapped_column(Text, ForeignKey('modules.id', ondelete='CASCADE'), nullable=False)
    learner: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    creator: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    initiated_by: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'learner'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'ringing'"))
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ended_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ended_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (Index('calls_learner_created', 'learner', 'created_at'), Index('calls_creator_created', 'creator', 'created_at'),)
