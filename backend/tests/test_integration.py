"""Test d'intégration — crée un user lié au rôle admin et vérifie les relations.

Prérequis : base de données lancée et migrations appliquées.
  docker compose up -d db
  docker compose run --rm api alembic upgrade head

Lancement :
  DATABASE_URL=postgresql://postgres:changeme@localhost:5432/projet_action pytest tests/test_integration.py -v
"""
import hashlib
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:changeme@localhost:5432/projet_action",
)


@pytest.fixture(scope="module")
def db():
    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _argon2_placeholder() -> str:
    """Retourne un hash Argon2id factice valide pour les tests."""
    return "$argon2id$v=19$m=65536,t=3,p=4$dGVzdA$fakehashfortesting000000000000000000000000000000000"


def test_create_user_with_admin_role(db):
    """Crée un user, l'associe au rôle admin, et vérifie ses permissions."""
    unique_email = f"test-{uuid.uuid4().hex[:8]}@example.com"

    # Créer le user
    db.execute(
        text("""
            INSERT INTO users (email, password_hash, status)
            VALUES (:email, :pwd, 'active')
        """),
        {"email": unique_email, "pwd": _argon2_placeholder()},
    )
    db.commit()

    user_row = db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": unique_email},
    ).fetchone()
    assert user_row is not None, "User non trouvé après insertion"
    user_id = user_row[0]

    # Créer le profil associé
    db.execute(
        text("""
            INSERT INTO profiles (user_id) VALUES (:uid)
        """),
        {"uid": user_id},
    )

    # Récupérer le rôle admin
    admin_row = db.execute(
        text("SELECT id FROM roles WHERE code = 'admin'"),
    ).fetchone()
    assert admin_row is not None, "Rôle admin absent — seed non appliqué ?"
    admin_role_id = admin_row[0]

    # Assigner le rôle admin au user
    db.execute(
        text("""
            INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid)
        """),
        {"uid": user_id, "rid": admin_role_id},
    )
    db.commit()

    # Vérifier que le user a bien le rôle admin
    role_check = db.execute(
        text("""
            SELECT r.code
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :uid
        """),
        {"uid": user_id},
    ).fetchone()
    assert role_check is not None
    assert role_check[0] == "admin"

    # Vérifier que l'admin a toutes les permissions (8 attendues)
    perm_count = db.execute(
        text("""
            SELECT COUNT(*)
            FROM user_roles ur
            JOIN role_permissions rp ON rp.role_id = ur.role_id
            WHERE ur.user_id = :uid
        """),
        {"uid": user_id},
    ).scalar()
    assert perm_count == 8, f"Admin doit avoir 8 permissions, trouvé : {perm_count}"

    # Nettoyage
    db.execute(text("DELETE FROM user_roles WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM profiles WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    db.commit()


def test_seed_roles_and_permissions(db):
    """Vérifie que le seed contient bien 4 rôles et 8 permissions."""
    role_count = db.execute(text("SELECT COUNT(*) FROM roles")).scalar()
    assert role_count == 4, f"Attendu 4 rôles, trouvé : {role_count}"

    perm_count = db.execute(text("SELECT COUNT(*) FROM permissions")).scalar()
    assert perm_count == 8, f"Attendu 8 permissions, trouvé : {perm_count}"

    role_codes = {
        row[0]
        for row in db.execute(text("SELECT code FROM roles")).fetchall()
    }
    assert role_codes == {"admin", "manager", "support", "user"}


def test_unique_email_constraint(db):
    """Vérifie que deux users actifs avec le même email sont rejetés."""
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"

    db.execute(
        text("INSERT INTO users (email, password_hash) VALUES (:e, :p)"),
        {"e": email, "p": _argon2_placeholder()},
    )
    db.commit()

    with pytest.raises(Exception):
        db.execute(
            text("INSERT INTO users (email, password_hash) VALUES (:e, :p)"),
            {"e": email, "p": _argon2_placeholder()},
        )
        db.commit()

    db.rollback()

    # Nettoyage
    db.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
    db.commit()
