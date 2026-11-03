import inspect
import json
import os
import time
from unittest.mock import MagicMock

import pytest

from ivoryos.models import Script
from ivoryos.runtime.safety import guard
from ivoryos.script import ScriptEditor
from tests.conftest import session_draft_id
from ivoryos.services.draft_service import post_script_for_user
from tests.unit.test_runner_missing_method import _execute, _step

FLOAT_LIMIT = {"target": "dummy", "method": "float_method", "param": "arg", "min": 0, "max": 10, "unit": "mL"}


@pytest.fixture
def limits(tmp_path):
    """Point the guard at a file of this test's own, and back afterwards."""
    original = guard.path
    path = tmp_path / "safety.json"
    guard.configure(str(path))

    def write(entries, **extra):
        path.write_text(json.dumps({"format": "ivoryos-safety/1", "limits": entries, **extra}))
        os.utime(path, (time.time() + 1, time.time() + 1))

    write.path = path
    yield write
    guard.configure(original)


def test_a_run_step_past_a_limit_is_refused_at_the_call(app, init_database, test_deck, limits):
    limits([FLOAT_LIMIT])

    events, row = _execute(app, _step("float_method", {"arg": 20.0}, {"arg": "float"}))

    assert row.run_error is True
    [error] = [payload["message"] for name, payload in events if name == "error"]
    assert error == "Safety guard: dummy.float_method: arg = 20 is above the maximum of 10 mL."

    _, row = _execute(app, _step("float_method", {"arg": 5.0}, {"arg": "float"}))
    assert row.run_error is False


def test_the_instruments_page_refuses_a_call_past_a_limit(auth, test_deck, limits):
    limits([FLOAT_LIMIT])

    # numbers, as the downloaded proxy sends them; enum_method's Enum field shares the name `arg`
    refused = auth.post('/ivoryos/instruments/deck.dummy', json={"hidden_name": "float_method", "arg": 20}).get_json()
    allowed = auth.post('/ivoryos/instruments/deck.dummy', json={"hidden_name": "float_method", "arg": 5}).get_json()

    assert refused["success"] is False and refused["output"].startswith("Safety guard: dummy.float_method: arg = 20")
    assert allowed["success"] is True


def draft_with(auth, args):
    script = Script(author='testuser')
    ScriptEditor(script).add_action({'instrument': 'deck.dummy', 'action': 'float_method',
                                     'args': args, 'return': '', 'arg_types': {'arg': 'float'}})
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))


def test_a_workflow_past_a_limit_is_not_started(auth, test_deck, limits, monkeypatch):
    from ivoryos.routes.execute import execute as execute_module

    limits([FLOAT_LIMIT])
    run_script = MagicMock(return_value='queued')
    monkeypatch.setattr(execute_module.runner, 'run_script', run_script)

    # a value written into a step
    draft_with(auth, {'arg': 20.0})
    body = auth.post('/ivoryos/executions/config', data={'repeat': '1', 'batch_size': '1'},
                     follow_redirects=True).get_data(as_text=True)
    assert "Nothing was started" in body and "Step 1, dummy.float_method: arg = 20 is above the maximum of 10 mL." in body

    # a config table column passed to that step, its header showing the limit
    draft_with(auth, {'arg': '#volume'})
    page = auth.get('/ivoryos/executions/config').get_data(as_text=True)
    assert 'mL · 0 to 10' in page
    form = {'online-config': '', 'batch_size': '1', 'volume[1]': '5', 'volume[2]': '20'}
    body = auth.post('/ivoryos/executions/config', data=form, follow_redirects=True).get_data(as_text=True)
    assert "Row 2, &#39;volume&#39;: 20 is above the maximum of 10 mL." in body

    run_script.assert_not_called()


def test_a_run_that_leaves_an_input_unset_is_not_started(auth, test_deck, monkeypatch):
    from ivoryos.routes.execute import execute as execute_module
    from ivoryos.runtime.state import global_state

    started = []

    def run_script(**kwargs):
        started.append(kwargs)
        global_state.runner_status = {"id": 1}  # what the JSON route waits for
        return 'queued'

    monkeypatch.setattr(execute_module.runner, 'run_script', run_script)
    monkeypatch.setattr(global_state, 'runner_status', None)
    # `#volume` is set by no step, so only the run can give it
    draft_with(auth, {'arg': '#volume'})
    json_headers = {"Accept": "application/json"}

    body = auth.post('/ivoryos/executions/config', data={'repeat': '1', 'batch_size': '1'},
                     follow_redirects=True).get_data(as_text=True)
    assert "&#39;volume&#39; has no value: no step in the workflow sets it" in body
    refused = auth.post('/ivoryos/executions/config', json={'repeat': 1}, headers=json_headers)
    assert refused.status_code == 400
    refused = auth.post('/ivoryos/executions/config', json={'kwargs': [{'volume': 1}, {'other': 1}]},
                        headers=json_headers)
    assert refused.get_json()['problems'] == ["Row 2, 'volume': No value."]
    refused = auth.post('/ivoryos/executions/campaign', json={'parameters': [], 'objectives': []},
                        headers=json_headers)
    assert refused.status_code == 400
    assert not started

    assert auth.post('/ivoryos/executions/config', json={'kwargs': [{'volume': 5}]},
                     headers=json_headers).status_code == 200
    assert started


def test_the_designer_shows_a_fields_unit_and_range(auth, test_deck, limits):
    limits([FLOAT_LIMIT])

    html = auth.get('/ivoryos/draft/instruments/deck.dummy').get_json()['html']

    # under the field, in the field column of the toolbox grid, and named as a limit
    assert 'class="form-text field-limit" title="Safety limit: mL · 0 to 10">mL · 0 to 10</div>' in html


def test_an_instrument_form_shows_each_fields_limit(app):
    from ivoryos.forms.dynamic_forms import create_form_for_method

    def dispense(self, volume: float, speed: float = 1.0):
        return volume

    with app.test_request_context():
        form = create_form_for_method(inspect.signature(dispense), autofill=False, design=False,
                                      limits={"volume": {"max": 10, "unit": "µL"}})()

    assert form.volume.description == "µL · at most 10"
    assert form.speed.description == ""


def shields(page):
    """``{(method, field): shield button}`` on an Instruments page."""
    import re
    return {(m.group(1), m.group(2)): m.group(0) for m in re.finditer(
        r'<button type="button" class="input-group-text guard-shield[^>]*data-method="([^"]+)" data-param="([^"]+)".*?</button>',
        page, re.S)}


def test_a_fields_shield_sets_its_limit(auth, test_deck, limits):
    page = auth.get('/ivoryos/instruments/deck.dummy').get_data(as_text=True)
    assert 'Add a safety limit' in shields(page)[('float_method', 'arg')]
    # an Enum already fixes its choices, so its field has no shield
    assert ('enum_method', 'arg') not in shields(page)

    url = '/ivoryos/instruments/deck.dummy/limits'
    refused = auth.post(url, json={'method': 'float_method', 'param': 'arg', 'limit': {'min': 20, 'max': 10}})
    assert refused.status_code == 400
    assert refused.get_json()['errors'][0]['param'] == 'arg' and not limits.path.exists()

    saved = auth.post(url, json={'method': 'float_method', 'param': 'arg', 'limit': {'min': 0, 'max': 10, 'unit': 'mL'}})
    assert saved.get_json() == {'limit': {'min': 0, 'max': 10, 'unit': 'mL'}, 'hint': 'mL · 0 to 10'}
    assert json.loads(limits.path.read_text())['limits'] == [FLOAT_LIMIT]

    shield = shields(auth.get('/ivoryos/instruments/deck.dummy').get_data(as_text=True))[('float_method', 'arg')]
    assert 'is-set' in shield and 'mL · 0 to 10' in shield


def test_building_blocks_have_no_limits(auth, test_deck):
    assert auth.post('/ivoryos/instruments/blocks.anything/limits', json={}).status_code == 404
