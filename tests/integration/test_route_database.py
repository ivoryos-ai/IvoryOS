from datetime import datetime

from ivoryos.models import Script, WorkflowRun, WorkflowStep, WorkflowPhase
from ivoryos import db


def create_workflow_run_with_phase(app):
    with app.app_context():
        run = WorkflowRun(
            name='test_workflow',
            platform='test_platform',
            start_time=datetime(2026, 5, 14, 12, 0, 0),
            data_path='test_workflow.csv',
        )
        db.session.add(run)
        db.session.commit()

        phase = WorkflowPhase(
            run_id=run.id,
            name='main',
            repeat_index=1,
            parameters=[{'input': 1}],
            outputs=[{'yield': [3, 4], 'status': 'ok'}],
            start_time=datetime(2026, 5, 14, 12, 1, 0),
        )
        db.session.add(phase)
        db.session.commit()

        step = WorkflowStep(
            phase_id=phase.id,
            step_index=1,
            method_name='deck.sensor.read',
            start_time=datetime(2026, 5, 14, 12, 2, 0),
            output={'input': 1, 'yield': 3},
        )
        db.session.add(step)
        db.session.commit()
        return run.id


def test_database_scripts_page(auth):
    """
    GIVEN an authenticated user
    WHEN they access the script library page
    THEN the page should load and show their scripts
    """
    # First, create a script so the page has something to render
    with auth.application.app_context():
        script = Script(name='test_script', author='testuser')
        db.session.add(script)
        db.session.commit()

    response = auth.get('/ivoryos/library/', follow_redirects=True)
    assert response.status_code == 200


def test_database_workflows_page(auth):
    """
    GIVEN an authenticated user
    WHEN they access the workflow records page
    THEN the page should load and show past workflow runs
    """
    # Create a workflow run to display
    with auth.application.app_context():
        run = WorkflowRun(name="untitled", platform="deck", start_time=datetime.now())
        db.session.add(run)
        db.session.commit()

    response = auth.get('/ivoryos/executions/records', follow_redirects=True)
    assert response.status_code == 200


def test_view_specific_workflow(auth):
    """
    GIVEN an authenticated user and an existing workflow run
    WHEN they access the specific URL for that workflow
    THEN the detailed view for that run should be displayed
    """
    with auth.application.app_context():
        run = WorkflowRun(name='test_workflow', platform='test_platform', start_time=datetime.now())
        db.session.add(run)
        db.session.commit()
        run_id = run.id

        phase = WorkflowPhase(run_id=run_id, name="main", start_time=datetime.now())
        db.session.add(phase)
        db.session.commit()

    response = auth.get(f'/ivoryos/executions/records/{run_id}', follow_redirects=True)
    assert response.status_code == 200


def test_database_workflows_json_filters_by_keyword(auth):
    run_id = create_workflow_run_with_phase(auth.application)

    response = auth.get(
        '/ivoryos/executions/records?keyword=test_workflow',
        headers={'Accept': 'application/json'},
    )

    assert response.status_code == 200
    workflow_data = response.get_json()['workflow_data']
    assert str(run_id) in workflow_data
    assert workflow_data[str(run_id)]['workflow_name'] == 'test_workflow'


def test_workflow_logs_json_and_missing_record(auth):
    run_id = create_workflow_run_with_phase(auth.application)

    response = auth.get(
        f'/ivoryos/executions/records/{run_id}',
        headers={'Accept': 'application/json'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['workflow_info']['name'] == 'test_workflow'
    assert payload['csv_file_name'] == 'test_workflow.csv'
    assert payload['phases']['script']['1'][0]['steps'][0]['method_name'] == 'deck.sensor.read'

    missing = auth.get('/ivoryos/executions/records/999999', headers={'Accept': 'application/json'})
    assert missing.status_code == 404
    assert missing.get_json() == {'error': 'Workflow not found'}


def test_workflow_phase_data_csv_logs_and_delete(auth):
    run_id = create_workflow_run_with_phase(auth.application)

    phase_data = auth.get(f'/ivoryos/executions/data/{run_id}')
    assert phase_data.status_code == 200
    assert phase_data.get_json() == {'1': {'yield': [{'x': 1, 'y': 3}, {'x': 1, 'y': 4}]}}

    csv_response = auth.get(f'/ivoryos/executions/records/{run_id}/steps_data_csv')
    assert csv_response.status_code == 200
    assert 'deck.sensor.read' in csv_response.get_data(as_text=True)
    assert 'test_workflow_steps.csv' in csv_response.headers['Content-disposition']

    missing_log = auth.get(f'/ivoryos/executions/records/{run_id}/logs')
    assert missing_log.status_code == 404
    assert missing_log.get_json() == {'error': 'Log file not found on disk'}

    delete_response = auth.delete(f'/ivoryos/executions/records/{run_id}')
    assert delete_response.status_code == 200
    assert delete_response.get_json() == {'success': True}
    with auth.application.app_context():
        assert db.session.get(WorkflowRun, run_id) is None

    missing_delete = auth.delete(f'/ivoryos/executions/records/{run_id}')
    assert missing_delete.status_code == 404
    assert missing_delete.get_json() == {'error': 'Workflow run not found', 'success': False}


def test_existing_database_gets_the_new_run_columns(app, tmp_path):
    """
    GIVEN a database from before runs kept their outcome, events and submitter, and
    iterations their status
    WHEN the app checks the schema at start
    THEN the columns are added, so queries on runs and iterations keep working
    """
    from sqlalchemy import create_engine, inspect, text
    from ivoryos.app import reset_old_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE workflow_runs (id INTEGER PRIMARY KEY, name VARCHAR(128), platform VARCHAR(128))"))
        conn.execute(text("CREATE TABLE workflow_phases (id INTEGER PRIMARY KEY, run_id INTEGER)"))

    with app.app_context():
        reset_old_schema(engine, str(tmp_path))

    assert {'status', 'events', 'submitted_by'} <= {column['name'] for column in inspect(engine).get_columns('workflow_runs')}
    assert {'status', 'error'} <= {column['name'] for column in inspect(engine).get_columns('workflow_phases')}


def test_workflow_view_reads_the_config_table_results_from_the_iterations(auth):
    """
    GIVEN a config run that was edited, had a row fail and was stopped early
    WHEN its page is opened
    THEN its table is read from the iterations: each row with its status, values
    and outputs, the failed value marked, the rows not run from their event, the
    edits from theirs, and the user's stop on the timeline
    """
    events = [
        {'time': '2026-10-06T10:00:02', 'kind': 'table_edited', 'detail': "Row 1: 'temperature' changed from '25' to '30' while it was running",
         'changes': [{'row': 1, 'action': 'edit', 'field': 'temperature', 'from': '25', 'to': '30', 'while_running': True}]},
        {'time': '2026-10-06T10:00:05', 'kind': 'stop_after_iteration', 'detail': None},
        {'time': '2026-10-06T10:00:09', 'kind': 'rows_not_run', 'detail': '1 row(s) of the table were not run.',
         'rows': [{'temperature': '60'}]},
    ]
    with auth.application.app_context():
        run = WorkflowRun(name='edited', platform='deck', start_time=datetime.now(), repeat_mode='batch',
                          status='stopped', events=events)
        db.session.add(run)
        db.session.flush()
        now = datetime.now()
        db.session.add_all([
            WorkflowPhase(run_id=run.id, name='main', repeat_index=1, status='done', start_time=now, end_time=now,
                          parameters=[{'temperature': 30.0}], outputs=[{'temperature': 30.0, 'yield_pct': 0.93}]),
            WorkflowPhase(run_id=run.id, name='main', repeat_index=2, status='failed', start_time=now, end_time=now,
                          parameters=[{'temperature': 'hot'}],
                          error={'message': "cannot convert 'hot'", 'fields': {'temperature': "cannot convert 'hot'"}}),
        ])
        db.session.commit()
        run_id = run.id

    body = auth.get(f'/ivoryos/executions/records/{run_id}').get_data(as_text=True)

    assert 'Stopped early' in body
    assert 'Config table results' in body
    # row 1 ran as iteration 1, with what it returned
    assert 'href="#card-iter1"' in body and '0.93' in body and '<th class="table-info">yield_pct</th>' in body
    # row 2 failed as iteration 2, its bad value marked, the reason on hover rather than spelled out
    assert '<td class="text-danger fw-semibold" title="cannot convert &#39;hot&#39;">hot</td>' in body
    assert '>failed</span>' in body
    # row 3 was never reached
    assert 'not run' in body and '<td>60</td>' in body
    assert 'Edited during the run (1)' in body
    assert "Row 1: &#39;temperature&#39; changed from &#39;25&#39; to &#39;30&#39; while it was running" in body
    assert '"Stop after this iteration"' in body and "group: 'events'" in body
    assert "className: 'script failed'" in body


def test_run_list_tells_running_and_unfinished_runs_apart(auth):
    """
    GIVEN a run in progress, one that never finished, and one from before outcomes were kept
    WHEN the run list is opened
    THEN the running one shows as running, the unfinished one as not finished,
    and the old one shows no outcome
    """
    from ivoryos.runtime.state import GlobalState

    with auth.application.app_context():
        running = WorkflowRun(name='now', platform='deck', start_time=datetime.now())
        unfinished = WorkflowRun(name='crashed', platform='deck', start_time=datetime.now())
        old = WorkflowRun(name='old', platform='deck', start_time=datetime.now(), end_time=datetime.now())
        db.session.add_all([running, unfinished, old])
        db.session.commit()
        running_id = running.id

    state = GlobalState()
    previous = state.runner_status
    state.runner_status = {'id': running_id, 'type': 'workflow'}
    state.runner_lock.acquire()
    try:
        body = auth.get('/ivoryos/executions/records').get_data(as_text=True)
    finally:
        state.runner_lock.release()
        state.runner_status = previous

    assert body.count('title="Running"') == 1
    assert body.count('title="Did not finish"') == 1
    assert 'bg-teal-subtle' not in body


def test_run_events_are_saved_as_they_happen(app, init_database):
    """
    GIVEN a run in progress
    WHEN the user pauses and stops it
    THEN each event is in the database right away, not only when the run ends,
    and nothing is saved once the run is over
    """
    from ivoryos.runtime.script_runner import ScriptRunner

    with app.app_context():
        run = WorkflowRun(name='live', platform='deck', start_time=datetime.now())
        db.session.add(run)
        db.session.commit()
        run_id = run.id

    runner = ScriptRunner()
    runner.current_app, runner.logger = app, None
    runner.run_events, runner.run_id = [], run_id

    runner.record_event('paused')
    with app.app_context():
        assert [event['kind'] for event in db.session.get(WorkflowRun, run_id).events] == ['paused']
    runner.record_event('stop_now', 'Cleanup skipped.')
    with app.app_context():
        saved = db.session.get(WorkflowRun, run_id).events
    assert [(event['kind'], event['detail']) for event in saved] == [('paused', None), ('stop_now', 'Cleanup skipped.')]

    runner.run_events, runner.run_id = None, None
    runner.record_event('resumed')
    with app.app_context():
        assert len(db.session.get(WorkflowRun, run_id).events) == 2


def test_results_table_marks_where_each_batch_begins(auth):
    """
    GIVEN a config run with two rows to an iteration
    WHEN its page is opened
    THEN a line marks where the second batch begins, and only there
    """
    with auth.application.app_context():
        run = WorkflowRun(name='batched', platform='deck', start_time=datetime.now(), repeat_mode='batch', status='completed')
        db.session.add(run)
        db.session.flush()
        now = datetime.now()
        for index, pair in enumerate([(1, 2), (3, 4)], start=1):
            db.session.add(WorkflowPhase(run_id=run.id, name='main', repeat_index=index, status='done',
                                         start_time=now, end_time=now,
                                         parameters=[{'temperature': value} for value in pair]))
        db.session.commit()
        run_id = run.id

    body = auth.get(f'/ivoryos/executions/records/{run_id}').get_data(as_text=True)

    assert body.count(' batch-start"') == 1


def test_the_run_list_shows_who_submitted_each_run_and_finds_them_by_it(auth):
    """
    GIVEN runs submitted by two users, and one from before the submitter was kept
    WHEN the run list is shown, searched and sorted
    THEN each run says who submitted it, and a search for a user finds their runs
    """
    with auth.application.app_context():
        for name, who in [('heat_a', 'alice'), ('heat_b', 'bob'), ('legacy_run', None)]:
            db.session.add(WorkflowRun(name=name, platform='deck', start_time=datetime.now(), submitted_by=who))
        db.session.commit()

    page = auth.get('/ivoryos/executions/records').get_data(as_text=True)
    assert 'Submitted By' in page and 'sort_by=submitted_by' in page
    assert '</i>alice' in page and '</i>bob' in page

    found = auth.get('/ivoryos/executions/records?keyword=alice').get_data(as_text=True)
    assert 'heat_a' in found and 'heat_b' not in found and 'legacy_run' not in found

    listed = auth.get('/ivoryos/executions/records?keyword=heat', headers={'Accept': 'application/json'}).get_json()
    assert sorted(run['submitted_by'] for run in listed['workflow_data'].values()) == ['alice', 'bob']

    by_user = auth.get('/ivoryos/executions/records?sort_by=submitted_by&order=asc').get_data(as_text=True)
    assert by_user.index('heat_a') < by_user.index('heat_b')


def test_a_run_page_says_who_submitted_it(auth):
    with auth.application.app_context():
        mine = WorkflowRun(name='mine', platform='deck', start_time=datetime.now(), submitted_by='alice')
        older = WorkflowRun(name='older', platform='deck', start_time=datetime.now())
        db.session.add_all([mine, older])
        db.session.commit()
        mine_id, older_id = mine.id, older.id

    page = auth.get(f'/ivoryos/executions/records/{mine_id}').get_data(as_text=True)
    assert 'Submitted by <strong>alice</strong>' in page
    # a run from before the submitter was kept says nothing rather than guessing
    assert 'run-submitted-by' not in auth.get(f'/ivoryos/executions/records/{older_id}').get_data(as_text=True)


def test_data_csv_keeps_what_an_unfinished_batch_got_done(auth):
    """
    GIVEN a batch of two samples whose first step ran for both, and whose second
    step failed on the first sample, leaving the run paused
    WHEN the data CSV is downloaded
    THEN each sample has its own row with what its steps returned so far
    """
    import pandas as pd
    from io import StringIO

    with auth.application.app_context():
        run = WorkflowRun(name='partial', platform='test_platform', start_time=datetime(2026, 5, 14, 12, 0, 0),
                          data_path='partial.csv', repeat_mode='batch')
        db.session.add(run)
        db.session.commit()
        phase = WorkflowPhase(run_id=run.id, name='main', repeat_index=1,
                              parameters=[{'x': 1}, {'x': 2}], start_time=datetime(2026, 5, 14, 12, 1, 0))
        db.session.add(phase)
        db.session.commit()
        ended = datetime(2026, 5, 14, 12, 2, 0)
        db.session.add_all([
            WorkflowStep(phase_id=phase.id, step_index=1, method_name='measure', end_time=ended,
                         output={'x': 1, 'a': 10}),
            WorkflowStep(phase_id=phase.id, step_index=1, method_name='measure', end_time=ended,
                         output={'x': 2, 'a': 20}),
            WorkflowStep(phase_id=phase.id, step_index=2, method_name='analyse', end_time=ended,
                         run_error=True, output={'x': 1, 'a': 10}),
        ])
        db.session.commit()
        run_id = run.id

    response = auth.get(f'/ivoryos/executions/records/{run_id}/data_csv')

    assert response.status_code == 200
    rows = pd.read_csv(StringIO(response.get_data(as_text=True))).to_dict(orient='records')
    assert rows == [{'x': 1, 'a': 10}, {'x': 2, 'a': 20}]
