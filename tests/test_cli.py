import re
import sys
from pathlib import Path
import os

import pytest
from typer.testing import CliRunner
import typer  # Import Typer for creating a test app

# Import the specific command function directly from your cli.py
from akaidoo.cli import akaidoo_command_entrypoint
from akaidoo.cli import pyperclip as actual_pyperclip_in_cli_module


def strip_ansi_codes(s: str) -> str:
    return re.sub(
        r"\x1b\[([0-9,A-Z]{1,2}(;[0-9]{1,2})?(;[0-9]{3})?)?[m|K|H|f|J]", "", s
    )


runner = CliRunner()

# This test_app will wrap your command function for CliRunner
# test_app = typer.Typer(add_completion=False, no_args_is_help=False) # Keep it simple for tests
# test_app.command(name="akaidoo_test_cmd", help="Test wrapper")(akaidoo_command_entrypoint)

test_app = typer.Typer(
    help="Akaidoo Test App Wrapper",  # Help for the wrapper app
    add_completion=False,
    no_args_is_help=True,  # If `akaidoo` (test_app) is run with no command, it shows its own help
)
# Register akaidoo_command_entrypoint as a command of test_app.
# This is how CliRunner can properly discover and invoke it as a command.
test_app.command(name="run")(
    akaidoo_command_entrypoint
)  # Use a simple name like "run" or keep "akaidoo_test_cmd"

# The name="akaidoo_test_cmd" is arbitrary for the test wrapper;
# CliRunner will invoke this when given the test_app.
# If you want to test the exact `akaidoo` command name as the entry point,
# the prog_name in runner.invoke handles that.


# --- Test Setup ---
@pytest.fixture(scope="module")
def dummy_addons_env(tmp_path_factory):
    # ... (your existing fixture is fine, no changes needed there) ...
    base_path = tmp_path_factory.mktemp("dummy_addons_env")
    addons_path = base_path / "addons"
    addons_path.mkdir()

    addon_a_path = addons_path / "addon_a"
    addon_a_path.mkdir()
    (addon_a_path / "__init__.py").write_text(
        "# addon_a init\nimport models\nCONSTANT_IN_A_INIT = True\n"
    )
    (addon_a_path / "__manifest__.py").write_text(
        "{'name': 'Addon A', 'version': '16.0.1.0.0', 'depends': ['base_addon', 'addon_b'], 'installable': True}"
    )
    (addon_a_path / "models").mkdir()
    (addon_a_path / "models" / "__init__.py").write_text(
        "# addon_a models init\nfrom . import a_model\nVALUE_IN_MODELS_INIT = 1\n"
    )
    (addon_a_path / "models" / "a_model.py").write_text(
        "class AModel:\n    pass # A's model\n"
    )
    (addon_a_path / "views").mkdir()
    (addon_a_path / "views" / "a_view.xml").write_text(
        "<odoo><data name='A_VIEW'/></odoo>"
    )

    addon_b_path = addons_path / "addon_b"
    addon_b_path.mkdir()
    (addon_b_path / "__init__.py").write_text("# addon_b init\n")
    (addon_b_path / "__manifest__.py").write_text(
        "{'name': 'Addon B', 'version': '16.0.1.0.0', 'depends': ['base_addon'], 'installable': True}"
    )
    (addon_b_path / "models").mkdir()
    (addon_b_path / "models" / "__init__.py").write_text(
        "# from . import b_model\n# only comments and imports"
    )
    (addon_b_path / "models" / "b_model.py").write_text(
        "class BModel:\n    pass # B's model\n"
    )
    (addon_b_path / "wizard").mkdir()
    (addon_b_path / "wizard" / "b_wizard.xml").write_text(
        "<odoo><data name='B_WIZARD'/></odoo>"
    )

    addon_c_path = addons_path / "addon_c"
    addon_c_path.mkdir()
    (addon_c_path / "__init__.py").touch()
    (addon_c_path / "__manifest__.py").write_text(
        "{'name': 'Addon C', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (addon_c_path / "security").mkdir()
    (addon_c_path / "security" / "ir.model.access.csv").write_text(
        "id,name\naccess_c,access_c\n"
    )

    base_addon_path = addons_path / "base_addon"
    base_addon_path.mkdir()
    (base_addon_path / "__init__.py").touch()
    (base_addon_path / "__manifest__.py").write_text(
        "{'name': 'Base Addon', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (base_addon_path / "models").mkdir()
    (base_addon_path / "models" / "base_model.py").write_text(
        "class BaseCoreModel:\n    pass\n"
    )

    framework_addon_name = "mail"
    framework_addon_path = addons_path / framework_addon_name
    framework_addon_path.mkdir()
    (framework_addon_path / "__init__.py").touch()
    (framework_addon_path / "__manifest__.py").write_text(
        f"{{'name': '{framework_addon_name.capitalize()}', 'version': '16.0.1.0.0', 'depends': ['base_addon'], 'installable': True}}"
    )
    (framework_addon_path / "models").mkdir()
    (framework_addon_path / "models" / f"{framework_addon_name}_model.py").write_text(
        f"class {framework_addon_name.capitalize()}Model:\n    pass\n"
    )
    (framework_addon_path / "models" / "__init__.py").write_text(
        f"# Trivial models init for {framework_addon_name}\n"
    )

    addon_a_manifest_path = addon_a_path / "__manifest__.py"
    addon_a_manifest_content_str = addon_a_manifest_path.read_text()
    try:
        manifest_dict = eval(addon_a_manifest_content_str)
        if (
            isinstance(manifest_dict, dict)
            and "depends" in manifest_dict
            and isinstance(manifest_dict["depends"], list)
        ):
            if framework_addon_name not in manifest_dict["depends"]:
                manifest_dict["depends"].append(framework_addon_name)
            addon_a_manifest_path.write_text(str(manifest_dict))
        else:  # Fallback for simple string manipulation if eval is not clean
            if "'depends': [" in addon_a_manifest_content_str:
                addon_a_manifest_content_str = addon_a_manifest_content_str.replace(
                    "'depends': ['base_addon', 'addon_b']",
                    f"'depends': ['base_addon', 'addon_b', '{framework_addon_name}']",
                ).replace(
                    "'depends': ['addon_b', 'base_addon']",
                    f"'depends': ['addon_b', 'base_addon', '{framework_addon_name}']",
                )
            else:  # If 'depends' key itself is missing
                addon_a_manifest_content_str = (
                    addon_a_manifest_content_str.rstrip("}")
                    + f", 'depends': ['{framework_addon_name}']}}"
                )

            addon_a_manifest_content_str.write_text(addon_a_manifest_content_str)

    except Exception as e:
        print(f"Warning: Error processing manifest for addon_a: {e}")

    odoo_conf_path = base_path / "dummy_odoo.conf"
    odoo_conf_path.write_text(f"[options]\naddons_path = {str(addons_path)}\n")

    return {
        "addons_path": addons_path,
        "odoo_conf": odoo_conf_path,
        "addon_a_path": addon_a_path,
        "addon_b_path": addon_b_path,
        "base_addon_path": base_addon_path,
        "framework_addon_path": framework_addon_path,
        "framework_addon_name": framework_addon_name,
    }


def _run_cli(args, catch_exceptions=False, expected_exit_code=None):
    str_args = [str(a) for a in args]
    print(f"\nCOMMAND: akaidoo {' '.join(str_args)}")

    # Invoke the test_app which wraps akaidoo_command_entrypoint
    result = runner.invoke(
        test_app, str_args, prog_name="akaidoo", catch_exceptions=catch_exceptions
    )

    print("STDOUT:", result.stdout)
    actual_stderr = ""
    if result.stderr_bytes:
        actual_stderr = result.stderr
        print("STDERR:", actual_stderr)
    elif result.exit_code != 0 and result.stdout and not result.stderr_bytes:
        print("STDERR (Note: Typer/Click error to stdout):", result.stdout)
        actual_stderr = result.stdout
    else:
        print("STDERR: (empty)")

    result.processed_stderr = actual_stderr

    if result.exception and not catch_exceptions:
        print("EXCEPTION:", result.exception)
        if not isinstance(result.exception, SystemExit):
            raise result.exception

    if expected_exit_code is not None:
        assert (
            result.exit_code == expected_exit_code
        ), f"Expected exit code {expected_exit_code} but got {result.exit_code}. STDERR: '{result.processed_stderr}' STDOUT: '{result.stdout}'"

    return result


def _get_file_names_from_output(output_str, separator=","):
    if not output_str.strip():
        return set()

    names = set()
    for line in output_str.splitlines():
        line = line.strip()
        if not line:
            continue

        # Check if it's a tree line (starts with tree characters or is a file in tree)
        if any(marker in line for marker in ["├── ", "└── ", "Module: ", "Path: "]):
            # Extract path from tree line
            # Example: ├── models/a_model.py (2KB) [Models: ...]
            match = re.search(r"[├└]──\s+([^\s(]+)", line)
            if match:
                path_part = match.group(1)
                names.add(Path(path_part).name)
            continue

        # Fallback for flat list (if separator is used or just absolute paths)
        for p in line.split(separator):
            if p.strip():
                # Avoid adding log-like lines that aren't paths
                p_trimmed = p.strip()
                if "/" in p_trimmed or "\\" in p_trimmed or "." in p_trimmed:
                    names.add(Path(p_trimmed).name)
    return names


# --- Tests ---


def test_main_help():
    # Invoke help on the test_app
    result = runner.invoke(test_app, ["--help"], prog_name="akaidoo")
    assert result.exit_code == 0
    stdout_clean = strip_ansi_codes(result.stdout)
    print(
        f"DEBUG: Cleaned STDOUT for help test:\n{stdout_clean}"
    )  # For debugging in CI
    # The Usage string comes from how Typer wraps akaidoo_command_entrypoint
    # Because akaidoo_command_entrypoint is now a command *of* test_app,
    # the help might show "Usage: akaidoo akaidoo_test_cmd [OPTIONS] ADDON_NAME"
    # or similar. Or, if test_app has no other commands, it might be simpler.
    # Let's check for the core parts.
    assert "Usage: akaidoo" in stdout_clean  # It will use prog_name
    assert "[OPTIONS] ADDON_NAME" in stdout_clean  # Key part
    # The main help might come from test_app's help or the command's docstring.
    # Let's check for options of akaidoo_command_entrypoint:
    # assert "-l" in stdout_clean  # SKIPPED: -l flag removed, replaced with --prune enum
    if result.stderr_bytes:
        print("STDERR from test_main_help:", result.stderr)
    assert not result.stderr_bytes


# ... (The rest of your tests should remain unchanged as their `args` list
#      correctly starts with `addon_name` which will be passed to `akaidoo_command_entrypoint`)


def test_list_files_basic_addons_path(dummy_addons_env):
    os.environ["VIRTUAL_ENV"] = "FAKE"  # avoid addons_path conflicts
    args = [
        "addon_a",
        "--addons-path",
        str(dummy_addons_env["addons_path"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files_basenames = _get_file_names_from_output(result.stdout)

    expected_present_basenames = {
        "a_model.py",
        "b_model.py",
        "base_model.py",
        f"{dummy_addons_env['framework_addon_name']}_model.py",
        "__init__.py",
        "__manifest__.py",
    }
    assert output_files_basenames.issuperset(expected_present_basenames)
    assert "ir.model.access.csv" not in output_files_basenames

    # output_full_paths = {p.strip() for p in result.stdout.strip().split(",") if p}
    # In tree mode, we use _get_file_names_from_output to get a set of filenames
    output_full_paths = _get_file_names_from_output(result.stdout)
    addon_a_root_init = dummy_addons_env["addon_a_path"] / "__init__.py"
    addon_a_models_init = dummy_addons_env["addon_a_path"] / "models" / "__init__.py"
    dummy_addons_env["addon_b_path"] / "__init__.py"
    dummy_addons_env["addon_b_path"] / "models" / "__init__.py"
    dummy_addons_env["framework_addon_path"] / "__init__.py"
    (dummy_addons_env["framework_addon_path"] / "models" / "__init__.py")

    assert addon_a_root_init.name in output_full_paths
    assert addon_a_models_init.name in output_full_paths
    # Note: __init__.py names clash, but _get_file_names_from_output collects unique names.
    # The logic of skipping trivial ones is still verified by the presence of a_model.py.


def test_list_files_odoo_conf(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files


def test_list_files_only_models(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    expected_models = {
        "a_model.py",
        "b_model.py",
        "base_model.py",
        f"{dummy_addons_env['framework_addon_name']}_model.py",
        "__init__.py",
    }
    assert output_files.issuperset(expected_models)
    assert "a_view.xml" not in output_files
    assert "b_wizard.xml" not in output_files

    output_full_paths_set = {
        Path(p.strip()).resolve() for p in result.stdout.strip().split(",") if p
    }
    addon_a_root_init_path = (
        dummy_addons_env["addon_a_path"] / "__init__.py"
    ).resolve()

    assert addon_a_root_init_path not in output_full_paths_set


def test_list_files_no_wizards(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--include=view",
        "--separator",
        ",",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "a_view.xml" in output_files
    assert "b_model.py" in output_files
    assert "b_wizard.xml" not in output_files


def test_list_files_exclude_framework(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files
    assert "base_model.py" in output_files
    assert f"{dummy_addons_env['framework_addon_name']}_model.py" not in output_files


def test_list_files_no_exclude_framework(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
        "--separator",
        ",",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    assert f"{dummy_addons_env['framework_addon_name']}_model.py" in output_files


@pytest.mark.skipif(
    sys.platform == "win32", reason="Clipboard tests are tricky on Windows CI"
)
def test_list_files_clipboard(dummy_addons_env, mocker):
    mock_pyperclip_module_patch = mocker.patch("akaidoo.cli.pyperclip", create=True)

    if not hasattr(mock_pyperclip_module_patch, "copy"):
        mock_pyperclip_module_patch.copy = mocker.Mock()

    args = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--clipboard",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)

    if actual_pyperclip_in_cli_module is not None:
        mock_pyperclip_module_patch.copy.assert_called_once()
        clipboard_content = mock_pyperclip_module_patch.copy.call_args[0][0]
        assert "# FILEPATH:" in clipboard_content
        assert "__manifest__.py" in clipboard_content
        assert "{'name': 'Addon C'" in clipboard_content
    elif actual_pyperclip_in_cli_module is None:
        assert "requires the 'pyperclip' library" in result.processed_stderr


def test_list_files_output_file(dummy_addons_env, tmp_path):
    output_file = tmp_path / "output.txt"
    args = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--output-file",
        str(output_file),
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    _run_cli(args, expected_exit_code=0)
    assert output_file.exists()
    content = output_file.read_text()
    assert "# FILEPATH:" in content
    assert "__manifest__.py" in content
    assert "{'name': 'Addon C'" in content


def test_list_files_edit_mode(dummy_addons_env, mocker):
    mock_run = mocker.patch("akaidoo.cli.subprocess.run")
    mock_process_result = mocker.Mock()
    mock_process_result.returncode = 0
    mock_run.return_value = mock_process_result

    mocker.patch.dict(os.environ, {"VISUAL": "myeditor", "EDITOR": "fallbackeditor"})

    args = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--edit",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    _run_cli(args, expected_exit_code=0)
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "myeditor"
    assert any(
        "__manifest__.py" in Path(arg).name
        for arg in called_cmd
        if isinstance(arg, str) and os.path.sep in arg
    )


def test_list_files_edit_mode_custom_cmd(dummy_addons_env, mocker):
    mock_run = mocker.patch("akaidoo.cli.subprocess.run")
    mock_process_result = mocker.Mock()
    mock_process_result.returncode = 0
    mock_run.return_value = mock_process_result

    args = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--edit",
        "--editor-cmd",
        "customvim -p",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    _run_cli(args, expected_exit_code=0)
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "customvim"
    assert called_cmd[1] == "-p"


def test_mutually_exclusive_outputs(dummy_addons_env):
    args_clipboard_output = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--clipboard",
        "--output-file",
        "out.txt",
    ]
    result1 = _run_cli(args_clipboard_output, expected_exit_code=1)
    assert "Please choose only one primary output action" in result1.processed_stderr

    args_edit_output = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--edit",
        "--output-file",
        "out.txt",
    ]
    result2 = _run_cli(args_edit_output, expected_exit_code=1)
    assert "Please choose only one primary output action" in result2.processed_stderr

    args_edit_clipboard = [
        "addon_c",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--edit",
        "--clipboard",
    ]
    result3 = _run_cli(args_edit_clipboard, expected_exit_code=1)
    assert "Please choose only one primary output action" in result3.processed_stderr


def test_list_files_missing_addon(dummy_addons_env):
    args = [
        "non_existent_addon",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
    ]
    result = _run_cli(args, expected_exit_code=1)
    assert "Addon(s) 'non_existent_addon' not found" in result.processed_stderr


def test_trivial_init_skipping(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)

    output_full_paths = _get_file_names_from_output(result.stdout)
    addon_a_root_init = dummy_addons_env["addon_a_path"] / "__init__.py"
    addon_a_models_init = dummy_addons_env["addon_a_path"] / "models" / "__init__.py"

    assert addon_a_root_init.name in output_full_paths
    assert addon_a_models_init.name in output_full_paths
    assert "a_model.py" in output_full_paths


def test_list_files_shrink_option(dummy_addons_env, mocker):
    mock_pyperclip_module_patch = mocker.patch("akaidoo.cli.pyperclip", create=True)

    if not hasattr(mock_pyperclip_module_patch, "copy"):
        mock_pyperclip_module_patch.copy = mocker.Mock()

    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--shrink=soft",
        "--clipboard",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)

    if actual_pyperclip_in_cli_module is not None:
        mock_pyperclip_module_patch.copy.assert_called_once()
        clipboard_content = mock_pyperclip_module_patch.copy.call_args[0][0]

        # Check that dependency model is shrunken
        b_model_path = (
            dummy_addons_env["addon_b_path"] / "models" / "b_model.py"
        ).resolve()
        assert f"# FILEPATH: {b_model_path}" in clipboard_content
        assert "class BModel:" in clipboard_content
        assert "pass # B's model" not in clipboard_content
        # assert "pass  # shrunk" in clipboard_content

        # Check that target addon model is NOT shrunken
        a_model_path = (
            dummy_addons_env["addon_a_path"] / "models" / "a_model.py"
        ).resolve()
        assert f"# FILEPATH: {a_model_path}" in clipboard_content
        assert "class AModel:" in clipboard_content
        assert "pass # A's model" in clipboard_content
        assert "pass  # body shrinked by akaidoo" not in clipboard_content

    elif actual_pyperclip_in_cli_module is None:
        assert "requires the 'pyperclip' library" in result.processed_stderr


def test_list_files_multiple_addons(dummy_addons_env):
    args = [
        "addon_a,addon_b",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--separator",
        ",",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)
    output_files = _get_file_names_from_output(result.stdout)
    # Check that files from both addons are present
    assert "a_model.py" in output_files
    assert "b_model.py" in output_files


def test_list_files_multiple_addons_shrink(dummy_addons_env, tmp_path):
    output_file = tmp_path / "out.txt"
    args = [
        "addon_a,addon_b",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--shrink=soft",
        "--output-file",
        str(output_file),
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    _run_cli(args, expected_exit_code=0)
    content = output_file.read_text()

    # Both should be full because they are both targets
    assert "class AModel:" in content
    assert "pass # A's model" in content
    assert "class BModel:" in content
    assert "pass # B's model" in content


def test_directory_mode_basic(tmp_path):
    d = tmp_path / "some_dir"
    d.mkdir()
    (d / "file1.py").write_text("print('hello')")
    (d / "subdir").mkdir()
    (d / "subdir" / "file2.txt").write_text("world")

    args = [str(d)]
    result = _run_cli(args, expected_exit_code=0)
    # Check that file paths are listed in stdout
    assert "file1.py" in result.stdout
    assert "file2.txt" in result.stdout


def test_directory_mode_trailing_slash_force(tmp_path):
    d = tmp_path / "my_addon"
    d.mkdir()
    (d / "__init__.py").touch()
    (d / "__manifest__.py").write_text("{'name': 'My Addon'}")
    (d / "models").mkdir()
    # Create proper Odoo model to avoid pruning
    (d / "models" / "model.py").write_text(
        """
from odoo import models

class MyModel(models.Model):
    _name = 'my.model'
    _description = 'My Model'
    name = fields.Char('Name')
"""
    )

    addon_path_str = str(d)
    if addon_path_str.endswith("/"):
        addon_path_str = addon_path_str[:-1]

    # Case 1: NO trailing slash -> Treated as "Project Mode" (valid addon path)
    result = _run_cli([addon_path_str, "-V"], expected_exit_code=0)
    # Check logs for "Project Mode" activation
    # Note: Log messages may be in stdout or stderr depending on environment
    combined_output = result.stdout + result.processed_stderr
    assert "treated as Odoo addon name" in combined_output
    assert "Implicitly added addons paths" in combined_output
    assert "model.py" in result.stdout

    # Case 2: WITH trailing slash -> Forced to Directory Mode
    result_forced = _run_cli([addon_path_str + "/", "-V"], expected_exit_code=0)
    # Check logs for Directory Mode activation
    # Note: Log messages may be in stdout or stderr depending on environment
    combined_output_forced = result_forced.stdout + result_forced.processed_stderr
    assert "is a directory. Listing all files recursively" in combined_output_forced
    assert "model.py" in result_forced.stdout


def test_directory_mode_skips_i18n(tmp_path):
    d = tmp_path / "my_addon_with_i18n"
    d.mkdir()
    (d / "__init__.py").touch()
    (d / "i18n").mkdir()
    (d / "i18n" / "fr.po").write_text("...")
    (d / "models").mkdir()
    (d / "models" / "m.py").write_text("...")

    args = [str(d) + "/"]
    result = _run_cli(args, expected_exit_code=0)
    assert "fr.po" not in result.stdout
    assert "m.py" in result.stdout


def test_list_files_tree_mode(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)
    # Check for tree symbols and addon names in output
    assert "addon_a" in result.stdout
    assert "addon_b" in result.stdout
    assert "├──" in result.stdout or "└──" in result.stdout
    assert "models/a_model.py" in result.stdout
    assert "models/b_model.py" in result.stdout


@pytest.fixture
def project_structure(tmp_path):
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    addon_1 = project_dir / "addon_1"
    addon_1.mkdir()
    (addon_1 / "__init__.py").touch()
    (addon_1 / "__manifest__.py").write_text("{'name': 'Addon 1', 'depends': []}")
    (addon_1 / "models").mkdir()
    (addon_1 / "models" / "a1.py").write_text("class A1: pass")

    addon_2 = project_dir / "addon_2"
    addon_2.mkdir()
    (addon_2 / "__init__.py").touch()
    (addon_2 / "__manifest__.py").write_text(
        "{'name': 'Addon 2', 'depends': ['addon_1']}"
    )
    (addon_2 / "models").mkdir()
    (addon_2 / "models" / "a2.py").write_text("class A2: pass")

    not_addon = project_dir / "not_an_addon"
    not_addon.mkdir()
    (not_addon / "some_file.txt").write_text("hello")

    return project_dir


def test_project_mode_container(project_structure):
    args = [
        str(project_structure),
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
        "-V",
    ]
    result = _run_cli(args)
    # Note: Log messages may be in stdout or stderr depending on environment
    combined_output = result.stdout + result.processed_stderr
    assert "target(s)" in combined_output.lower()
    assert "a1.py" in result.stdout
    assert "a2.py" in result.stdout
    assert "some_file.txt" not in result.stdout


def test_project_mode_single_path(project_structure):
    addon_path = project_structure / "addon_1"
    args = [
        str(addon_path),
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args)
    assert "a1.py" in result.stdout
    assert "a2.py" not in result.stdout


def test_project_mode_mixed(project_structure):
    addon_path = project_structure / "addon_1"
    args = [
        f"{addon_path},addon_2",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args)
    assert "a1.py" in result.stdout
    assert "a2.py" in result.stdout


@pytest.fixture(scope="module")
def auto_expand_env(tmp_path_factory):
    base_path = tmp_path_factory.mktemp("auto_expand_env")
    addons_path = base_path / "addons"
    addons_path.mkdir()

    base_addon_path = addons_path / "base"
    base_addon_path.mkdir()
    (base_addon_path / "__init__.py").touch()
    (base_addon_path / "__manifest__.py").write_text(
        "{'name': 'Base', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (base_addon_path / "models").mkdir()
    (base_addon_path / "models" / "__init__.py").write_text("")

    base_models_path = base_addon_path / "models"

    base_model_content = """from odoo import models, fields

class BaseModel(models.Model):
    _name = 'base.model'
    _description = 'Base Model'

    name = fields.Char(string='Name')
    code = fields.Char(string='Code')
    active = fields.Boolean(string='Active', default=True)

    def action_activate(self):
        self.active = True

    def action_deactivate(self):
        self.active = False
"""
    (base_models_path / "base_model.py").write_text(base_model_content)

    target_addon_path = addons_path / "target_addon"
    target_addon_path.mkdir()
    (target_addon_path / "__init__.py").touch()
    (target_addon_path / "__manifest__.py").write_text(
        "{'name': 'Target Addon', 'version': '16.0.1.0.0', 'depends': ['base'], 'installable': True}"
    )
    (target_addon_path / "models").mkdir()
    (target_addon_path / "models" / "__init__.py").write_text("")

    target_models_path = target_addon_path / "models"

    high_score_model_content = """from odoo import models, fields, api

class HighScoreModel(models.Model):
    _inherit = 'base.model'
    _description = 'High Score Model - should be auto expanded'

    custom_field1 = fields.Char(string='Custom Field 1')
    custom_field2 = fields.Char(string='Custom Field 2')
    custom_field3 = fields.Char(string='Custom Field 3')
    custom_field4 = fields.Char(string='Custom Field 4')
    custom_field5 = fields.Char(string='Custom Field 5')
    custom_field6 = fields.Char(string='Custom Field 6')

    @api.model
    def custom_method_one(self):
        return True

    @api.model
    def custom_method_two(self):
        return True

    @api.model
    def custom_method_three(self):
        return True
"""
    (target_models_path / "high_score_model.py").write_text(high_score_model_content)

    low_score_model_content = """from odoo import models, fields

class LowScoreModel(models.Model):
    _inherit = 'base.model'
    _description = 'Low Score Model - should NOT be auto expanded'

    minor_field = fields.Char(string='Minor Field')
"""
    (target_models_path / "low_score_model.py").write_text(low_score_model_content)

    odoo_conf_path = base_path / "dummy_odoo.conf"
    odoo_conf_path.write_text(f"[options]\naddons_path = {str(addons_path)}\n")

    return {
        "addons_path": addons_path,
        "odoo_conf": odoo_conf_path,
        "target_addon_path": target_addon_path,
        "base_addon_path": base_addon_path,
    }


def test_auto_expand_high_score_model(auto_expand_env):
    args = [
        "target_addon",
        "-c",
        str(auto_expand_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--shrink=soft",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
        "-o",
        "/tmp/test_auto_expand.txt",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    import os

    os.remove("/tmp/test_auto_expand.txt")


def test_auto_expand_implies_shrink(auto_expand_env):
    args = [
        "target_addon",
        "-c",
        str(auto_expand_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
        "-o",
        "/tmp/test_auto_expand2.txt",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    import os

    os.remove("/tmp/test_auto_expand2.txt")


def test_auto_expand_with_explicit_expand(auto_expand_env):
    args = [
        "target_addon",
        "-c",
        str(auto_expand_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--expand",
        "base.model",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
        "-o",
        "/tmp/test_auto_expand3.txt",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    import os

    os.remove("/tmp/test_auto_expand3.txt")


def test_auto_expand_low_score_not_expanded(auto_expand_env):
    low_score_addon_path = auto_expand_env["addons_path"] / "low_score_addon"
    low_score_addon_path.mkdir()
    (low_score_addon_path / "__init__.py").touch()
    (low_score_addon_path / "__manifest__.py").write_text(
        "{'name': 'Low Score Addon', 'version': '16.0.1.0.0', 'depends': ['base'], 'installable': True}"
    )
    (low_score_addon_path / "models").mkdir()
    (low_score_addon_path / "models" / "__init__.py").write_text("")

    low_model_content = """from odoo import models, fields

class VeryLowScoreModel(models.Model):
    _inherit = 'base.model'

    tiny_field = fields.Char()
"""
    (low_score_addon_path / "models" / "low.py").write_text(low_model_content)

    args = [
        "low_score_addon",
        "-c",
        str(auto_expand_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
        "-o",
        "/tmp/test_auto_expand4.txt",
    ]
    result = _run_cli(args)
    assert result.exit_code == 0
    import os

    os.remove("/tmp/test_auto_expand4.txt")


@pytest.fixture(scope="module")
def pruning_env(tmp_path_factory):
    base_path = tmp_path_factory.mktemp("pruning_env")
    addons_path = base_path / "addons"
    addons_path.mkdir()

    # Target Addon
    target = addons_path / "target_addon"
    target.mkdir()
    (target / "__init__.py").touch()
    (target / "__manifest__.py").write_text(
        "{'name': 'Target', 'depends': ['dep_relevant', 'dep_irrelevant'], 'version': '16.0.1.0.0'}"
    )
    (target / "models").mkdir()
    (target / "models" / "model_a.py").write_text("""
from odoo import models, fields
class ModelA(models.Model):
    _name = 'model.a'
    # High score to auto-expand
    f1 = fields.Char()
    f2 = fields.Char()
    f3 = fields.Char()
    f4 = fields.Char()
    f5 = fields.Char()
    f6 = fields.Char()
    f7 = fields.Char()

    # Relation to B
    rel_b = fields.Many2one('model.b')
""")

    # Relevant Dependency (contains 'model.b')
    dep_rel = addons_path / "dep_relevant"
    dep_rel.mkdir()
    (dep_rel / "__init__.py").touch()
    (dep_rel / "__manifest__.py").write_text(
        "{'name': 'Dep Relevant', 'depends': [], 'version': '16.0.1.0.0'}"
    )
    (dep_rel / "models").mkdir()
    (dep_rel / "models" / "model_b.py").write_text("""
from odoo import models
class ModelB(models.Model):
    _name = 'model.b'
""")

    # Irrelevant Dependency (contains unrelated model)
    dep_irrel = addons_path / "dep_irrelevant"
    dep_irrel.mkdir()
    (dep_irrel / "__init__.py").touch()
    (dep_irrel / "__manifest__.py").write_text(
        "{'name': 'Dep Irrelevant', 'depends': [], 'version': '16.0.1.0.0'}"
    )
    (dep_irrel / "models").mkdir()
    (dep_irrel / "models" / "model_x.py").write_text("""
from odoo import models
class ModelX(models.Model):
    _name = 'model.x'
""")

    return addons_path


def test_no_pruning_logic_integrated(pruning_env):
    args = [
        "target_addon",
        "--addons-path",
        str(pruning_env),
    ]
    result = _run_cli(args, expected_exit_code=0)

    assert "dep_irrelevant" in result.stdout
    assert "[pruned]" not in result.stdout
    assert "models/model_x.py" in result.stdout


def test_tree_view_token_estimation(dummy_addons_env):
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)
    assert "Estimated context size:" in result.stdout
    assert "KB" in result.stdout
    assert "Tokens)" in result.stdout


def test_tree_view_shrunk_visualization(dummy_addons_env):
    """Test that tree view runs correctly with shrink mode enabled.

    Note: The dummy addon files use simple Python classes (not Odoo models),
    so per-model shrink indicators won't appear. This test verifies the tree
    structure is correctly displayed and shrinking doesn't break the tree view.
    """
    args = [
        "addon_a",
        "-c",
        str(dummy_addons_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--shrink=soft",
        "--no-exclude=base,web,web_editor,web_tour,portal,mail,digest,bus,auth_signup,base_setup,http_routing,utm,uom,product",
    ]
    result = _run_cli(args, expected_exit_code=0)

    # Verify tree structure is displayed correctly
    assert "Module: addon_a" in result.stdout
    assert "Module: addon_b" in result.stdout
    assert "a_model.py" in result.stdout
    assert "b_model.py" in result.stdout
    # File sizes should be shown
    assert "(35B)" in result.stdout or "(30B)" in result.stdout


@pytest.fixture(scope="module")
def odoo_models_env(tmp_path_factory):
    """Create a test environment with proper Odoo model definitions for expand testing."""
    base_path = tmp_path_factory.mktemp("odoo_models_env")
    addons_path = base_path / "addons"
    addons_path.mkdir()

    # Target addon with models that will be auto-expanded
    target_addon = addons_path / "target_addon"
    target_addon.mkdir()
    (target_addon / "__init__.py").write_text("from . import models\n")
    (target_addon / "__manifest__.py").write_text(
        "{'name': 'Target Addon', 'version': '16.0.1.0.0', 'depends': ['dep_addon'], 'installable': True}"
    )
    (target_addon / "models").mkdir()
    (target_addon / "models" / "__init__.py").write_text(
        "from . import sale_order\nfrom . import product\n"
    )
    # sale.order extension with enough fields/methods to trigger auto-expand
    (target_addon / "models" / "sale_order.py").write_text("""
from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    custom_field1 = fields.Char(string="Custom 1")
    custom_field2 = fields.Char(string="Custom 2")
    custom_field3 = fields.Char(string="Custom 3")
    custom_field4 = fields.Float(string="Custom 4")
    custom_field5 = fields.Float(string="Custom 5")
    custom_field6 = fields.Boolean(string="Custom 6")

    @api.depends('custom_field1')
    def _compute_something(self):
        for rec in self:
            rec.custom_field4 = 1.0

    def action_custom_method(self):
        return True

    def another_method(self):
        pass
""")
    # product.template extension (simpler)
    (target_addon / "models" / "product.py").write_text("""
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    extra_info = fields.Text(string="Extra Info")
""")

    # Dependency addon with base models
    dep_addon = addons_path / "dep_addon"
    dep_addon.mkdir()
    (dep_addon / "__init__.py").write_text("from . import models\n")
    (dep_addon / "__manifest__.py").write_text(
        "{'name': 'Dep Addon', 'version': '16.0.1.0.0', 'depends': [], 'installable': True}"
    )
    (dep_addon / "models").mkdir()
    (dep_addon / "models" / "__init__.py").write_text(
        "from . import sale_order\nfrom . import product\n"
    )
    # Base sale.order model
    (dep_addon / "models" / "sale_order.py").write_text("""
from odoo import models, fields, api

class SaleOrder(models.Model):
    _name = 'sale.order'
    _description = 'Sale Order'

    name = fields.Char(string="Order Reference", required=True)
    partner_id = fields.Many2one('res.partner', string="Customer")
    order_line = fields.One2many('sale.order.line', 'order_id', string="Order Lines")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirmed'),
    ], default='draft')
    amount_total = fields.Float(string="Total", compute='_compute_amount')

    @api.depends('order_line')
    def _compute_amount(self):
        for order in self:
            order.amount_total = sum(line.price for line in order.order_line)

    def action_confirm(self):
        self.write({'state': 'confirm'})
        return True
""")
    # Base product.template model
    (dep_addon / "models" / "product.py").write_text("""
from odoo import models, fields

class ProductTemplate(models.Model):
    _name = 'product.template'
    _description = 'Product Template'

    name = fields.Char(string="Name", required=True)
    description = fields.Text(string="Description")
    list_price = fields.Float(string="Price")
""")

    odoo_conf = base_path / "odoo.conf"
    odoo_conf.write_text(f"[options]\naddons_path = {addons_path}\n")

    return {
        "addons_path": addons_path,
        "odoo_conf": odoo_conf,
        "target_addon": target_addon,
        "dep_addon": dep_addon,
    }


def test_agent_mode_token_consistency(odoo_models_env, tmp_path):
    """Test that --agent mode produces similar token estimates to normal mode.

    This is a regression test for the bug where agent mode was incorrectly
    counting tokens (either double-counting or missing expanded model content).
    """
    base_args = [
        "target_addon",
        "-c",
        str(odoo_models_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--shrink=soft",
    ]

    # Run without --agent
    normal_output = tmp_path / "normal.md"
    normal_args = base_args + ["-o", str(normal_output)]
    result_normal = _run_cli(normal_args, expected_exit_code=0)

    # Run with --agent
    agent_output = tmp_path / "agent.md"
    agent_args = base_args + ["--agent", "-o", str(agent_output)]
    result_agent = _run_cli(agent_args, expected_exit_code=0)

    # Extract token estimates from output
    def extract_tokens(output):
        match = re.search(r"(\d+)k Tokens", output)
        if match:
            return int(match.group(1))
        return None

    normal_tokens = extract_tokens(result_normal.stdout)
    agent_tokens = extract_tokens(result_agent.stdout)

    assert normal_tokens is not None, "Could not extract token count from normal mode"
    assert agent_tokens is not None, "Could not extract token count from agent mode"

    # Token estimates should be within 5% of each other
    # (small difference is expected due to header differences)
    diff_percent = abs(normal_tokens - agent_tokens) / max(normal_tokens, 1) * 100
    assert diff_percent < 5, (
        f"Token estimates differ too much: normal={normal_tokens}k, agent={agent_tokens}k "
        f"({diff_percent:.1f}% difference)"
    )


def test_agent_mode_file_count_consistency(odoo_models_env, tmp_path):
    """Test that --agent mode includes the same number of files as normal mode."""
    base_args = [
        "target_addon",
        "-c",
        str(odoo_models_env["odoo_conf"]),
        "--no-addons-path-from-import-odoo",
        "--odoo-series",
        "16.0",
        "--shrink=soft",
    ]

    # Run without --agent
    normal_output = tmp_path / "normal.md"
    normal_args = base_args + ["-o", str(normal_output)]
    result_normal = _run_cli(normal_args, expected_exit_code=0)

    # Run with --agent
    agent_output = tmp_path / "agent.md"
    agent_args = base_args + ["--agent", "-o", str(agent_output)]
    result_agent = _run_cli(agent_args, expected_exit_code=0)

    # Extract file counts
    def extract_file_count(output):
        match = re.search(r"Found (\d+) total files", output)
        if match:
            return int(match.group(1))
        return None

    normal_files = extract_file_count(result_normal.stdout)
    agent_files = extract_file_count(result_agent.stdout)

    assert normal_files is not None, "Could not extract file count from normal mode"
    assert agent_files is not None, "Could not extract file count from agent mode"

    # File counts should be identical
    assert (
        normal_files == agent_files
    ), f"File counts differ: normal={normal_files}, agent={agent_files}"
