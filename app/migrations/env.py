# app/migrations/env.py
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
from dotenv import load_dotenv

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# โหลด .env
load_dotenv()

# ใช้ Base จาก app.db เท่านั้น
from app.db import Base

# import โมเดลทั้งหมดเพื่อให้ถูกผูกกับ Base.metadata
# (อย่า import app.create_app หรือ blueprint)
import app.models.user
import app.models.security_answer
import app.models.package
import app.models.payment
import app.models.user_package
import app.models.car_cache
import app.models.search      # ✅ ใช้ไฟล์นี้เท่านั้นสำหรับ SearchSession


target_metadata = Base.metadata

# ถ้า alembic.ini มี sqlalchemy.url เป็นค่า dummy ให้ override ด้วย env
db_url = os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
