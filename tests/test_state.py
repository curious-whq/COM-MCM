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


def test_stateful_transformation_can_update_on_emitted_output() -> None:
    from umcm.ir.completion import CompletionSpec, EventSlot
    from umcm.ir.event import EventInstance
    from umcm.ir.trace import Trace
    from umcm.solver.completion import CompletionStatus, complete_trace

    catalog = EventCatalog(
        {
            "Test.Input": EventType(
                name="Test.Input", module="Test", layer="test"
            ),
            "Test.Output": EventType(
                name="Test.Output", module="Test", layer="test"
            ),
        }
    )
    variable = StateVariable("Test.state.valid", BOOL, False)
    transition = Transformation(
        name="emit_and_update",
        inputs=(EventRole("input", "Test.Input"),),
        outputs=(EventRole("output", "Test.Output"),),
        state_updates=(
            StateUpdate(
                state=variable.name,
                at="output",
                value=Literal(True, BOOL),
            ),
        ),
    )
    trace = Trace(
        events=[EventInstance("input_0", "Test.Input", cycle=0)],
        partial=True,
    )
    spec = CompletionSpec(
        slots=[EventSlot("output_0", "Test.Output")],
        transformations=[transition],
        state_variables=[variable],
        horizon=2,
    )

    result = complete_trace(catalog, trace, spec)

    assert result.status is CompletionStatus.FEASIBLE
    assert result.added_event_ids == ("output_0",)
    assert result.final_state[variable.name] is True


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


def test_exact_transformation_requires_one_derived_output() -> None:
    with pytest.raises(SchemaError, match="exact transformation"):
        Transformation(
            name="bad_exact",
            inputs=(EventRole("input", "Test.Input"),),
            exact=True,
        )


def test_exact_transformation_roundtrip() -> None:
    transition = Transformation(
        name="accepted",
        inputs=(
            EventRole("valid", "Test.Valid"),
            EventRole("ready", "Test.Ready"),
        ),
        outputs=(EventRole("fire", "Test.Fire"),),
        exact=True,
    )
    loaded = Transformation.from_dict(transition.to_dict())
    assert loaded == transition
    assert loaded.exact is True


def test_z3_linear_state_encoding_rejects_conflicting_atomic_writes() -> None:
    from umcm.ir.completion import CompletionSpec
    from umcm.ir.event import EventInstance
    from umcm.ir.trace import Trace
    from umcm.solver.completion import CompletionStatus, complete_trace

    catalog = EventCatalog(
        {"Test.Input": EventType(name="Test.Input", module="Test", layer="test")}
    )
    variable = StateVariable("Test.state.valid", BOOL, False)
    set_true = Transformation(
        name="set_true",
        inputs=(EventRole("input", "Test.Input"),),
        state_updates=(
            StateUpdate(variable.name, "input", Literal(True, BOOL)),
        ),
    )
    set_false = Transformation(
        name="set_false",
        inputs=(EventRole("input", "Test.Input"),),
        state_updates=(
            StateUpdate(variable.name, "input", Literal(False, BOOL)),
        ),
    )
    result = complete_trace(
        catalog,
        Trace(events=[EventInstance("input_0", "Test.Input", cycle=0)], partial=True),
        CompletionSpec(
            transformations=[set_true, set_false],
            state_variables=[variable],
            horizon=1,
        ),
        backend="z3",
    )

    assert result.status is CompletionStatus.INFEASIBLE
