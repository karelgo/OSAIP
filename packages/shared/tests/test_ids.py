import uuid

from osaip_shared.ids import new_id


def test_new_id_is_uuid7() -> None:
    generated = new_id()
    assert isinstance(generated, uuid.UUID)
    assert generated.version == 7


def test_new_ids_are_unique() -> None:
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000
