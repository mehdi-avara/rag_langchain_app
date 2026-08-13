import inspect
import os
from datetime import (
    datetime,
    timedelta,
)
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault(
    "POSTGRES_DB",
    "test",
)
os.environ.setdefault(
    "POSTGRES_USER",
    "test",
)
os.environ.setdefault(
    "POSTGRES_PASSWORD",
    "test",
)
os.environ.setdefault(
    "POSTGRES_IP",
    "localhost",
)
os.environ.setdefault(
    "default_username",
    "admin",
)
os.environ.setdefault(
    "default_password",
    "admin123456",
)
os.environ.setdefault(
    "default_firstname",
    "Admin",
)
os.environ.setdefault(
    "jwt_secret",
    "test-secret",
)
os.environ.setdefault(
    "openai_api_key",
    "test",
)
os.environ.setdefault(
    "jina_api_key",
    "test",
)

from Models.user_invitation import (
    UserInvitation,
    user_invitation_role,
)
from core import user_invitations
from core.authorization import (
    is_tenant_permission_name,
)
from db import seed_rbac
from routs import auth, rbac
from schemas.user_invitations import (
    AdminUserInvitationCreate,
    AdminUserInvitationOut,
    AdminUserInvitationTokenOut,
    PublicUserInvitationStatusOut,
    UserInvitationAcceptIn,
    UserInvitationAcceptOut,
    UserInvitationTokenIn,
)
from settings import Settings


def test_invitation_permissions_are_tenant_scoped():
    assert is_tenant_permission_name(
        "users:invitations:read"
    )

    assert is_tenant_permission_name(
        "users:invitations:manage"
    )


def test_seed_contains_invitation_permissions():
    source = inspect.getsource(
        seed_rbac.seed
    )

    assert (
        '"users:invitations:read"'
        in source
    )

    assert (
        '"users:invitations:manage"'
        in source
    )


def test_invitation_model_stores_hash_not_raw_token():
    columns = {
        column.name
        for column
        in UserInvitation.__table__.columns
    }

    assert "token_hash" in columns

    assert "token" not in columns

    assert "invitation_token" not in columns

    assert (
        UserInvitation.__table__
        .c.token_hash.type.length
        == 64
    )


def test_invitation_role_assignment_is_relational():
    columns = {
        column.name
        for column
        in user_invitation_role.columns
    }

    assert columns == {
        "invitation_id",
        "role_id",
    }


def test_invitation_token_is_random_and_hashed():
    token_one = (
        user_invitations
        .generate_invitation_token()
    )

    token_two = (
        user_invitations
        .generate_invitation_token()
    )

    assert token_one != token_two

    hash_one = (
        user_invitations
        .hash_invitation_token(
            token_one
        )
    )

    assert len(hash_one) == 64

    assert token_one not in hash_one


def test_invitation_status_contract():
    now = datetime.utcnow()

    pending = SimpleNamespace(
        accepted_at=None,
        revoked_at=None,
        expires_at=(
            now
            + timedelta(hours=1)
        ),
    )

    accepted = SimpleNamespace(
        accepted_at=now,
        revoked_at=None,
        expires_at=(
            now
            + timedelta(hours=1)
        ),
    )

    revoked = SimpleNamespace(
        accepted_at=None,
        revoked_at=now,
        expires_at=(
            now
            + timedelta(hours=1)
        ),
    )

    expired = SimpleNamespace(
        accepted_at=None,
        revoked_at=None,
        expires_at=(
            now
            - timedelta(seconds=1)
        ),
    )

    assert (
        user_invitations
        .invitation_status(
            pending,
            now=now,
        )
        == "pending"
    )

    assert (
        user_invitations
        .invitation_status(
            accepted,
            now=now,
        )
        == "accepted"
    )

    assert (
        user_invitations
        .invitation_status(
            revoked,
            now=now,
        )
        == "revoked"
    )

    assert (
        user_invitations
        .invitation_status(
            expired,
            now=now,
        )
        == "expired"
    )


def test_invitation_default_lifetime_is_bounded():
    assert (
        Settings.model_fields[
            "user_invitation_exp_hours"
        ].default
        == 72
    )


def test_admin_create_schema_normalizes_email():
    payload = (
        AdminUserInvitationCreate(
            email=" Person@Example.COM ",
            first_name=" Person ",
            role_ids=[
                4,
                4,
                2,
            ],
        )
    )

    assert (
        payload.email
        == "person@example.com"
    )

    assert (
        payload.first_name
        == "Person"
    )

    assert payload.role_ids == [
        2,
        4,
    ]


def test_public_invitation_inputs_use_secret_types():
    token = UserInvitationTokenIn(
        invitation_token="secret-token-value"
    )

    accept = UserInvitationAcceptIn(
        invitation_token="secret-token-value",
        password="StrongPassword123!",
    )

    assert (
        "**********"
        in str(
            token.invitation_token
        )
    )

    assert (
        accept.password.get_secret_value()
        == "StrongPassword123!"
    )


def test_safe_output_schemas_do_not_expose_hash():
    safe_schemas = (
        AdminUserInvitationOut,
        PublicUserInvitationStatusOut,
        UserInvitationAcceptOut,
    )

    for schema in safe_schemas:
        fields = set(
            schema.model_fields
        )

        assert "token_hash" not in fields
        assert "invitation_token" not in fields
        assert "password" not in fields


def test_raw_token_output_is_explicit_one_time_schema():
    fields = set(
        AdminUserInvitationTokenOut
        .model_fields
    )

    assert (
        "invitation_token"
        in fields
    )

    assert "token_hash" not in fields


def test_admin_invitation_route_permissions():
    list_source = inspect.getsource(
        rbac.list_company_user_invitations
    )

    create_source = inspect.getsource(
        rbac.create_company_user_invitation
    )

    reissue_source = inspect.getsource(
        rbac.reissue_company_user_invitation
    )

    revoke_source = inspect.getsource(
        rbac.revoke_company_user_invitation
    )

    assert (
        "users:invitations:read"
        in list_source
    )

    for source in (
        create_source,
        reissue_source,
        revoke_source,
    ):
        assert (
            "users:invitations:manage"
            in source
        )


def test_public_invitation_token_is_not_in_url_path():
    source = Path(
        auth.__file__
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"/invitations/{token}'
        not in source
    )

    assert (
        '"/invitations/status"'
        in source
    )

    assert (
        '"/invitations/accept"'
        in source
    )


def test_invitation_acceptance_is_row_locked():
    source = inspect.getsource(
        user_invitations
        .accept_user_invitation
    )

    assert "lock=True" in source

    lookup_source = inspect.getsource(
        user_invitations
        .get_invitation_by_token
    )

    assert (
        ".with_for_update()"
        in lookup_source
    )


def test_reissue_and_revoke_are_row_locked():
    reissue = inspect.getsource(
        user_invitations
        .reissue_user_invitation
    )

    revoke = inspect.getsource(
        user_invitations
        .revoke_user_invitation
    )

    assert "lock=True" in reissue
    assert "lock=True" in revoke


def test_invitation_role_scope_matches_tenant_policy():
    source = inspect.getsource(
        user_invitations
        ._role_scope_query
    )

    assert (
        "Role.company_id"
        in source
    )

    assert (
        "GLOBAL_USER_ROLE_NAME"
        in source
    )

    assert (
        "GLOBAL_ADMIN_ROLE_NAME"
        not in source
    )


def test_role_count_detects_deleted_assignments():
    source = inspect.getsource(
        user_invitations
        .validate_assigned_invitation_roles
    )

    assert (
        "invitation.role_count"
        in source
    )

    assert (
        "Invitation roles are no longer valid"
        in source
    )


def test_create_invitation_does_not_create_user():
    source = inspect.getsource(
        user_invitations
        .create_user_invitation
    )

    assert (
        "UserInvitation("
        in source
    )

    assert (
        "\n    user = User("
        not in source
    )


def test_acceptance_creates_user_and_provisions_defaults():
    source = inspect.getsource(
        user_invitations
        .accept_user_invitation
    )

    assert "user = User(" in source

    assert (
        "provision_company_defaults"
        in source
    )

    assert (
        "invitation.accepted_at"
        in source
    )


def test_acceptance_does_not_issue_login_tokens():
    source = (
        inspect.getsource(
            auth.accept_public_user_invitation
        )
        + inspect.getsource(
            user_invitations
            .accept_user_invitation
        )
    )

    assert (
        "create_token_pair"
        not in source
    )

    assert (
        "create_auth_session"
        not in source
    )


def test_invitation_admin_audit_events_exist():
    source = Path(
        rbac.__file__
    ).read_text(
        encoding="utf-8"
    )

    for action in (
        "user.invited",
        "user.invitation_reissued",
        "user.invitation_revoked",
    ):
        assert action in source

    accept_source = inspect.getsource(
        user_invitations
        .accept_user_invitation
    )

    assert (
        "user.invitation_accepted"
        in accept_source
    )


def test_invitation_audit_source_never_includes_raw_token():
    rbac_source = (
        inspect.getsource(
            rbac.create_company_user_invitation
        )
        + inspect.getsource(
            rbac.reissue_company_user_invitation
        )
        + inspect.getsource(
            rbac.revoke_company_user_invitation
        )
    )

    assert (
        '"invitation_token"'
        not in rbac_source
    )

    assert (
        '"token_hash"'
        not in rbac_source
    )


def test_existing_registration_policy_is_unchanged():
    source = inspect.getsource(
        auth.register
    )

    assert (
        'self_registration_mode != "open"'
        in source
    )

    assert (
        "create_token_pair"
        in source
    )


def test_invitation_service_adds_no_mail_transport():
    source = Path(
        user_invitations.__file__
    ).read_text(
        encoding="utf-8"
    ).casefold()

    for forbidden in (
        "smtplib",
        "sendgrid",
        "mailgun",
        "postmark",
        "send_email",
        "send_mail",
    ):
        assert forbidden not in source


def test_migration_contract():
    path = Path(
        "alembic/versions/"
        "57a4e5f6b7c8_add_user_invitation_foundation.py"
    )

    source = path.read_text(
        encoding="utf-8"
    )

    assert (
        'revision: str = "57a4e5f6b7c8"'
        in source
    )

    assert (
        'down_revision: str | None = "46f3d4e5a6b7"'
        in source
    )

    assert (
        '"user_invitations"'
        in source
    )

    assert (
        '"user_invitation_role"'
        in source
    )

    assert (
        "uq_user_invitations_open_company_email"
        in source
    )

    normalized_source = " ".join(
        source.split()
    )

    assert (
        "accepted_at IS NULL"
        in normalized_source
    )

    assert (
        "AND revoked_at IS NULL"
        in normalized_source
    )

    assert (
        '"token_hash"'
        in source
    )
