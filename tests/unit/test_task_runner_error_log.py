"""A single step that fails leaves its traceback in the log; the page and its record keep only the message."""
import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from ivoryos.runtime.safety import SafetyViolation
from ivoryos.runtime.state import global_state
from ivoryos.runtime.task_runner import TaskRunner


class Arm:
    def grab(self, index: str = "A1"):
        self._move()

    def _move(self):
        raise TimeoutError("Timeout waiting for program to start running")


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.app_context.return_value.__enter__.return_value = app
    return app


@pytest.fixture
def arm():
    global_state.defined_variables["arm"] = Arm()
    yield
    global_state.defined_variables.pop("arm", None)


def _run(method, mock_app, kwargs=None):
    with patch("ivoryos.runtime.task_runner.db"):
        return asyncio.run(TaskRunner().run_single_step("arm", method, kwargs or {}, current_app=mock_app))


def _errors(caplog):
    return [r for r in caplog.records if r.name == "gui_logger" and r.levelno == logging.ERROR]


def test_failed_step_logs_traceback(arm, mock_app, caplog):
    with caplog.at_level(logging.ERROR, logger="gui_logger"):
        result = _run("grab", mock_app, {"index": "B2"})

    # the caller still gets only the message
    assert result == {"success": False, "output": "Timeout waiting for program to start running"}
    [record] = _errors(caplog)
    assert "arm.grab" in record.getMessage() and "B2" in record.getMessage()
    # the traceback reaches down to the line in the driver that raised
    assert record.exc_info[0] is TimeoutError
    assert "in _move" in caplog.text


def test_refused_step_logs_no_traceback(arm, mock_app, caplog):
    # a refusal by the limits is not a crash
    with patch("ivoryos.runtime.task_runner.guard.enforce", side_effect=SafetyViolation(["index is locked"])):
        with caplog.at_level(logging.ERROR, logger="gui_logger"):
            result = _run("grab", mock_app)

    assert result["success"] is False
    [record] = _errors(caplog)
    assert not record.exc_info


def test_step_that_cannot_be_found_is_logged(arm, mock_app, caplog):
    with caplog.at_level(logging.ERROR, logger="gui_logger"):
        result = _run("no_such_method", mock_app)

    assert result["status"] == "error"
    [record] = _errors(caplog)
    assert "arm.no_such_method" in record.getMessage()
    assert record.exc_info
