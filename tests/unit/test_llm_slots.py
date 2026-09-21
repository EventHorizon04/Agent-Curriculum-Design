"""`SLOTS` is the one declaration of an LLM slot, so it is the one thing that
can be wrong about all of them at once.

A slot's provider and model are named as strings, which is what keeps one entry
to one line — and what mypy cannot check. These tests are the substitute: a
misspelled field name fails pytest instead of surfacing at boot as a slot
pointing at nothing.
"""

from __future__ import annotations

import pytest

from curriculum_agent.config import SLOTS, Settings, SlotSpec


def test_every_declared_field_exists_on_settings() -> None:
    """The check mypy cannot do for a getattr.

    `_apply_provider_model_defaults` and `_slot_provider` both reach these
    fields by name. A typo there is invisible until something reads the slot,
    and what it reads then is a model of "" pointed at no provider.
    """
    declared = set(Settings.model_fields)
    for slot in SLOTS:
        assert slot.model_field in declared, f"{slot.name}: no field '{slot.model_field}'"
        if slot.provider_field is not None:
            assert slot.provider_field in declared, (
                f"{slot.name}: no field '{slot.provider_field}'"
            )


def test_the_field_check_would_actually_catch_one() -> None:
    """A guard that silently matches nothing is the failure it exists to catch."""
    fabricated = SlotSpec("invented", "invented_provider", "invented_model")

    assert fabricated.model_field not in set(Settings.model_fields)


def test_slot_names_are_unique() -> None:
    """The name is the label in the startup log and the key `_slot` looks up, so
    two slots sharing one makes the second unreachable and the log ambiguous."""
    names = [slot.name for slot in SLOTS]

    assert len(set(names)) == len(names), names


def test_exactly_one_slot_can_be_switched_off() -> None:
    """`disableable` is not a convenience: it says "" is a meaningful value for
    this slot's provider, which is true of the validation agent's kill switch
    and of nothing else. A second disableable slot would mean a second provider
    field where empty and unset differ, and every reader of that field would
    have to learn the distinction."""
    disableable = [slot.name for slot in SLOTS if slot.disableable]

    assert disableable == ["validation"]


def test_asking_for_a_slot_that_does_not_exist_says_so() -> None:
    """`_resolve` takes a name, so a typo at a call site has to fail loudly
    rather than resolve to a default slot."""
    from curriculum_agent import llm

    with pytest.raises(KeyError, match="no LLM slot named"):
        llm._slot("heavey")
