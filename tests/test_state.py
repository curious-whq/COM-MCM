import pytest

from umcm.errors import SchemaError
from umcm.ir.event import EventCatalog, EventType
from umcm.ir.expression import Literal
from umcm.ir.sort import BOOL
from umcm.ir.state import StateRequirement, StateUpdate, StateVariable
from umcm.ir.transformation import EventRole, Transformation


def test_state_variable_requires_qualified_name() -> None:
    with pytest.raises(SchemaError):
        StateVariable("valid", BOOL, False)


def test_stateful_transformation_cannot_have_existential_outputs() -> None:
    with pytest.raises(SchemaError):
        Transformation(
            name="bad",
            inputs=(EventRole("input", "Test.Input"),),
            outputs=(EventRole("output", "Test.Output"),),
            state_updates=(
                StateUpdate(
                    state="Test.state.valid",
                    at="input",
                    value=Literal(True, BOOL),
                ),
            ),
        )


def test_state_requirement_and_update_validate_against_catalog() -> None:
    catalog = EventCatalog(
        {
            "Test.Input": EventType(
                name="Test.Input",
                module="Test",
                layer="test",
            )
        }
    )
    variable = StateVariable("Test.state.valid", BOOL, False)
    transformation = Transformation(
        name="set_valid",
        inputs=(EventRole("input", "Test.Input"),),
        state_requirements=(
            StateRequirement(
                state=variable.name,
                at="input",
                op="eq",
                value=Literal(False, BOOL),
            ),
        ),
        state_updates=(
            StateUpdate(
                state=variable.name,
                at="input",
                value=Literal(True, BOOL),
            ),
        ),
    )
    transformation.validate(catalog, {variable.name: variable})
