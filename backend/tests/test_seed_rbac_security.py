from pathlib import Path


SEED_PATH = (
    Path(__file__).parents[1]
    / "db"
    / "seed_rbac.py"
)


def test_rbac_seeder_contains_no_built_in_accounts() -> None:
    source = SEED_PATH.read_text(
        encoding="utf-8",
    )

    forbidden_tokens = {
        "admin123",
        "user123",
        "get_or_create_user",
        "bcrypt.hash",
        'username="admin"',
        'username="user1"',
        "admin_user",
        "normal_user",
    }

    for token in forbidden_tokens:
        assert token not in source


def test_rbac_seeder_only_provisions_metadata() -> None:
    source = SEED_PATH.read_text(
        encoding="utf-8",
    )

    assert "get_or_create_permission" in source
    assert "get_or_create_role" in source
    assert "permissions_data" in source
    assert "admin_role.permissions = permissions" in source
    assert "db.commit()" in source
    assert "User(" not in source
    assert ".roles =" not in source
