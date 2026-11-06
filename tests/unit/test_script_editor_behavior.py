import pytest

from ivoryos.script import Script, ScriptEditor


def test_add_variable_math_and_input_actions_update_variables():
    script = Script(author="tester")
    editor = ScriptEditor(script)

    editor.add_variable("true", "flag value", "bool")
    editor.add_math_variable("#flag_value + 2", "score total")
    editor.add_input_action("Enter sample", "sample_name", "str")

    actions = script.script_dict["script"]
    assert [action["action"] for action in actions] == ["flag_value", "score_total", "sample_name"]
    assert actions[0]["args"]["statement"] is True
    assert actions[1]["instrument"] == "math_variable"
    assert actions[2]["return"] == "sample_name"
    assert editor.get_variables() == {
        "sample_name": "function_output",
        "flag_value": "bool",
        "score_total": "float",
    }


def test_insert_sort_duplicate_and_delete_actions_by_uuid():
    script = Script(author="tester")
    editor = ScriptEditor(script)
    editor.add_action({"instrument": "deck.pump", "action": "prime", "args": {}, "return": "", "arg_types": {}})
    editor.add_action(
        {"instrument": "deck.pump", "action": "dose", "args": {"amount": 1}, "return": "", "arg_types": {"amount": "int"}},
        insert_position="1",
    )

    assert [action["action"] for action in script.script_dict["script"]] == ["dose", "prime"]

    editor.duplicate_action(1)
    assert [action["id"] for action in script.script_dict["script"]] == [1, 2, 3]
    assert script.script_dict["script"][1]["action"] == "dose"

    editor.add_logic_action("if", "#ready")
    logic_uuid = script.script_dict["script"][-3]["uuid"]
    editor.delete_action(script.script_dict["script"][-3]["id"])

    assert all(action["uuid"] != logic_uuid for action in script.script_dict["script"])


def test_config_and_validate_variables_resolve_inputs_and_outputs():
    script = Script(author="tester")
    script.script_dict["script"] = [
        {
            "id": 1,
            "uuid": 1,
            "instrument": "deck.sensor",
            "action": "read",
            "args": {},
            "return": "reading",
            "arg_types": {},
        },
        {
            "id": 2,
            "uuid": 2,
            "instrument": "deck.pump",
            "action": "dose",
            "args": {"amount": "#configured_amount", "label": "literal"},
            "return": "",
            "arg_types": {"amount": "float", "label": "str"},
        },
        {
            "id": 3,
            "uuid": 3,
            "instrument": "math_variable",
            "action": "scaled",
            "args": {"statement": "#configured_amount * 2"},
            "return": "",
            "arg_types": {"statement": "float"},
        },
    ]

    editor = ScriptEditor(script)

    config, config_types = editor.config("script")
    assert config == ["configured_amount"]
    assert config_types == {"configured_amount": "float"}

    kwargs = editor.validate_variables(
        {"amount": "reading", "count": "42", "new variable": "#bad name"},
        {"amount": "float", "count": "int", "new variable": "str"},
    )
    assert kwargs == {
        "amount": "#reading",
        "count": 42,
        "new variable": "#bad_name",
    }


def test_duplicate_missing_action_raises_value_error():
    script = Script(author="tester")
    editor = ScriptEditor(script)

    with pytest.raises(ValueError):
        editor.duplicate_action(404)

def test_sort_actions_renumbers_sequentially():
    script = Script(author="tester")
    script.script_dict["script"] = [
        {"id": 99, "action": "first"},
        {"id": 5, "action": "second"},
        {"id": 42, "action": "third"}
    ]
    editor = ScriptEditor(script)
    editor.sort_actions("script")
    assert [action["id"] for action in script.script_dict["script"]] == [1, 2, 3]

def test_toggle_comment_action():
    script = Script(author="tester")
    script.script_dict["script"] = [
        {"id": 1, "uuid": 12345, "action": "dose", "disabled": False}
    ]
    editor = ScriptEditor(script)
    
    # Toggle to disabled
    editor.toggle_comment_action(1)
    assert script.script_dict["script"][0]["disabled"] is True
    
    # Toggle back to enabled
    editor.toggle_comment_action(1)
    assert script.script_dict["script"][0]["disabled"] is False


@pytest.mark.parametrize("blank", [None, ""])
def test_blank_repeat_and_pause_get_usable_defaults(blank):
    # a blank number field submits None, a blank text field submits ''
    script = Script(author="tester")
    editor = ScriptEditor(script)

    editor.add_logic_action("repeat", blank)
    editor.add_logic_action("pause", blank)
    editor.add_logic_action("comment", blank)

    statements = [action["args"].get("statement") for action in script.script_dict["script"]]
    assert statements == [1, None, "Human intervention required", ""]


def _row(instrument, action, uid):
    return {"instrument": instrument, "action": action, "uuid": uid}


@pytest.mark.parametrize("rows, problem", [
    # a whole block, an if without an else, and a step inside one: nothing to refuse
    ([_row("if", "if", 1), _row("deck.pump", "prime", 9), _row("if", "else", 1), _row("if", "endif", 1)], None),
    ([_row("if", "if", 1), _row("if", "endif", 1)], None),
    # crossing another block is left to the canvas warning: a move can pass through it
    ([_row("if", "if", 1), _row("if", "if", 2), _row("if", "else", 1), _row("if", "endif", 1),
      _row("if", "else", 2), _row("if", "endif", 2)], None),
    ([_row("if", "else", 1), _row("if", "if", 1), _row("if", "endif", 1)],
     "An else can't come before its own if."),
    ([_row("if", "if", 1), _row("if", "endif", 1), _row("if", "else", 1)],
     "An else can't come after its own endif."),
    ([_row("while", "endwhile", 1), _row("while", "while", 1)],
     "An endwhile can't come before its own while."),
    ([_row("repeat", "endrepeat", 1), _row("repeat", "repeat", 1)],
     "An endrepeat can't come before its own repeat."),
])
def test_block_order_problem(rows, problem):
    assert ScriptEditor.block_order_problem(rows) == problem


def test_block_order_problem_only_counts_blocks_the_move_puts_out_of_order():
    # block 1's else is already above its if (a draft saved before the check)
    before = [_row("if", "else", 1), _row("if", "if", 1), _row("if", "endif", 1),
              _row("deck.pump", "prime", 9), _row("if", "if", 2), _row("if", "endif", 2)]
    elsewhere = [before[i] for i in (0, 1, 3, 2, 4, 5)]
    fixed = [before[i] for i in (1, 0, 2, 3, 4, 5)]
    breaks_block_2 = [before[i] for i in (0, 1, 2, 3, 5, 4)]

    assert ScriptEditor.block_order_problem(elsewhere, before=before) is None
    assert ScriptEditor.block_order_problem(fixed, before=before) is None
    assert ScriptEditor.block_order_problem(breaks_block_2, before=before) == (
        "An endif can't come before its own if.")
