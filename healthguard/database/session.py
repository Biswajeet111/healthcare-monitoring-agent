from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from healthguard.core.config import settings

connect_args = {}
engine_kwargs = {"pool_pre_ping": True}

if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    sqlite_file = settings.DATABASE_URL.replace("sqlite:///", "", 1)
    if sqlite_file and sqlite_file != ":memory:":
        Path(sqlite_file).parent.mkdir(parents=True, exist_ok=True)
else:
    engine_kwargs["pool_recycle"] = 300

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
