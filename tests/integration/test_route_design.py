import re
import io

import pytest
from flask import g
from itsdangerous import URLSafeTimedSerializer

from ivoryos.models import Script, db
from ivoryos.runtime.state import global_state
from ivoryos.script import ScriptEditor
from tests.conftest import session_draft_id
from ivoryos.services import draft_service
from ivoryos.services.draft_service import get_script_for_user, post_script_for_user


def test_design_page_loads_for_auth_user(auth):
    """
    GIVEN an authenticated user
    WHEN the design page is accessed
    THEN the page should load successfully
    """
    response = auth.get('/ivoryos/draft/instruments', follow_redirects=True)
    assert response.status_code == 200


def test_clear_canvas(auth):
    """
    Tests clearing the design canvas (deleting the current draft).
    """
    response = auth.delete('/ivoryos/draft', follow_redirects=True)
    assert response.status_code == 200


def test_experiment_campaign_page(auth):
    """
    Tests the experiment campaign/run page.
    """
    response = auth.get('/ivoryos/executions/queue', follow_redirects=True)
    assert response.status_code == 200


def test_draft_instruments_list(auth):
    """
    Tests the design instruments list endpoint.
    """
    response = auth.get('/ivoryos/draft/instruments', follow_redirects=True)
    assert response.status_code == 200


def test_code_preview(auth):
    """
    Tests the code preview endpoint.
    """
    response = auth.get('/ivoryos/draft/code_preview', follow_redirects=True)
    assert response.status_code == 200
    assert "code" in response.get_json()


def test_update_ui_state_show_code_and_invalid_request(auth):
    response = auth.patch('/ivoryos/draft/ui-state', json={'show_code': True})

    assert response.status_code == 200
    assert response.get_json() == {'success': True}
    with auth.session_transaction() as session:
        assert session['show_code'] is True

    invalid = auth.patch('/ivoryos/draft/ui-state', json={'unknown': True})
    assert invalid.status_code == 400
    assert invalid.get_json() == {'error': 'Invalid request'}


def test_get_available_variables_reads_current_user_draft(auth):
    script = Script(author='testuser')
    ScriptEditor(script).add_variable('5', 'sample_count', 'int')
    ScriptEditor(script).add_action({
        'instrument': 'deck.sensor',
        'action': 'read',
        'args': {},
        'return': 'measurement',
        'arg_types': {},
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    response = auth.get('/ivoryos/draft/variables')

    assert response.status_code == 200
    assert set(response.get_json()['variables']) >= {'sample_count', 'measurement'}


def test_reorder_steps_updates_current_draft_order(auth):
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'comment',
        'action': 'comment',
        'args': {'statement': 'first'},
        'return': '',
        'arg_types': {'statement': 'str'},
    })
    ScriptEditor(script).add_action({
        'instrument': 'comment',
        'action': 'comment',
        'args': {'statement': 'second'},
        'return': '',
        'arg_types': {'statement': 'str'},
    })
    ScriptEditor(script).add_action({
        'instrument': 'comment',
        'action': 'comment',
        'args': {'statement': 'third'},
        'return': '',
        'arg_types': {'statement': 'str'},
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    response = auth.post('/ivoryos/draft/steps/order', data={'order': '3,1,2'})

    assert response.status_code == 200
    with auth.application.app_context():
        draft = get_script_for_user('testuser', session_draft_id(auth))
    assert [action['args']['statement'] for action in draft.script_dict['script']] == ['third', 'first', 'second']
    assert [action['id'] for action in draft.script_dict['script']] == [1, 2, 3]


def test_import_python_file_reports_missing_or_empty_upload(auth):
    no_file = auth.post('/ivoryos/draft/import_python_file', data={})
    assert no_file.status_code == 200
    assert no_file.get_json() == {'success': False, 'error': 'No file part'}

    no_functions = auth.post(
        '/ivoryos/draft/import_python_file',
        data={'file': (io.BytesIO(b'x = 1\n'), 'workflow.py')},
        content_type='multipart/form-data',
    )
    assert no_functions.status_code == 200
    assert no_functions.get_json() == {'success': False, 'error': 'No functions found in file'}


def test_confirm_import_python_creates_workflow_script(auth):
    payload = {
        'workflows': {
            'imported_workflow': {
                'cards': [{
                    'id': 1,
                    'uuid': 1,
                    'instrument': 'comment',
                    'action': 'comment',
                    'args': {'statement': 'hello'},
                    'return': '',
                    'arg_types': {'statement': 'str'},
                }],
                'source': 'def imported_workflow():\n    pass\n',
            }
        },
        'overwrite': [],
    }

    response = auth.post('/ivoryos/draft/confirm_import_python', json=payload)

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'results': {'imported_workflow': 'created'},
    }
    with auth.application.app_context():
        saved = db.session.get(Script, 'imported_workflow')
        assert saved is not None
        assert saved.author == 'testuser'
        assert saved.script_dict['script'][0]['action'] == 'comment'


def test_canvas_flags_a_step_the_deck_no_longer_offers(auth, test_deck):
    """
    GIVEN a draft built against a deck method that has since disappeared
    WHEN the design canvas is rendered
    THEN the step carries a warning and the canvas says how many steps are affected
    """
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy',
        'action': 'int_method',
        'args': {'arg': 1},
        'return': '',
        'arg_types': {'arg': 'int'},
    })
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy',
        'action': 'method_that_was_deleted',
        'args': {},
        'return': '',
        'arg_types': {},
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    response = auth.post('/ivoryos/draft/steps/order', data={'order': '1,2'})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '1 step' in body and 'no longer match' in body
    # one marker slot per step, but only the stale one carries a reason
    assert body.count('step-issue-marker') == 2
    assert body.count('data-bs-toggle="tooltip"') == 1
    assert "Method &#39;method_that_was_deleted&#39; no longer exists" in body


def test_clean_steps_keep_an_invisible_marker_slot_so_labels_stay_aligned(auth, test_deck):
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy',
        'action': 'int_method',
        'args': {'arg': 1},
        'return': '',
        'arg_types': {'arg': 'int'},
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    body = auth.post('/ivoryos/draft/steps/order', data={'order': '1'}).get_data(as_text=True)

    assert 'step-issue-marker me-1 invisible' in body


def test_canvas_has_no_warnings_when_every_step_matches_the_deck(auth, test_deck):
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy',
        'action': 'int_method',
        'args': {'arg': 1},
        'return': '',
        'arg_types': {'arg': 'int'},
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    response = auth.post('/ivoryos/draft/steps/order', data={'order': '1'})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'deck-compatibility-banner' not in body
    assert 'data-bs-toggle="tooltip"' not in body


def test_the_designer_still_shows_the_draft_after_a_server_restart(auth, test_deck):
    """Restarting the server must not clear the canvas: the browser never logged out."""
    script = Script(author='testuser', deck='test_deck')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy',
        'action': 'int_method',
        'args': {'arg': 1},
        'return': '',
        'arg_types': {'arg': 'int'},
    })
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    draft_service._drafts.clear()  # the process restarted; the browser cookie is the same

    response = auth.get('/ivoryos/draft')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'int_method' in body


def test_step_edit_form_explains_why_the_step_no_longer_matches(auth, test_deck):
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy',
        'action': 'int_method',
        'args': {'arg': 1, 'dropped_arg': 2},
        'return': '',
        'arg_types': {'arg': 'int', 'dropped_arg': 'int'},
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))
        uuid = get_script_for_user('testuser', session_draft_id(auth)).script_dict['script'][0]['uuid']

    response = auth.get(f'/ivoryos/draft/steps/{uuid}')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Step will fail' in body
    assert 'no longer takes &#39;dropped_arg&#39;' in body


def test_a_deck_name_alone_is_not_flagged(auth, test_deck):
    """Only the steps say whether a workflow fits: a deck keeps its name when its methods change."""
    from ivoryos.runtime.state import global_state

    # the fixture's stand-in deck carries no module name of its own
    global_state._deck.__name__ = 'current_deck'
    try:
        script = Script(author='testuser', deck='deck_it_was_designed_for')
        ScriptEditor(script).add_action({
            'instrument': 'deck.dummy',
            'action': 'int_method',
            'args': {'arg': 1},
            'return': '',
            'arg_types': {'arg': 'int'},
        })

        with auth.application.app_context():
            post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

        response = auth.post('/ivoryos/draft/steps/order', data={'order': '1'})
        body = response.get_data(as_text=True)
    finally:
        del global_state._deck.__name__

    assert response.status_code == 200
    assert 'deck-compatibility-banner' not in body


def test_execution_config_page_renders(auth, test_deck):
    """
    GIVEN a draft built against the loaded deck
    WHEN the execution config page is requested
    THEN it renders (it no longer receives the long-unused design_buttons context)
    """
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy',
        'action': 'int_method',
        'args': {'arg': 1},
        'return': '',
        'arg_types': {'arg': 'int'},
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    response = auth.get('/ivoryos/executions/config', follow_redirects=True)

    assert response.status_code == 200
    assert 'design_buttons' not in response.get_data(as_text=True)


def test_execution_page_warns_about_steps_that_will_fail(auth, test_deck):
    """
    GIVEN a draft with a step whose deck method is gone, and one that is disabled
    WHEN the execution config page is opened
    THEN it names the failing step and ignores the disabled one, which never runs
    """
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'method_that_was_deleted',
        'args': {}, 'return': '', 'arg_types': {},
    })
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'also_deleted',
        'args': {}, 'return': '', 'arg_types': {}, 'disabled': True,
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    body = auth.get('/ivoryos/executions/config', follow_redirects=True).get_data(as_text=True)

    assert 'run-compatibility-warning' in body
    assert '1 step will fail against the current deck' in body
    # the warning lists steps as <code>module.method</code>; the disabled one is
    # absent from that list, though it still shows in the compiled code preview
    assert '<code>dummy.method_that_was_deleted</code>' in body
    assert '<code>dummy.also_deleted</code>' not in body
    # the list is one compact line per step; the full sentence is the hover title
    assert 'missing method method_that_was_deleted' in body
    assert 'Fix these in the workflow designer' not in body


def test_execution_page_is_quiet_when_the_workflow_matches_the_deck(auth, test_deck):
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'int_method',
        'args': {'arg': 1}, 'return': '', 'arg_types': {'arg': 'int'},
    })

    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    body = auth.get('/ivoryos/executions/config', follow_redirects=True).get_data(as_text=True)

    assert 'run-compatibility-warning' not in body


def test_run_names_skip_queued_tasks_not_yet_in_the_database(app, init_database, monkeypatch):
    """
    GIVEN one finished run named 'flow' and another task already queued as 'flow_1'
    WHEN a name is picked for the next task
    THEN it skips both, rather than reusing the queued task's name
    """
    from datetime import datetime

    from ivoryos.models import WorkflowRun
    from ivoryos.routes.execute import execute as execute_module

    monkeypatch.setattr(execute_module.runner, "execution_queue", [{"run_name": "flow_1"}])
    monkeypatch.setattr(execute_module.runner, "current_task", None)

    with app.app_context():
        db.session.add(WorkflowRun(name='flow', platform='deck', start_time=datetime.now()))
        db.session.commit()

        assert execute_module._unique_run_name('flow') == 'flow_2'


def test_queued_task_conditions_can_be_read_and_edited(auth, monkeypatch):
    """
    GIVEN a config task waiting in the queue
    WHEN its conditions are read, then edited with a bad and a good value
    THEN the bad edit is refused with a reason and the good one is applied
    """
    from ivoryos.routes.execute import execute as execute_module

    script = Script(author='testuser')
    script.script_dict['script'] = [{
        'id': 1, 'uuid': 1, 'instrument': 'deck.reactor', 'action': 'run',
        'args': {'temperature': '#temperature'}, 'return': '', 'arg_types': {'temperature': 'float'},
    }]
    task = {'uid': 'abc', 'script': script, 'run_name': 'flow', 'repeat_count': None,
            'batch_size': 1, 'compiled': False, 'config': [{'temperature': '25'}]}
    monkeypatch.setattr(execute_module.runner, 'execution_queue', [task])
    monkeypatch.setattr(execute_module.runner, 'socketio', None)
    url = '/ivoryos/executions/queue/task/abc/conditions'

    assert auth.get(url).get_json()['rows'] == [['25']]

    refused = auth.post(url, json={'config': [{'temperature': 'hot'}]})
    assert refused.status_code == 400
    assert 'Entry 1' in refused.get_json()['error']
    assert task['config'] == [{'temperature': '25'}]

    assert auth.post(url, json={'config': [{'temperature': '30'}, {'temperature': '35'}]}).status_code == 200
    assert task['config'] == [{'temperature': '30'}, {'temperature': '35'}]

    assert auth.get('/ivoryos/executions/queue/task/gone/conditions').status_code == 404
    assert auth.post('/ivoryos/executions/queue/task/gone/conditions', json={}).status_code == 404


def test_renaming_a_queued_task_keeps_run_names_unique(auth, monkeypatch):
    """
    GIVEN two queued tasks, 'flow' and 'other'
    WHEN 'other' is renamed to 'flow', and then to 'flow 1', which cleans up to its own name
    THEN it becomes 'flow_1', and stays 'flow_1' rather than clashing with itself
    """
    from ivoryos.routes.execute import execute as execute_module

    first = {'uid': 'a', 'script': Script(author='testuser'), 'run_name': 'flow', 'repeat_count': 2, 'config': None}
    second = {'uid': 'b', 'script': Script(author='testuser'), 'run_name': 'other', 'repeat_count': 2,
              'config': None, 'display_name': 'Other'}
    monkeypatch.setattr(execute_module.runner, 'execution_queue', [first, second])
    monkeypatch.setattr(execute_module.runner, 'current_task', None)
    monkeypatch.setattr(execute_module.runner, 'socketio', None)
    url = '/ivoryos/executions/queue/task/b/conditions'

    assert auth.post(url, json={'name': 'flow'}).status_code == 200
    assert (second['run_name'], second['display_name']) == ('flow_1', None)

    assert auth.post(url, json={'name': 'flow 1'}).status_code == 200
    assert second['run_name'] == 'flow_1'


def test_the_toolbox_lists_flow_control_instruments_and_workflows(auth, test_deck):
    with auth.application.app_context():
        post_script_for_user('testuser', Script(author='testuser', deck='test_deck'), draft_id=session_draft_id(auth))

    page = auth.get('/ivoryos/draft').get_data(as_text=True)

    # each group sits under a divider and loads its actions from here when first shown
    assert 'data-url="/ivoryos/draft/instruments/flow_control"' in page
    assert 'data-url="/ivoryos/draft/instruments/deck.dummy"' in page
    assert 'data-url="/ivoryos/draft/instruments/workflows"' in page
    # flow control starts folded; the instruments and the workflows start open
    assert 'id="toolbox-flow_control" class="toolbox-group-body" hidden' in page
    assert 'id="toolbox-deck-dummy" class="toolbox-group-body">' in page
    assert 'id="toolbox-workflows" class="toolbox-group-body">' in page
    assert page.index('>Flow control<') < page.index('>Dummy<') < page.index('>Workflows<')
    # the groups are dividers, folded by a plain toggle rather than Bootstrap's collapse
    toolbox = auth.get('/ivoryos/draft/instruments').get_json()['html']
    assert 'class="toolbox-divider"' in toolbox
    assert 'accordion' not in toolbox and 'data-bs-toggle' not in toolbox
    # a step is edited in a pop-up, not in the toolbox
    assert 'id="editStepModal"' in page


def test_the_toolbox_has_one_search_box_and_a_count_on_each_divider(auth, test_deck):
    with auth.application.app_context():
        post_script_for_user('testuser', Script(author='testuser', deck='test_deck'), draft_id=session_draft_id(auth))

    page = auth.get('/ivoryos/draft').get_data(as_text=True)

    # one control at the top: a search across every group, the auto fill toggle and the fold-all toggle
    assert 'class="input-group input-group-sm"' in page
    assert 'class="form-control toolbox-search"' in page
    assert 'toolbox-autofill"' in page and 'id="autoFillToggle" aria-pressed="false"' in page
    assert 'class="btn toolbox-tool-toggle toolbox-fold-all"' in page
    # the groups scroll on their own under that row
    assert 'class="toolbox-groups"' in page and page.index('toolbox-tools') < page.index('toolbox-groups')
    assert 'form-check-input" type="checkbox" id="autoFillCheck"' not in page
    # each divider names its group, for the browser to remember its fold, and shows its size
    assert 'data-group="deck.dummy"' in page and 'class="toolbox-count"' in page
    assert 'data-deck="test_deck"' in page
    # a group no longer has a search box of its own
    html = auth.get('/ivoryos/draft/instruments/deck.dummy').get_json()['html']
    assert 'action-search' not in html


def test_a_busy_deck_starts_with_only_the_instruments_that_fit_open(auth, test_deck):
    """Instruments open from the top while their methods fit a screen; the rest start folded."""
    methods = lambda n: {f"method_{i}": {} for i in range(n)}
    global_state._interface_schema = {"deck.a": methods(5), "deck.b": methods(5), "deck.c": methods(5)}
    with auth.application.app_context():
        post_script_for_user('testuser', Script(author='testuser', deck='test_deck'), draft_id=session_draft_id(auth))

    page = auth.get('/ivoryos/draft').get_data(as_text=True)

    assert 'id="toolbox-deck-a" class="toolbox-group-body">' in page
    assert 'id="toolbox-deck-b" class="toolbox-group-body">' in page
    assert 'id="toolbox-deck-c" class="toolbox-group-body" hidden' in page
    # the budget is about instruments: the workflows still start open
    assert 'id="toolbox-workflows" class="toolbox-group-body">' in page


def test_a_toolbox_group_holds_only_its_actions(auth, test_deck):
    html = auth.get('/ivoryos/draft/instruments/deck.dummy').get_json()['html']

    # no way back to step out of, and ids that cannot clash with another open group
    assert 'bi-arrow-return-left' not in html
    assert 'id="actions-deck-dummy"' in html
    assert 'aria-controls="actions-deck-dummy-1"' in html and 'id="actions-deck-dummy-1"' in html
    # each action is a row whose form opens under it, not an accordion item
    assert 'class="toolbox-action"' in html and 'accordion' not in html
    # an Enum field's choices are named after its action, not just its field
    assert 'list="actions-deck-dummy-' in html and 'list="arg_options"' not in html


def test_a_flow_control_field_explains_itself_in_its_placeholder_not_as_a_limit(auth, test_deck):
    html = auth.get('/ivoryos/draft/instruments/flow_control').get_json()['html']

    # a short example in the box, no note under it
    assert 'placeholder="1, True, &#34;text&#34;"' in html or 'placeholder="1, True, &quot;text&quot;"' in html
    assert 'placeholder="x * 2 + 1"' in html and 'placeholder="x &gt; 5"' in html
    assert 'field-help' not in html
    # the type select has a label that fits the narrow label column
    assert 'Select Value Type' not in html and 'Select Input Type' not in html
    assert '<label class="input-group-text">Type' in html
    # help text is not a safety limit, and never sits inside the label-and-field row
    assert 'Safety limit' not in html
    assert 'input-group-text small text-muted' not in html


def test_auto_fill_is_one_setting_for_the_toolbox(auth, test_deck):
    assert auth.patch('/ivoryos/draft/ui-state', json={'autofill': True}).get_json() == {'success': True}

    html = auth.get('/ivoryos/draft/instruments/deck.dummy').get_json()['html']
    assert 'value="#arg"' in html
    # and its toggle on the toolbox comes back lit
    with auth.application.app_context():
        post_script_for_user('testuser', Script(author='testuser', deck='test_deck'), draft_id=session_draft_id(auth))
    page = auth.get('/ivoryos/draft').get_data(as_text=True)
    assert 'toolbox-autofill active"' in page and 'id="autoFillToggle" aria-pressed="true"' in page


def test_a_step_opens_in_a_pop_up_with_save_and_cancel(auth, test_deck):
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'int_method',
        'args': {'arg': 1}, 'return': '', 'arg_types': {'arg': 'int'},
    })
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))
        uuid = get_script_for_user('testuser', session_draft_id(auth)).script_dict['script'][0]['uuid']

    body = auth.get(f'/ivoryos/draft/steps/{uuid}').get_data(as_text=True)

    assert 'class="modal-header"' in body and 'id="editStepTitle"' in body
    assert 'form="edit-step-form"' in body and 'data-bs-dismiss="modal">Cancel' in body
    assert 'id="back"' not in body
    # the step's own variables, apart from the toolbox's
    assert 'list="step_variables"' in body


def test_running_config_table_can_be_read_and_edited(auth, monkeypatch):
    """
    GIVEN a config run in progress, with its first row running
    WHEN its table is read, then edited with a bad and a good value
    THEN the bad edit is refused, the good one applied, and another task's uid is turned away
    """
    from ivoryos.routes.execute import execute as execute_module
    from ivoryos.runtime.live_config import LiveConfig

    url = '/ivoryos/executions/current_task/config'
    monkeypatch.setattr(execute_module.runner, 'live_config', None)
    assert auth.get(url).status_code == 404

    live = LiveConfig([{'temperature': '25'}, {'temperature': '40'}], {'temperature': 'float'})
    live.start_batch(1)
    monkeypatch.setattr(execute_module.runner, 'live_config', live)
    monkeypatch.setattr(execute_module.runner, 'current_task', {'uid': 'abc', 'run_name': 'flow', 'batch_size': 1})

    table = auth.get(url).get_json()
    assert [(row['status'], row['values']) for row in table['rows']] == [('running', ['25']), ('pending', ['40'])]
    rows = [{'id': row['id'], 'values': {'temperature': row['values'][0]}, 'number': n}
            for n, row in enumerate(table['rows'], start=1)]

    rows[1]['values'] = {'temperature': 'warm'}
    refused = auth.post(url, json={'uid': 'abc', 'rows': rows})
    assert refused.status_code == 400 and 'Row 2' in refused.get_json()['error']

    rows[1]['values'] = {'temperature': '45'}
    saved = auth.post(url, json={'uid': 'abc', 'rows': rows + [{'id': None, 'values': {'temperature': '60'}, 'number': 3}]})
    assert saved.get_json() == {'status': 'ok', 'notes': []}
    assert [row['values'] for row in auth.get(url).get_json()['rows']] == [['25'], ['45'], ['60']]

    assert auth.post(url, json={'uid': 'other', 'rows': rows}).status_code == 404


def test_the_run_page_starts_with_the_right_button_and_never_asks_on_load(auth, test_deck, monkeypatch):
    """The button over the progress panel is a pencil only while a config table runs, and
    the page renders it so, rather than asking the running-table endpoint when it loads."""
    from ivoryos.routes.execute import execute as execute_module
    from ivoryos.runtime.live_config import LiveConfig

    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'float_method',
        'args': {'arg': '#temperature'}, 'return': '', 'arg_types': {'arg': 'float'},
    })
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    monkeypatch.setattr(execute_module.runner, 'live_config', None)
    page = auth.get('/ivoryos/executions/config').get_data(as_text=True)
    assert 'data-editable="false"' in page and 'bi-info-circle' in page

    monkeypatch.setattr(execute_module.runner, 'live_config', LiveConfig([{'temperature': '25'}], {'temperature': 'float'}))
    page = auth.get('/ivoryos/executions/config').get_data(as_text=True)
    assert 'data-editable="true"' in page and 'bi-pencil-square' in page


def test_an_edit_to_the_running_table_moves_every_pages_total(auth, monkeypatch):
    from unittest.mock import MagicMock
    from ivoryos.routes.execute import execute as execute_module
    from ivoryos.runtime.live_config import LiveConfig
    from ivoryos.runtime.run_progress import RunProgress

    runner = execute_module.runner
    live = LiveConfig([{'temperature': '25'}, {'temperature': '40'}], {'temperature': 'float'})
    live.start_batch(1)
    progress = RunProgress()
    progress.start('abc', 'flow', Script(author='testuser'), iterations=2)
    progress.follow_table(live)
    progress.start_iteration(1)
    socketio = MagicMock()
    monkeypatch.setattr(runner, 'live_config', live)
    monkeypatch.setattr(runner, 'current_task', {'uid': 'abc', 'run_name': 'flow', 'batch_size': 1})
    monkeypatch.setattr(runner, 'progress', progress)
    monkeypatch.setattr(runner, 'socketio', socketio)

    table = auth.get('/ivoryos/executions/current_task/config').get_json()
    rows = [{'id': row['id'], 'values': {'temperature': row['values'][0]}, 'number': n}
            for n, row in enumerate(table['rows'], start=1)]
    auth.post('/ivoryos/executions/current_task/config',
              json={'uid': 'abc', 'rows': rows + [{'id': None, 'values': {'temperature': '60'}, 'number': 3}]})

    [sent] = [call.args[1] for call in socketio.emit.call_args_list if call.args[0] == 'progress']
    assert sent['iterations'] == 3 and sent['table']['total'] == 3


def test_a_config_row_can_leave_an_optional_input_empty(auth, test_deck, monkeypatch):
    """
    GIVEN a workflow whose second input is passed to an Optional argument
    WHEN a config row leaves that cell empty, and another types None into the required one
    THEN both rows run, with None for those values; a row left entirely empty is skipped
    """
    from unittest.mock import MagicMock
    from ivoryos.routes.execute import execute as execute_module

    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'float_method',
        'args': {'arg': '#temperature'}, 'return': '', 'arg_types': {'arg': 'float'},
    })
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'str_method',
        'args': {'arg': '#note'}, 'return': '', 'arg_types': {'arg': ['str', 'NoneType']},
    })
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))
    run_script = MagicMock(return_value='queued')
    monkeypatch.setattr(execute_module.runner, 'run_script', run_script)

    page = auth.get('/ivoryos/executions/config').get_data(as_text=True)
    assert 'var configOptional = ["note"];' in page
    # headers stay on one line: the required input is starred, the optional one is not
    assert 'title="Required">temperature<span class="text-danger ms-1" aria-label="required">*</span>' in page
    assert re.search(r'title="Optional: left empty in a filled row, it runs as None">note\s*</th>', page)
    assert 'id="configTableKey"' in page and '>optional</div>' not in page

    form = {'online-config': '', 'batch_size': '1',
            'temperature[1]': '25', 'note[1]': '',
            'temperature[2]': 'None', 'note[2]': 'stirred',
            'temperature[3]': '', 'note[3]': ''}
    auth.post('/ivoryos/executions/config', data=form, follow_redirects=True)

    assert run_script.call_args.kwargs['config'] == [{'temperature': '25', 'note': ''},
                                                     {'temperature': 'None', 'note': 'stirred'}]

    # the required input still needs a value: an empty one holds the run back
    run_script.reset_mock()
    form['temperature[2]'] = ''
    body = auth.post('/ivoryos/executions/config', data=form, follow_redirects=True).get_data(as_text=True)
    run_script.assert_not_called()
    assert "Row 2, &#39;temperature&#39;: No value." in body


def test_a_table_of_one_optional_input_runs_the_rows_given_none_on_purpose(auth, test_deck, monkeypatch):
    """
    GIVEN a workflow whose only input is optional
    WHEN rows are left empty, and one is given None on purpose
    THEN only that row runs: an empty row is not a None, it is skipped
    """
    from unittest.mock import MagicMock
    from ivoryos.routes.execute import execute as execute_module

    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'str_method',
        'args': {'arg': '#note'}, 'return': '', 'arg_types': {'arg': ['str', 'NoneType']},
    })
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))
    run_script = MagicMock(return_value='queued')
    monkeypatch.setattr(execute_module.runner, 'run_script', run_script)

    page = auth.get('/ivoryos/executions/config').get_data(as_text=True)
    # nothing to star when no input is required
    assert 'aria-label="required"' not in page

    form = {'online-config': '', 'batch_size': '1',
            'note[1]': '', 'note[2]': 'None', 'note[3]': 'stirred', 'note[4]': ''}
    auth.post('/ivoryos/executions/config', data=form, follow_redirects=True)

    assert run_script.call_args.kwargs['config'] == [{'note': 'None'}, {'note': 'stirred'}]


def test_a_table_of_required_inputs_looks_as_it_did(auth, test_deck):
    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'float_method',
        'args': {'arg': '#temperature'}, 'return': '', 'arg_types': {'arg': 'float'},
    })
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))

    page = auth.get('/ivoryos/executions/config').get_data(as_text=True)

    # every input is required, so nothing is starred and there is no key
    assert 'aria-label="required"' not in page and 'id="configTableKey"' not in page


def test_a_submitted_run_is_tagged_with_the_user_who_submitted_it(auth, test_deck, monkeypatch):
    from unittest.mock import MagicMock
    from ivoryos.routes.execute import execute as execute_module

    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'float_method',
        'args': {'arg': '#temperature'}, 'return': '', 'arg_types': {'arg': 'float'},
    })
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))
    run_script = MagicMock(return_value='queued')
    monkeypatch.setattr(execute_module.runner, 'run_script', run_script)

    auth.post('/ivoryos/executions/config', data={'online-config': '', 'batch_size': '1', 'temperature[1]': '25'},
              follow_redirects=True)

    assert run_script.call_args.kwargs['submitted_by'] == 'testuser'


def test_a_config_table_that_cannot_run_is_not_started(auth, test_deck, monkeypatch):
    """
    GIVEN a workflow with a float input
    WHEN a config table with a value that is not a number is submitted
    THEN nothing is started and the page says which row to fix; once fixed, it runs
    """
    from unittest.mock import MagicMock
    from ivoryos.routes.execute import execute as execute_module

    script = Script(author='testuser')
    ScriptEditor(script).add_action({
        'instrument': 'deck.dummy', 'action': 'float_method',
        'args': {'arg': '#temperature'}, 'return': '', 'arg_types': {'arg': 'float'},
    })
    with auth.application.app_context():
        post_script_for_user('testuser', script, draft_id=session_draft_id(auth))
    run_script = MagicMock(return_value='queued')
    monkeypatch.setattr(execute_module.runner, 'run_script', run_script)

    form = {'online-config': '', 'batch_size': '1', 'temperature[1]': '25', 'temperature[2]': 'hot'}
    body = auth.post('/ivoryos/executions/config', data=form, follow_redirects=True).get_data(as_text=True)

    run_script.assert_not_called()
    assert "Nothing was started" in body and "Row 2, &#39;temperature&#39;" in body

    form['temperature[2]'] = '30'
    auth.post('/ivoryos/executions/config', data=form, follow_redirects=True)
    assert run_script.call_args.kwargs['config'] == [{'temperature': '25'}, {'temperature': '30'}]


def _toolbox_csrf_tokens(html):
    return set(re.findall(r'name="csrf_token"[^>]*value="([^"]+)"', html))


def _session_csrf_tokens(app, tokens):
    """The session's token each signed CSRF token carries. The signature includes the second it
    was made, so two requests a second apart give different tokens for the same session."""
    signer = URLSafeTimedSerializer(app.secret_key, salt="wtf-csrf-token")  # as flask_wtf signs them
    return {signer.loads(token) for token in tokens}


def _as_browser(client, method, url, **kwargs):
    """One request as a browser sends it. The fixtures keep an app context open across the
    test, so ``g`` is cleared by hand here; otherwise it would carry the CSRF token from one
    request to the next, which never happens between real requests."""
    g.pop('csrf_token', None)
    return getattr(client, method)(url, **kwargs)


def test_toolbox_groups_loaded_in_parallel_share_the_session_csrf_token(auth, test_deck, app):
    """
    The designer fetches every toolbox group at once, each from the cookie the page set. The
    page itself must therefore mint the session's CSRF token: otherwise each group would mint
    its own, only the last cookie would survive in the browser, and adding from any other
    group would fail with "The CSRF tokens do not match".
    """
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        with app.app_context():  # a draft that already knows its deck, as a real session has
            post_script_for_user('testuser', Script(author='testuser', deck='test_deck'),
                                 draft_id=session_draft_id(auth), record=False)
        with auth.session_transaction() as sess:
            sess.pop('csrf_token', None)  # a session that has not seen a form yet
        assert _as_browser(auth, 'get', '/ivoryos/draft').status_code == 200
        page_cookie = auth.get_cookie('session').value

        first = _as_browser(auth, 'get', '/ivoryos/draft/instruments/deck.dummy').get_json()['html']
        auth.set_cookie('session', page_cookie)  # the second fetch starts where the first did
        second = _as_browser(auth, 'get', '/ivoryos/draft/instruments/flow_control').get_json()['html']

        tokens = _toolbox_csrf_tokens(first)
        assert len(tokens) == 1
        assert _session_csrf_tokens(app, tokens) == _session_csrf_tokens(app, _toolbox_csrf_tokens(second))

        # the browser kept the second response's cookie; a form from the first still submits
        response = _as_browser(auth, 'post', '/ivoryos/draft/instruments/deck.dummy',
                               data={'hidden_name': 'int_method', 'arg': '5', 'csrf_token': tokens.pop()})
        assert response.get_json()['success'], response.get_json()
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


@pytest.mark.parametrize("variable_type, statement, stored", [
    ("float", "x * 2", "x * 2"),
    ("int", "#x + 1", "#x + 1"),
    ("bool", "x > 2", "x > 2"),
    ("int", "5", 5),
    ("float", "1.5", 1.5),
    ("bool", "True", True),
    ("bool", "no", False),
    ("str", "hello", "hello"),
])
def test_a_variable_keeps_an_expression_and_converts_a_plain_value(auth, test_deck, variable_type, statement, stored):
    # a variable does what a math step did: `x * 2` as a Float was float("x * 2"), an error, and `x > 2` False
    response = auth.post('/ivoryos/draft/instruments/flow_control',
                         data={'builtin_name': 'variable', 'statement': statement, 'variable': 'out',
                               'variable_type': variable_type})
    assert response.get_json()['success'], response.get_json()

    script = get_script_for_user('testuser', draft_id=session_draft_id(auth))
    saved = script.script_dict['script'][-1]['args']['statement']
    assert saved == stored and type(saved) is type(stored)


def test_flow_control_dropped_with_a_blank_statement_still_compiles(auth, test_deck):
    for builtin in ('repeat', 'pause', 'comment'):
        response = auth.post('/ivoryos/draft/instruments/flow_control',
                             data={'builtin_name': builtin, 'statement': ''})
        body = response.get_json()
        assert body['success'] is True and body['error'] == '', body['error']

    script = get_script_for_user('testuser', draft_id=session_draft_id(auth))
    statements = [step['args'].get('statement') for step in script.script_dict['script']]
    assert statements == [1, None, 'Human intervention required', '']
