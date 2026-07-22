"""Role-order matrix and capability flags — pure unit tests on the permissions module."""

import pytest

from osaip_api.models import Project
from osaip_api.permissions import ProjectContext, has_role


@pytest.mark.parametrize(
    ("actual", "needed", "expected"),
    [
        (None, "viewer", False),
        ("viewer", "viewer", True),
        ("viewer", "editor", False),
        ("viewer", "admin", False),
        ("editor", "viewer", True),
        ("editor", "editor", True),
        ("editor", "admin", False),
        ("admin", "viewer", True),
        ("admin", "editor", True),
        ("admin", "admin", True),
    ],
)
def test_role_matrix(actual: str | None, needed: str, expected: bool) -> None:
    assert has_role(actual, needed) is expected


def _project(status: str = "active") -> Project:
    return Project(key="x", name="X", status=status, storage_prefix="projects/x")


@pytest.mark.parametrize(
    ("role", "can_edit", "can_manage"),
    [("viewer", False, False), ("editor", True, False), ("admin", True, True)],
)
def test_capabilities_by_role(role: str, can_edit: bool, can_manage: bool) -> None:
    caps = ProjectContext(project=_project(), role=role).capabilities
    assert caps["can_edit"] is can_edit
    assert caps["can_manage_members"] is can_manage
    assert caps["can_archive"] is can_manage


def test_archived_project_has_no_write_capabilities() -> None:
    caps = ProjectContext(project=_project("archived"), role="admin").capabilities
    assert caps == {"can_edit": False, "can_manage_members": False, "can_archive": False}
