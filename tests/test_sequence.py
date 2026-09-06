import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from model.sequence import SequenceManager, SequenceSpec, SequenceStep
from lwsc import Lwsc
from textual.widgets import TabbedContent, TabPane, Button


def test_sequence_manager():
    config_path = Path(__file__).resolve().parent.parent / "src" / "config" / "sequences.yaml"
    mgr = SequenceManager(config_path)

    # 1. Total sequences loaded
    assert len(mgr.sequences) == 5, f"Expected 5 sequences, got {len(mgr.sequences)}"

    # 2. Visible sequences
    visible = mgr.get_visible_sequences()
    visible_ids = [s.id for s in visible]
    expected_visible = [
        "give_alliance_tech_gold",
        "claim_alliance_gifts_regular",
        "claim_alliance_gifts_premium",
        "claim_alliance_gifts_all",
    ]
    assert visible_ids == expected_visible, f"Visible mismatch: {visible_ids} != {expected_visible}"

    # 3. Hidden sequence
    morning = mgr.get("morning_routine")
    assert morning is not None
    assert morning.visible is False
    assert len(morning.steps) == 1
    assert morning.steps[0].type == "action"
    assert morning.steps[0].value == "alliance_tech_donate_gold"

    # 4. Check give_alliance_tech_gold
    give = mgr.get("give_alliance_tech_gold")
    assert give is not None
    assert give.steps[0].type == "action"
    assert give.steps[0].value == "alliance"
    assert give.steps[0].sleep == 1.0
    assert give.steps[-1].type == "action"
    assert give.steps[-1].value == "return"

    # 5. Check claim_alliance_gifts_regular with click current_position, return, wait_state, and return
    reg = mgr.get("claim_alliance_gifts_regular")
    assert reg is not None
    step_types = [s.type for s in reg.steps]
    assert step_types == ["action", "action", "action", "action", "click", "action", "wait_state", "action"]
    assert reg.steps[4].type == "click"
    assert reg.steps[4].value == "current_position"
    assert reg.steps[5].type == "action"
    assert reg.steps[5].value == "return"
    assert reg.steps[6].type == "wait_state"
    assert reg.steps[6].value == "alliance"
    assert reg.steps[7].type == "action"
    assert reg.steps[7].value == "return"

    # 6. Check nested sequences in claim_alliance_gifts_all
    all_gifts = mgr.get("claim_alliance_gifts_all")
    assert all_gifts is not None
    assert all_gifts.steps[0].type == "sequence"
    assert all_gifts.steps[0].value == "claim_alliance_gifts_regular"
    assert all_gifts.steps[-1].type == "sequence"
    assert all_gifts.steps[-1].value == "claim_alliance_gifts_premium"

    print("✅ test_sequence_manager PASSED")


import asyncio

async def test_lwsc_tabs_composition():
    app = Lwsc()
    # Disable state_supervisor thread during test
    app.state_supervisor = lambda: None

    async with app.run_test() as pilot:
        tabbed = pilot.app.query_one(TabbedContent)
        assert tabbed is not None

        panes = list(tabbed.query(TabPane))
        pane_ids = [pane.id for pane in panes]
        assert pane_ids == ["tab_actions", "tab_sequences", "tab_parameters", "tab_debug"], (
            f"Expected panes ['tab_actions', 'tab_sequences', 'tab_parameters', 'tab_debug'], got {pane_ids}"
        )

        seq_pane = pilot.app.query_one("#tab_sequences", TabPane)
        buttons = list(seq_pane.query(Button))
        button_ids = [b.id for b in buttons]
        expected_btn_ids = [
            "seq_give_alliance_tech_gold",
            "seq_claim_alliance_gifts_regular",
            "seq_claim_alliance_gifts_premium",
            "seq_claim_alliance_gifts_all",
        ]
        assert button_ids == expected_btn_ids, f"Button IDs mismatch: {button_ids} != {expected_btn_ids}"

        button_labels = [str(b.label) for b in buttons]
        assert button_labels == [
            "Give to alliance tech",
            "Claim regular alliance gifts",
            "Claim premium alliance gifts",
            "Claim all alliance gifts",
        ]

    print("✅ test_lwsc_tabs_composition PASSED")


def test_sequence_execution_flow():
    app = Lwsc()
    calls = []

    # Mock _find_and_click_button
    def mock_find_and_click(button_names, hold_duration=None, timeout=4.0, restore_cursor=False, action_name="", log_ui=None):
        calls.append(("action", button_names, action_name))
        return True

    app._find_and_click_button = mock_find_and_click
    app._wait_for_state = lambda target, timeout=5.0, log_ui=None: True

    logs = []
    log_ui = lambda msg: logs.append(msg)

    # Test claim_alliance_gifts_all which calls sub-sequences
    seq = app.sequence_mgr.get("claim_alliance_gifts_all")
    assert seq is not None

    # Patch time.sleep to run quickly
    import time
    orig_sleep = time.sleep
    time.sleep = lambda s: None
    try:
        ok = app._execute_sequence(seq, log_ui=log_ui, depth=0)
        assert ok is True
    finally:
        time.sleep = orig_sleep

    # Verify calls contain expected action steps from regular and premium sub-sequences
    # regular: alliance, alliance_gifts, alliance_gifts_regular, alliance_gifts_regular_claim_all, return, return
    # premium: alliance, alliance_gifts, alliance_gifts_premium, alliance_gifts_premium_claim_all, return, return
    action_calls = [c[2] for c in calls]
    assert "Alliance" in action_calls
    assert "Return" in action_calls

    print("✅ test_sequence_execution_flow PASSED")


def test_optional_sequence_steps():
    app = Lwsc()

    # Create sequence with optional failed action and optional sub-sequence
    failed_seq = SequenceSpec(
        id="failing_sub",
        label="Failing Sub",
        steps=[SequenceStep(type="action", value="non_existent_action")],
        optional=True,
    )
    app.sequence_mgr.sequences["failing_sub"] = failed_seq

    parent_seq = SequenceSpec(
        id="parent_test",
        label="Parent Test",
        steps=[
            # 1. Action that fails but is marked optional: true
            SequenceStep(type="action", value="non_existent_btn", kwargs={"optional": True}),
            # 2. Sub-sequence that fails but sub_seq.optional is True
            SequenceStep(type="sequence", value="failing_sub"),
            # 3. Sub-sequence that fails but step has optional: true
            SequenceStep(type="sequence", value="failing_sub_2", kwargs={"optional": True}),
        ],
    )

    logs = []
    log_ui = lambda msg: logs.append(msg)

    import time
    orig_sleep = time.sleep
    time.sleep = lambda s: None
    try:
        ok = app._execute_sequence(parent_seq, log_ui=log_ui, depth=0)
        assert ok is True, f"Sequence should continue and return True, got {ok}"
    finally:
        time.sleep = orig_sleep

    assert any("étape optionnelle" in log for log in logs)
    assert any("optionnelle" in log for log in logs)
    print("✅ test_optional_sequence_steps PASSED")


def test_wait_state_step():
    app = Lwsc()
    app.current_state = "headquarter"

    logs = []
    log_ui = lambda msg: logs.append(msg)

    # 1. Immediate state match
    seq_immediate = SequenceSpec(
        id="wait_hq",
        label="Wait HQ",
        steps=[SequenceStep(type="wait_state", value="headquarter", kwargs={"timeout": 1.0})],
    )
    ok = app._execute_sequence(seq_immediate, log_ui=log_ui)
    assert ok is True
    assert any("headquarter" in l for l in logs)

    # 2. Timeout failure (not optional)
    logs.clear()
    seq_fail = SequenceSpec(
        id="wait_fail",
        label="Wait Fail",
        steps=[SequenceStep(type="wait_state", value="alliance", kwargs={"timeout": 0.1})],
    )
    ok = app._execute_sequence(seq_fail, log_ui=log_ui)
    assert ok is False
    assert any("Timeout" in l for l in logs)

    # 3. Timeout with optional: true
    logs.clear()
    seq_optional = SequenceSpec(
        id="wait_opt",
        label="Wait Opt",
        steps=[SequenceStep(type="wait_state", value="alliance", kwargs={"timeout": 0.1, "optional": True})],
    )
    # 4. List of states
    logs.clear()
    seq_list = SequenceSpec(
        id="wait_list",
        label="Wait List",
        steps=[SequenceStep(type="wait_state", value=["headquarter", "area"], kwargs={"timeout": 0.5})],
    )
    ok = app._execute_sequence(seq_list, log_ui=log_ui)
    assert ok is True
    assert any("headquarter" in l for l in logs)

    # 5. Empty list
    logs.clear()
    seq_empty = SequenceSpec(
        id="wait_empty",
        label="Wait Empty",
        steps=[SequenceStep(type="wait_state", value=[], kwargs={"timeout": 0.5})],
    )
    ok = app._execute_sequence(seq_empty, log_ui=log_ui)
    assert ok is True

    print("✅ test_wait_state_step PASSED")


if __name__ == "__main__":
    test_sequence_manager()
    asyncio.run(test_lwsc_tabs_composition())
    test_sequence_execution_flow()
    test_optional_sequence_steps()
    test_wait_state_step()
    print("🎉 ALL TESTS PASSED!")




