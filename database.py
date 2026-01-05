from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    tg_id = Column(Integer, primary_key=True)
    username = Column(String)
    is_approved = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    storage_limit = Column(Float, default=0.0) # In MB
    used_storage = Column(Float, default=0.0)
    plan_expiry = Column(DateTime, nullable=True)

# Railway provides the DATABASE_URL automatically
engine = create_engine(os.getenv("DATABASE_URL"))
Session = sessionmaker(bind=engine)
session = Session()

def init_db():
    Base.metadata.create_all(engine)
