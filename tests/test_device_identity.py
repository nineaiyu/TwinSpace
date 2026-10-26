"""Tests for deterministic simulated device identities."""

from twinspace.core.clone_task import CloneTask
from twinspace.core.device_identity import (
    identity_for_clone,
    identity_for_environment,
    instance_number,
    keychain_prefix,
)


def test_environment_identity_matches_known_vector():
    identity = identity_for_environment("mm")
    assert identity.scope == "env|mm"
    assert identity.platform_uuid == "89E76C84-8F48-4FCF-9B92-DF7F9C47EAE5"
    assert identity.serial == "C02Z7Q2R67W2"
    assert identity.seed == "4582d7c2fc276b1a"
    assert identity.hostname == "mm-836b93.local"


def test_environment_identity_is_stable_and_isolated():
    first = identity_for_environment("phone1")
    second = identity_for_environment("phone1")
    other = identity_for_environment("phone2")
    assert first == second
    assert first.platform_uuid != other.platform_uuid
    assert first.serial != other.serial
    assert first.hostname != other.hostname


def test_clone_in_environment_shares_environment_identity():
    shared = identity_for_clone(
        "ZCode-phone1",
        "dev.zcode.phone1",
        env_group="phone1",
    )
    assert shared == identity_for_environment("phone1")

    standalone = identity_for_clone("ZCode-solo", "dev.zcode.solo")
    assert standalone.platform_uuid != shared.platform_uuid
    assert standalone.scope == "clone|ZCode-solo|dev.zcode.solo"


def test_clone_task_delegates_to_device_identity():
    task = CloneTask.__new__(CloneTask)
    task.clone_name = "ZCode-phone1"
    task.new_bundle_id = "dev.zcode.phone1"
    task.env_group = "phone1"

    expected = identity_for_environment("phone1")
    assert task.device_uuid == expected.platform_uuid
    assert task.device_serial == expected.serial
    assert task.device_seed == expected.seed
    assert task.device_hostname == expected.hostname
    assert task.device_identity_key == "env|phone1"
    assert task.keychain_prefix == keychain_prefix("ZCode-phone1", "dev.zcode.phone1")
    assert task.instance_number == "1"


def test_keychain_prefix_and_instance_number_are_stable():
    assert keychain_prefix("Alpha", "a.b") == keychain_prefix("Alpha", "a.b")
    assert keychain_prefix("Alpha", "a.b").startswith("twinspace.")
    assert keychain_prefix("Alpha", "a.b") != keychain_prefix("Beta", "a.b")
    assert instance_number("Clone42", "a.b") == "42"
    assert instance_number("NoDigits", "a.b").isdigit()
