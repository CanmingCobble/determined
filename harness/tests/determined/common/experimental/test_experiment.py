from typing import Callable

import pytest
import responses

from determined.common import api
from determined.common.api import bindings
from determined.common.experimental import experiment
from tests.common import api_server

_MASTER = "http://localhost:8080"


@pytest.fixture
def standard_session() -> api.Session:
    return api.Session(master=_MASTER, user=None, auth=None, cert=None)


@pytest.fixture
def make_expref(standard_session: api.Session) -> Callable[[int], experiment.ExperimentReference]:
    def _make_expref(exp_id: int) -> experiment.ExperimentReference:
        return experiment.ExperimentReference(exp_id, standard_session)

    return _make_expref


@responses.activate(registry=responses.registries.OrderedRegistry)
def test_wait_retries_transient_504(
    make_expref: Callable[[int], experiment.ExperimentReference]
) -> None:
    expref = make_expref(1)

    exp_resp = api_server.sample_get_experiment(
        id=expref.id, state=bindings.experimentv1State.COMPLETED
    )

    responses.get(f"{_MASTER}/api/v1/experiments/{expref.id}", status=504)
    responses.get(f"{_MASTER}/api/v1/experiments/{expref.id}", status=504)
    responses.get(f"{_MASTER}/api/v1/experiments/{expref.id}", status=200, json=exp_resp.to_json())

    expref.wait(interval=0.01)
    assert len(responses.calls) > 2  # 2 504s and 1 200


@pytest.mark.parametrize(
    "terminal_state",
    [
        bindings.experimentv1State.CANCELED,
        bindings.experimentv1State.COMPLETED,
        bindings.experimentv1State.DELETED,
        bindings.experimentv1State.ERROR,
    ],
)
@responses.activate(registry=responses.registries.OrderedRegistry)
def test_wait_waits_until_terminal_state(
    make_expref: Callable[[int], experiment.ExperimentReference],
    terminal_state: bindings.experimentv1State,
) -> None:
    expref = make_expref(1)

    exp_resp_running = api_server.sample_get_experiment(
        id=expref.id, state=bindings.experimentv1State.RUNNING
    )
    exp_resp_terminal = api_server.sample_get_experiment(id=expref.id, state=terminal_state)

    responses.get(f"{_MASTER}/api/v1/experiments/{expref.id}", json=exp_resp_running.to_json())
    responses.get(f"{_MASTER}/api/v1/experiments/{expref.id}", json=exp_resp_running.to_json())
    responses.get(f"{_MASTER}/api/v1/experiments/{expref.id}", json=exp_resp_terminal.to_json())

    expref.wait(interval=0.01)

    # Register an extra response so the mock can keep serving the experiment
    #   (necessary for the `expref._get().state` call below)
    responses.get(f"{_MASTER}/api/v1/experiments/{expref.id}", json=exp_resp_terminal.to_json())
    assert expref._get().state == terminal_state


@responses.activate
def test_wait_raises_exception_when_experiment_is_paused(
    make_expref: Callable[[int], experiment.ExperimentReference]
) -> None:
    expref = make_expref(1)

    exp_resp = api_server.sample_get_experiment(
        id=expref.id, state=bindings.experimentv1State.PAUSED
    )

    responses.get(f"{_MASTER}/api/v1/experiments/{expref.id}", json=exp_resp.to_json())

    with pytest.raises(ValueError):
        expref.wait()
