"""Schema initial V4 v2 — 10 tables, enums, triggers, indexes, seed

Revision ID: 0001
Revises:
Create Date: 2026-04-26

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # ── Trigger générique updated_at ──────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$
    """)

    # ── Enums ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TYPE user_status AS ENUM (
          'pending',
          'active',
          'suspended',
          'deleted'
        )
    """)

    op.execute("""
        CREATE TYPE audit_event_type AS ENUM (
          'user.register',
          'user.login',
          'user.login_failed',
          'user.logout',
          'user.logout_all',
          'user.email_verified',
          'user.password_reset_requested',
          'user.password_reset_completed',
          'user.password_changed',
          'user.profile_updated',
          'user.suspended',
          'user.reactivated',
          'user.deleted',
          'user.role_assigned',
          'user.role_revoked',
          'session.created',
          'session.revoked',
          'session.expired'
        )
    """)

    # ── Table users ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE users (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          email             citext NOT NULL,
          password_hash     text NOT NULL,
          status            user_status NOT NULL DEFAULT 'pending',
          email_verified_at timestamptz,
          last_login_at     timestamptz,
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          deleted_at        timestamptz,
          CONSTRAINT users_email_format_chk CHECK (email ~* '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$')
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX ux_users_email_active
          ON users (email)
          WHERE deleted_at IS NULL
    """)
    op.execute("CREATE INDEX ix_users_status ON users (status)")
    op.execute("CREATE INDEX ix_users_created_at ON users (created_at)")

    op.execute("""
        CREATE TRIGGER trg_users_updated_at
          BEFORE UPDATE ON users
          FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # ── Table profiles ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE profiles (
          user_id     uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          first_name  text,
          last_name   text,
          avatar_url  text,
          locale      text NOT NULL DEFAULT 'fr-FR',
          timezone    text NOT NULL DEFAULT 'Europe/Paris',
          created_at  timestamptz NOT NULL DEFAULT now(),
          updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TRIGGER trg_profiles_updated_at
          BEFORE UPDATE ON profiles
          FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # ── Table roles ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE roles (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          code        text NOT NULL UNIQUE,
          label       text NOT NULL,
          description text,
          created_at  timestamptz NOT NULL DEFAULT now(),
          updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TRIGGER trg_roles_updated_at
          BEFORE UPDATE ON roles
          FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # ── Table permissions ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE permissions (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          code        text NOT NULL UNIQUE,
          label       text NOT NULL,
          description text,
          created_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    # ── Table role_permissions ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE role_permissions (
          role_id       uuid NOT NULL REFERENCES roles(id)       ON DELETE CASCADE,
          permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE RESTRICT,
          granted_at    timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (role_id, permission_id)
        )
    """)

    op.execute("""
        CREATE INDEX ix_role_permissions_permission ON role_permissions (permission_id)
    """)

    # ── Table user_roles ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE user_roles (
          user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          role_id     uuid NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
          assigned_by uuid REFERENCES users(id) ON DELETE SET NULL,
          assigned_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, role_id)
        )
    """)

    op.execute("CREATE INDEX ix_user_roles_role ON user_roles (role_id)")

    # ── Table auth_sessions ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE auth_sessions (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token_hash      bytea NOT NULL,
          expires_at      timestamptz NOT NULL,
          idle_expires_at timestamptz NOT NULL,
          last_seen_at    timestamptz NOT NULL DEFAULT now(),
          revoked_at      timestamptz,
          ip_address      inet,
          user_agent      text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT auth_sessions_token_hash_len_chk CHECK (octet_length(token_hash) = 32)
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX ux_auth_sessions_token_hash ON auth_sessions (token_hash)
    """)
    op.execute("""
        CREATE INDEX ix_auth_sessions_user_active
          ON auth_sessions (user_id)
          WHERE revoked_at IS NULL
    """)
    op.execute("""
        CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at)
    """)

    # ── Table email_verification_tokens ──────────────────────────────────────
    op.execute("""
        CREATE TABLE email_verification_tokens (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token_hash  bytea NOT NULL,
          expires_at  timestamptz NOT NULL,
          used_at     timestamptz,
          created_at  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT email_verif_token_hash_len_chk CHECK (octet_length(token_hash) = 32)
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX ux_email_verif_token_hash
          ON email_verification_tokens (token_hash)
    """)
    op.execute("""
        CREATE INDEX ix_email_verif_user_unused
          ON email_verification_tokens (user_id)
          WHERE used_at IS NULL
    """)

    # ── Table password_reset_tokens ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE password_reset_tokens (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token_hash  bytea NOT NULL,
          expires_at  timestamptz NOT NULL,
          used_at     timestamptz,
          created_at  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT password_reset_token_hash_len_chk CHECK (octet_length(token_hash) = 32)
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX ux_password_reset_token_hash
          ON password_reset_tokens (token_hash)
    """)
    op.execute("""
        CREATE INDEX ix_password_reset_user_unused
          ON password_reset_tokens (user_id)
          WHERE used_at IS NULL
    """)

    # ── Table audit_logs ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE audit_logs (
          id              bigserial PRIMARY KEY,
          actor_user_id   uuid REFERENCES users(id) ON DELETE SET NULL,
          target_user_id  uuid REFERENCES users(id) ON DELETE SET NULL,
          event_type      audit_event_type NOT NULL,
          payload_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
          ip_address      inet,
          user_agent      text,
          created_at      timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX ix_audit_logs_actor
          ON audit_logs (actor_user_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX ix_audit_logs_target
          ON audit_logs (target_user_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX ix_audit_logs_event_type
          ON audit_logs (event_type, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at DESC)
    """)
    op.execute("""
        CREATE INDEX gx_audit_logs_payload
          ON audit_logs USING gin (payload_json jsonb_path_ops)
    """)

    # ── Seed : permissions ────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO permissions (code, label, description) VALUES
          ('users.read',      'Lire utilisateurs',      'Lister et consulter les fiches utilisateurs'),
          ('users.write',     'Modifier utilisateurs',  'Editer les utilisateurs et leurs profils'),
          ('users.invite',    'Inviter utilisateurs',   'Envoyer des invitations'),
          ('users.suspend',   'Suspendre/reactiver',    'Changer le statut d''un compte'),
          ('roles.assign',    'Assigner des roles',     'Ajouter/retirer des roles aux utilisateurs'),
          ('roles.manage',    'Gerer les roles',        'CRUD sur les roles eux-memes'),
          ('sessions.revoke', 'Revoquer des sessions',  'Revoquer la session d''un autre utilisateur'),
          ('audit.read',      'Lire les audit logs',    'Acceder aux journaux')
    """)

    # ── Seed : roles ──────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO roles (code, label, description) VALUES
          ('admin',   'Administrateur', 'Acces complet a la plateforme'),
          ('manager', 'Manager',        'Gestion utilisateurs et roles non-admin'),
          ('support', 'Support',        'Assistance utilisateurs en lecture'),
          ('user',    'Utilisateur',    'Compte standard')
    """)

    # ── Seed : role_permissions — admin → toutes ──────────────────────────────
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p WHERE r.code = 'admin'
    """)

    # ── Seed : role_permissions — manager ────────────────────────────────────
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE r.code = 'manager'
          AND p.code IN (
            'users.read', 'users.write', 'users.invite', 'users.suspend',
            'roles.assign', 'sessions.revoke', 'audit.read'
          )
    """)

    # ── Seed : role_permissions — support ────────────────────────────────────
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE r.code = 'support'
          AND p.code IN ('users.read', 'audit.read')
    """)


def downgrade() -> None:
    # Tables dans l'ordre inverse des dépendances
    op.execute("DROP TABLE IF EXISTS audit_logs")
    op.execute("DROP TABLE IF EXISTS password_reset_tokens")
    op.execute("DROP TABLE IF EXISTS email_verification_tokens")
    op.execute("DROP TABLE IF EXISTS auth_sessions")
    op.execute("DROP TABLE IF EXISTS user_roles")
    op.execute("DROP TABLE IF EXISTS role_permissions")
    op.execute("DROP TABLE IF EXISTS permissions")
    op.execute("DROP TABLE IF EXISTS roles")
    op.execute("DROP TABLE IF EXISTS profiles")
    op.execute("DROP TABLE IF EXISTS users")

    op.execute("DROP TYPE IF EXISTS audit_event_type")
    op.execute("DROP TYPE IF EXISTS user_status")

    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
