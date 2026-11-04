"""
Integration tests for type conversion through the instrument control route.

These tests verify that string values submitted through web forms are correctly
converted to their typed Python equivalents before calling instrument methods.
"""
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from tests.conftest import MockEnum


def _assert_runner_called(mock_run, method_name, expected_kwargs):
    mock_run.assert_awaited_once()
    args = mock_run.await_args.args
    assert args[0] == "deck.dummy"
    assert args[1] == method_name
    assert args[2] == expected_kwargs


def test_int_conversion(auth, test_deck):
    """Tests that a string from a form is converted to an integer."""
    with patch('ivoryos.runtime.task_runner.TaskRunner._run_single_step', new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "output": 123}
        response = auth.post(
            '/ivoryos/instruments/deck.dummy',
            data={'hidden_name': 'int_method', 'arg': '123', 'hidden_wait': 'true', 'override_busy': 'true'},
            follow_redirects=True
        )
        assert response.status_code == 200
        _assert_runner_called(mock_run, "int_method", {"arg": 123})


def test_float_conversion(auth, test_deck):
    """Tests that a string from a form is converted to a float."""
    with patch('ivoryos.runtime.task_runner.TaskRunner._run_single_step', new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "output": 123.45}
        response = auth.post(
            '/ivoryos/instruments/deck.dummy',
            data={'hidden_name': 'float_method', 'arg': '123.45', 'hidden_wait': 'true', 'override_busy': 'true'},
            follow_redirects=True
        )
        assert response.status_code == 200
        _assert_runner_called(mock_run, "float_method", {"arg": 123.45})


def test_bool_conversion(auth, test_deck):
    """Tests that a string from a form is converted to a boolean."""
    with patch('ivoryos.runtime.task_runner.TaskRunner._run_single_step', new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "output": True}
        response = auth.post(
            '/ivoryos/instruments/deck.dummy',
            data={'hidden_name': 'bool_method', 'arg': 'true', 'hidden_wait': 'true', 'override_busy': 'true'},
            follow_redirects=True
        )
        assert response.status_code == 200
        _assert_runner_called(mock_run, "bool_method", {"arg": True})


def test_list_conversion(auth, test_deck):
    """Tests that comma-separated form input reaches the runner as a list."""
    with patch('ivoryos.runtime.task_runner.TaskRunner._run_single_step', new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "output": ['a', 'b', 'c']}
        response = auth.post(
            '/ivoryos/instruments/deck.dummy',
            data={'hidden_name': 'list_method', 'arg': 'a,b,c', 'hidden_wait': 'true', 'override_busy': 'true'},
            follow_redirects=True
        )
        assert response.status_code == 200
        _assert_runner_called(mock_run, "list_method", {"arg": ["a", "b", "c"]})


def test_enum_conversion(auth, test_deck):
    """The form hands over the member's key; the runner calls the driver with the member."""
    with patch('ivoryos.runtime.task_runner.TaskRunner._run_single_step', new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "output": MockEnum.OPTION_B.value}
        response = auth.post(
            '/ivoryos/instruments/deck.dummy',
            data={'hidden_name': 'enum_method', 'arg': 'OPTION_B', 'hidden_wait': 'true', 'override_busy': 'true'},
            follow_redirects=True
        )
        assert response.status_code == 200
        _assert_runner_called(mock_run, "enum_method", {"arg": "OPTION_B"})
