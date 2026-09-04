import ast
from pathlib import Path


def test_v2_starts_after_legacy_subscription_cleanup_and_before_quote_pusher() -> None:
    app_path = Path(__file__).resolve().parents[2] / "simple_trade" / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))

    initialization_lines: list[int] = []
    v2_start_lines: list[int] = []
    quote_pusher_lines: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            if node.func.id == "initialize_system_data":
                initialization_lines.append(node.lineno)
            elif node.func.id == "AsyncQuotePusher":
                quote_pusher_lines.append(node.lineno)
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "start"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "v2_runtime"
        ):
            v2_start_lines.append(node.lineno)

    assert len(initialization_lines) == 1
    assert len(v2_start_lines) == 1
    assert len(quote_pusher_lines) == 1
    assert initialization_lines[0] < v2_start_lines[0] < quote_pusher_lines[0]
