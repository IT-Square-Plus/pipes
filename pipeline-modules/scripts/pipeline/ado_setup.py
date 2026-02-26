"""ADO Pipeline Manager."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.processors import PasswordProcessor
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, Shadow

from shared import settings
from shared.ado.approval import ApprovalService
from shared.ado.client import AdoClient
from shared.ado.environment import EnvironmentService
from shared.exceptions import AdoApiError


# -- ASCII Art ---------------------------------------------------------------

LOGO_LINES = [
    " \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2557 ",
    " \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557",
    " \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551",
    " \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551   \u2588\u2588\u2551",
    " \u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d",
    " \u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u255d  \u255a\u2550\u2550\u2550\u2550\u2550\u255d ",
    "    Pipeline Manager     ",
]


# -- Helpers -----------------------------------------------------------------

def _git_branch(repo_path: Path) -> str:
    """Get current git branch name for a repo directory."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "branch", "--show-current"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() or "(detached)"
    except Exception:
        return "(unknown)"


def _read_meta(repo_path: Path) -> dict | None:
    """Read meta.yaml from repo root. Returns None if not found."""
    meta_path = repo_path / "meta.yaml"
    if not meta_path.is_file():
        return None
    try:
        with open(meta_path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return None


# -- State -------------------------------------------------------------------

class AppState:
    def __init__(self) -> None:
        self.org: str = settings.org()
        self.project: str = settings.project()
        self.client: AdoClient | None = None
        self.pat_valid: bool = False

        # Screens: "settings" -> "pat" -> "main" -> "env_status"
        self.screen: str = "settings"

        # Settings screen
        self.editing: bool = False
        self.edit_field: str = ""

        # PAT screen
        self.pat_status: str = ""
        self.missing_scopes: list[str] = []

        # Main screen — directory browser
        self.browse_path: Path = Path.home()
        self.browse_entries: list[Path] = []
        self.browse_index: int = 0
        self.browse_scroll: int = 0
        self.selected_dir: Path | None = None
        self.selected_branch: str = ""
        self.selected_meta: dict | None = None  # None = no meta.yaml, {} = empty
        self.show_confirm_no_meta: bool = False

        # Main screen — focus: "browser" or "options"
        self.main_focus: str = "browser"

        # Main screen — shopping cart
        self.cart_index: int = 0
        self.cart_main: bool = False
        self.cart_promo_devqa: bool = False
        self.cart_promo_qastg: bool = False
        self.cart_promo_stgprd: bool = False
        self.cart_overwrite: bool = False

        # Promotion submenu
        self.show_promo_menu: bool = False
        self.promo_index: int = 0

        # Environment status screen
        self.env_tabs: list[str] = []
        self.env_tab_index: int = 0
        self.env_members: list[dict] = []
        self.env_members_loading: bool = False
        self.env_status: dict = {}
        self.env_loading: bool = False
        self.env_focus: str = "members"
        self.env_member_index: int = 0
        self.env_member_scroll: int = 0
        self.env_config_index: int = 0
        self.env_checked: dict = {}
        self.env_overwrite: dict = {}
        self.env_custom_min: dict = {}
        self.show_env_confirm: bool = False
        self.env_applying: bool = False
        self.env_apply_log: list[str] = []

    def refresh_browse(self) -> None:
        """Reload directory listing for current browse_path."""
        entries: list[Path] = []
        try:
            for entry in sorted(self.browse_path.iterdir()):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    entries.append(entry)
        except PermissionError:
            pass
        self.browse_entries = entries
        self.browse_index = 0
        self.browse_scroll = 0

    def is_git_dir(self, path: Path) -> bool:
        """Check if directory contains .git."""
        return (path / ".git").is_dir()

    def select_repo(self, path: Path) -> None:
        """Select a git repo — read meta.yaml and branch."""
        self.selected_dir = path
        self.selected_branch = _git_branch(path)
        self.selected_meta = _read_meta(path)

    @property
    def cart_has_promo(self) -> bool:
        return self.cart_promo_devqa or self.cart_promo_qastg or self.cart_promo_stgprd

    @property
    def cart_items(self) -> list[str]:
        """List of selected pipeline names for summary."""
        items: list[str] = []
        if self.cart_main:
            items.append("Main Pipeline")
        if self.cart_promo_devqa:
            items.append("DEV-to-QA")
        if self.cart_promo_qastg:
            items.append("QA-to-STG")
        if self.cart_promo_stgprd:
            items.append("STG-to-PRD")
        return items

state = AppState()


# -- Style -------------------------------------------------------------------

STYLE = Style.from_dict({
    # Base
    "":                  "bg:#0c0c0c #d4d4d4",
    # Logo
    "logo":              "#e06c75 bold",
    "logo.sub":          "#56b6c2",
    # Frame
    "frame":             "bg:#0c0c0c #3e4452",
    "frame.border":      "#3e4452",
    "frame.label":       "bg:#282c34 #61afef bold",
    # Title bar
    "title-bar":         "bg:#282c34 #abb2bf",
    "title-bar.screen":  "bg:#282c34 #c678dd bold",
    # Labels & values
    "label":             "#5c6370",
    "value":             "#e5c07b bold",
    "value.highlight":   "#61afef bold",
    # Keys
    "key":               "bg:#3e4452 #61afef bold",
    "key.label":         "#abb2bf",
    # Separator
    "separator":         "#3e4452",
    # Input
    "input":             "bg:#1e2127 #d4d4d4",
    "input-label":       "#61afef bold",
    # Feedback
    "ok":                "#98c379 bold",
    "fail":              "#e06c75 bold",
    "warn":              "#e5c07b bold",
    # Status bar
    "status":            "bg:#21252b #5c6370",
    "status.field":      "#abb2bf",
    "status.value":      "#61afef",
    "status.sep":        "#3e4452",
    # Dialog
    "dialog":            "bg:#282c34 #abb2bf",
    "dialog.border":     "#61afef",
    "dialog.shadow":     "bg:#000000",
    "dialog.title":      "bg:#61afef #282c34 bold",
    # Scrollbar
    "scrollbar.background": "bg:#1e2127",
    "scrollbar.button":     "bg:#3e4452",
    # Browser
    "browser.dir":       "#61afef",
    "browser.git":       "#98c379 bold",
    "browser.selected":  "bg:#282c34 #e5c07b bold",
    "browser.path":      "#c678dd bold",
    "browser.parent":    "#e5c07b",
    # Cart / options
    "cart":              "#abb2bf",
    "cart.selected":     "bg:#282c34 #e5c07b bold",
    "cart.checked":      "#98c379 bold",
    "cart.unchecked":    "#3e4452",
    "cart.action":       "#c678dd bold",
    "cart.action.sel":   "bg:#282c34 #c678dd bold",
    "cart.sub":          "#56b6c2",
    "cart.sub.sel":      "bg:#282c34 #56b6c2 bold",
    "cart.header":       "#61afef bold underline",
    # Meta info
    "meta.key":          "#5c6370",
    "meta.val":          "#98c379",
    "meta.branch":       "#c678dd bold",
    "meta.warn":         "#e5c07b",
    # Confirm dialog
    "confirm":           "bg:#282c34 #abb2bf",
    "confirm.warn":      "#e5c07b bold",
    "confirm.sel":       "bg:#3e4452 #61afef bold",
    "confirm.norm":      "#5c6370",
})


# -- Buffers -----------------------------------------------------------------

edit_buffer = Buffer(name="edit_input")
pat_buffer = Buffer(name="pat_input")


# -- Text builders -----------------------------------------------------------

def _get_logo_text() -> FormattedText:
    parts: list[tuple[str, str]] = []
    for i, line in enumerate(LOGO_LINES):
        style = "class:logo.sub" if i == len(LOGO_LINES) - 1 else "class:logo"
        parts.append((style, line))
        parts.append(("", "\n"))
    return FormattedText(parts)


def _get_title_bar_text() -> FormattedText:
    screen_label = {
        "settings": "SETTINGS",
        "pat": "AUTHENTICATION",
        "main": "PIPELINE INSTALLER",
        "env_status": "ENVIRONMENT STATUS",
    }
    label = screen_label.get(state.screen, "")
    return FormattedText([
        ("class:title-bar", "  "),
        ("class:title-bar.screen", f"\u25cf {label}"),
        ("class:title-bar", "  "),
    ])


def _get_settings_text() -> FormattedText:
    return FormattedText([
        ("", "\n"),
        ("class:label", "  Organization   "),
        ("class:value", f"\u25b8 {state.org}"),
        ("", "\n\n"),
        ("class:label", "  Project        "),
        ("class:value", f"\u25b8 {state.project}"),
        ("", "\n"),
    ])


def _get_settings_keys() -> FormattedText:
    return FormattedText([
        ("", "  "),
        ("class:key", " O "), ("class:key.label", " Org  "),
        ("class:key", " P "), ("class:key.label", " Project  "),
        ("class:key", " \u23ce "), ("class:key.label", " Continue  "),
        ("class:key", " Q "), ("class:key.label", " Quit "),
    ])


def _get_pat_text() -> FormattedText:
    parts: list[tuple[str, str]] = [
        ("", "\n"),
        ("class:label", "  Organization   "),
        ("class:value.highlight", state.org),
        ("", "\n"),
        ("class:label", "  Project        "),
        ("class:value.highlight", state.project),
        ("", "\n"),
    ]
    if state.pat_status == "validating":
        parts.extend([("", "\n"), ("class:warn", "  \u23f3 Validating...")])
    elif state.pat_status == "ok":
        parts.extend([("", "\n"), ("class:ok", "  \u2714 PAT validated successfully")])
    elif state.pat_status == "fail":
        parts.extend([("", "\n"), ("class:fail", "  \u2718 Invalid PAT. Check and try again.")])
    elif state.pat_status == "scope_check":
        parts.extend([
            ("", "\n"),
            ("class:ok", "  \u2714 PAT is valid\n"),
            ("class:warn", "  \u23f3 Checking scopes...\n"),
        ])
    elif state.pat_status == "scope_ok":
        parts.extend([
            ("", "\n"),
            ("class:ok", "  \u2714 PAT validated successfully\n"),
            ("class:ok", "  \u2714 All required scopes present\n"),
        ])
    elif state.pat_status == "scope_fail":
        parts.extend([
            ("", "\n"),
            ("class:ok", "  \u2714 PAT is valid\n"),
            ("class:fail", "  \u2718 Missing required scopes:\n\n"),
        ])
        for scope in state.missing_scopes:
            parts.append(("class:fail", f"     \u2022 {scope}\n"))
    return FormattedText(parts)


def _get_pat_keys() -> FormattedText:
    return FormattedText([
        ("", "  "),
        ("class:key", " \u23ce "), ("class:key.label", " Validate  "),
        ("class:key", " Esc "), ("class:key.label", " Back "),
    ])


def _get_browser_text() -> FormattedText:
    """Directory browser + repo info below."""
    parts: list[tuple[str, str]] = [
        ("class:browser.path", f" \u276f {state.browse_path}\n"),
        ("", "\n"),
    ]

    # Parent directory
    parent_style = "class:browser.selected" if state.browse_index == 0 else "class:browser.parent"
    cursor = "\u25b8 " if state.browse_index == 0 and state.main_focus == "browser" else "  "
    parts.append((parent_style, f"{cursor}\u2191 ..\n"))

    # Directory entries
    max_visible = 15
    entries = state.browse_entries
    scroll = state.browse_scroll

    for i in range(scroll, min(scroll + max_visible, len(entries))):
        entry = entries[i]
        idx = i + 1
        is_selected = idx == state.browse_index and state.main_focus == "browser"
        cursor = "\u25b8 " if is_selected else "  "
        git_marker = " \u25cf git" if state.is_git_dir(entry) else ""

        style = "class:browser.selected" if is_selected else "class:browser.dir"
        parts.append((style, f"{cursor}{entry.name}"))
        if git_marker:
            parts.append(("class:browser.git", git_marker))
        parts.append(("", "\n"))

    if not entries:
        parts.append(("class:label", "  (empty)\n"))

    # Repo info section
    if state.selected_dir:
        parts.extend([
            ("", "\n"),
            ("class:separator", " \u2500\u2500\u2500 Selected Repository \u2500\u2500\u2500\n"),
            ("", "\n"),
            ("class:meta.key", "  Directory  "),
            ("class:ok", f"{state.selected_dir.name}\n"),
            ("class:meta.key", "  Branch     "),
            ("class:meta.branch", f"{state.selected_branch}\n"),
        ])

        meta = state.selected_meta
        if meta is not None:
            parts.append(("", "\n"))
            # Display meta.yaml fields
            display_fields = [
                ("codename", "Codename"),
                ("project", "Project"),
                ("version", "Version"),
                ("team", "Team"),
                ("environment", "Env"),
                ("author", "Author"),
                ("authors", "Authors"),
                ("user", "User"),
                ("instance", "Instance"),
            ]
            for key, label in display_fields:
                val = meta.get(key)
                if val is not None:
                    if isinstance(val, list):
                        val = ", ".join(str(v) for v in val)
                    parts.append(("class:meta.key", f"  {label:<11}"))
                    parts.append(("class:meta.val", f"{val}\n"))
        else:
            parts.extend([
                ("", "\n"),
                ("class:meta.warn", "  \u26a0 No meta.yaml found\n"),
            ])

    return FormattedText(parts)


def _get_cart_text() -> FormattedText:
    """Right panel: shopping cart with pipeline selection."""
    parts: list[tuple[str, str]] = [("", "\n")]

    # Cart items definition:
    # 0: Main Pipeline (checkbox)
    # 1: Promotion Pipelines (opens submenu)
    # 2: Overwrite existing (checkbox)
    # 3: separator
    # 4: >> Proceed (action)

    cart_items = [
        {"label": "Main Pipeline", "kind": "checkbox", "key": "cart_main"},
        {"label": "Promotion Pipelines \u25b8", "kind": "submenu"},
        {"label": "Overwrite existing", "kind": "checkbox", "key": "cart_overwrite"},
    ]

    parts.append(("", "\n"))

    for i, item in enumerate(cart_items):
        is_sel = i == state.cart_index and state.main_focus == "options" and not state.show_promo_menu
        cursor = "\u25b8 " if is_sel else "  "

        if item["kind"] == "checkbox":
            checked = getattr(state, item["key"])
            check = "\u2714" if checked else "\u2500"
            check_style = "class:cart.checked" if checked else "class:cart.unchecked"
            label_style = "class:cart.selected" if is_sel else "class:cart"
            parts.append((label_style, f"{cursor}["))
            parts.append((check_style, check))
            parts.append((label_style, f"] {item['label']}"))
        elif item["kind"] == "submenu":
            label_style = "class:cart.selected" if is_sel else "class:cart.sub"
            promo_count = sum([state.cart_promo_devqa, state.cart_promo_qastg, state.cart_promo_stgprd])
            suffix = f" ({promo_count}/3)" if promo_count > 0 else ""
            parts.append((label_style, f"{cursor}{item['label']}{suffix}"))

        parts.append(("", "\n"))

        # Promo sub-items right after Promotion Pipelines entry
        if i == 1 and state.cart_has_promo:
            if state.cart_promo_devqa:
                parts.append(("class:cart.checked", "      \u2714 DEV-to-QA\n"))
            if state.cart_promo_qastg:
                parts.append(("class:cart.checked", "      \u2714 QA-to-STG\n"))
            if state.cart_promo_stgprd:
                parts.append(("class:cart.checked", "      \u2714 STG-to-PRD\n"))

    parts.append(("", "\n"))
    parts.append(("class:separator", " \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n"))

    # Cart summary
    items = state.cart_items
    can_continue = bool(items) and state.selected_dir is not None

    if items:
        parts.append(("class:ok", f" \u2714 {len(items)} pipeline(s) selected\n"))
        if state.cart_overwrite:
            parts.append(("class:warn", " \u26a0 Overwrite mode ON\n"))
    else:
        parts.append(("class:label", " Cart is empty\n"))

    if not state.selected_dir:
        parts.extend([("", "\n"), ("class:warn", " \u26a0 Select a Git directory first")])
    elif not items:
        parts.extend([("", "\n"), ("class:label", " Select pipelines to install")])

    # Continue button (index 3)
    if can_continue:
        is_sel = state.cart_index == 3 and state.main_focus == "options" and not state.show_promo_menu
        parts.append(("", "\n"))
        cursor = "\u25b8 " if is_sel else "  "
        style = "class:cart.action.sel" if is_sel else "class:cart.action"
        parts.append((style, f"{cursor}\u23ce Continue"))

    return FormattedText(parts)


def _get_promo_menu_text() -> FormattedText:
    """Floating submenu for promotion pipeline selection."""
    parts: list[tuple[str, str]] = [("", "\n")]

    promos = [
        ("cart_promo_devqa", "DEV-to-QA"),
        ("cart_promo_qastg", "QA-to-STG"),
        ("cart_promo_stgprd", "STG-to-PRD"),
    ]

    for i, (key, label) in enumerate(promos):
        is_sel = i == state.promo_index
        checked = getattr(state, key)
        cursor = "\u25b8 " if is_sel else "  "
        check = "\u2714" if checked else "\u2500"
        check_style = "class:cart.checked" if checked else "class:cart.unchecked"
        label_style = "class:cart.selected" if is_sel else "class:cart"

        parts.append((label_style, f"{cursor}["))
        parts.append((check_style, check))
        parts.append((label_style, f"] {label}\n"))

    parts.extend([
        ("", "\n"),
        ("class:key", " Space "), ("class:key.label", " Toggle  "),
        ("class:key", " \u23ce "), ("class:key.label", " Done  "),
        ("class:key", " Esc "), ("class:key.label", " Cancel "),
    ])

    return FormattedText(parts)


def _get_confirm_text() -> FormattedText:
    """Floating confirm dialog for repos without meta.yaml."""
    return FormattedText([
        ("class:confirm.warn", " \u26a0 Warning\n"),
        ("class:separator", " \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n"),
        ("class:confirm", " This repo does not have a meta.yaml.\n"),
        ("class:confirm", " It may not be configured according\n"),
        ("class:confirm", " to EMEA-GI-Team standards.\n\n"),
        ("class:confirm", " Are you sure you want to pick this one?\n\n"),
        ("class:key", " Y "), ("class:key.label", " Yes  "),
        ("class:key", " N "), ("class:key.label", " No "),
    ])


def _get_env_tab_bar_text() -> FormattedText:
    """Tab bar for switching between environments."""
    parts: list[tuple[str, str]] = [("", "  ")]
    for i, env_name in enumerate(state.env_tabs):
        if i == state.env_tab_index:
            parts.append(("class:cart.header", f" {env_name.upper()} "))
        else:
            parts.append(("class:label", f" {env_name.upper()} "))
        if i < len(state.env_tabs) - 1:
            parts.append(("class:separator", " \u2502 "))
    if state.env_loading:
        parts.append(("class:warn", "   \u23f3 Loading..."))
    return FormattedText(parts)


def _get_env_members_text() -> FormattedText:
    """Left panel: project members with checkboxes."""
    parts: list[tuple[str, str]] = [("", "\n")]

    if state.env_members_loading:
        parts.append(("class:warn", "  \u23f3 Loading members...\n"))
        return FormattedText(parts)

    if not state.env_members:
        parts.append(("class:label", "  No members found.\n"))
        return FormattedText(parts)

    current_env = state.env_tabs[state.env_tab_index] if state.env_tabs else ""
    checked = state.env_checked.get(current_env, set())
    checked_count = len(checked)

    parts.append(("class:label", f"  Selected: "))
    parts.append(("class:value", f"{checked_count}"))
    parts.append(("class:label", f" / {len(state.env_members)}\n\n"))

    max_visible = 16
    scroll = state.env_member_scroll
    members = state.env_members

    for i in range(scroll, min(scroll + max_visible, len(members))):
        member = members[i]
        is_sel = i == state.env_member_index and state.env_focus == "members"
        is_checked = member["id"] in checked
        cursor = "\u25b8 " if is_sel else "  "
        check = "\u2714" if is_checked else "\u2500"
        check_style = "class:cart.checked" if is_checked else "class:cart.unchecked"
        label_style = "class:cart.selected" if is_sel else "class:cart"

        parts.append((label_style, f"{cursor}["))
        parts.append((check_style, check))
        parts.append((label_style, f"] {member['displayName']}"))
        parts.append(("", "\n"))

    # Scroll indicator
    if len(members) > max_visible:
        parts.append(("", "\n"))
        parts.append(("class:label", f"  ({scroll + 1}\u2013{min(scroll + max_visible, len(members))} of {len(members)})"))

    return FormattedText(parts)


def _get_env_config_text() -> FormattedText:
    """Right panel: environment configuration."""
    parts: list[tuple[str, str]] = [("", "\n")]

    current_env = state.env_tabs[state.env_tab_index] if state.env_tabs else ""
    info = state.env_status.get(current_env, {})
    yaml_min = info.get("yaml_min", "?")

    # Settings.yaml reference
    parts.append(("class:label", "  Min Approvers from Settings: "))
    parts.append(("class:value", str(yaml_min)))
    parts.append(("", "\n\n"))

    # Current ADO status
    if state.env_loading:
        parts.append(("class:warn", "  \u23f3 Loading...\n\n"))
    elif info.get("exists"):
        parts.append(("class:ok", f"  \u2714 Environment exists (id: {info['env_id']})\n"))
        if info.get("has_approval"):
            parts.append(("class:ok", "  \u2714 Approval check configured\n"))
            parts.append(("class:label", "    Min required: "))
            parts.append(("class:value", f"{info.get('current_min', '?')}\n"))
            parts.append(("class:label", "    Approvers:\n"))
            for approver in info.get("current_approvers", []):
                parts.append(("class:meta.val", f"      \u2022 {approver}\n"))
        else:
            parts.append(("class:fail", "  \u2718 No approval check\n"))
        parts.append(("", "\n"))
    elif not state.env_loading:
        parts.append(("class:fail", "  \u2718 Environment does not exist\n"))
        parts.append(("class:label", "    Will be created\n\n"))

    parts.append(("class:separator", "  " + "\u2500" * 28 + "\n\n"))

    # Config item 0: Overwrite checkbox
    overwrite = state.env_overwrite.get(current_env, False)
    is_sel = state.env_config_index == 0 and state.env_focus == "config"
    cursor = "\u25b8 " if is_sel else "  "
    check = "\u2714" if overwrite else "\u2500"
    check_style = "class:cart.checked" if overwrite else "class:cart.unchecked"
    label_style = "class:cart.selected" if is_sel else "class:cart"

    if info.get("has_approval"):
        label = "Overwrite current Approvers setup"
    else:
        label = "Configure Approvers"

    parts.append((label_style, f"{cursor}["))
    parts.append((check_style, check))
    parts.append((label_style, f"] {label}\n\n"))

    # Config item 1: Min approvers
    custom_min = state.env_custom_min.get(current_env, str(yaml_min))
    is_sel = state.env_config_index == 1 and state.env_focus == "config"
    cursor = "\u25b8 " if is_sel else "  "
    label_style = "class:cart.selected" if is_sel else "class:cart"

    parts.append((label_style, f"{cursor}Min approvers: "))
    parts.append(("class:value.highlight", f"[{custom_min}]"))
    parts.append(("", "\n\n"))

    # Config item 2: Continue
    is_sel = state.env_config_index == 2 and state.env_focus == "config"
    cursor = "\u25b8 " if is_sel else "  "
    style = "class:cart.action.sel" if is_sel else "class:cart.action"
    parts.append((style, f"{cursor}\u23ce Continue"))
    parts.append(("", "\n"))

    return FormattedText(parts)


def _get_env_status_keys() -> FormattedText:
    focus_indicator = "MEMBERS" if state.env_focus == "members" else "CONFIG"
    return FormattedText([
        ("", "  "),
        ("class:key", " Tab "), ("class:key.label", " Switch  "),
        ("class:key", " [ ] "), ("class:key.label", " Env  "),
        ("class:key", " \u2191\u2193 "), ("class:key.label", " Navigate  "),
        ("class:key", " Space "), ("class:key.label", " Toggle  "),
        ("class:key", " \u23ce "), ("class:key.label", " Select  "),
        ("class:key", " Esc "), ("class:key.label", " Back  "),
        ("class:key", " Q "), ("class:key.label", " Quit  "),
        ("class:label", f"  \u25cf {focus_indicator}"),
    ])


def _get_env_confirm_text() -> FormattedText:
    """Floating confirm dialog for applying env settings."""
    if state.env_applying:
        parts: list[tuple[str, str]] = [
            ("class:confirm.warn", " \u23f3 Applying settings...\n"),
            ("class:separator", " " + "\u2500" * 34 + "\n\n"),
        ]
        for line in state.env_apply_log:
            parts.append(("class:confirm", f" {line}\n"))
        return FormattedText(parts)

    if state.env_apply_log:
        # Done — show results
        parts = [
            ("class:ok", " \u2714 Done!\n"),
            ("class:separator", " " + "\u2500" * 34 + "\n\n"),
        ]
        for line in state.env_apply_log:
            parts.append(("class:confirm", f" {line}\n"))
        parts.extend([
            ("", "\n"),
            ("class:key", " \u23ce "), ("class:key.label", " OK "),
        ])
        return FormattedText(parts)

    return FormattedText([
        ("class:confirm.warn", " \u26a0 Confirm\n"),
        ("class:separator", " " + "\u2500" * 34 + "\n\n"),
        ("class:confirm", " Do you want to continue?\n"),
        ("class:confirm", " The settings will be applied\n"),
        ("class:confirm", " to ADO Project.\n\n"),
        ("class:key", " Y "), ("class:key.label", " Yes  "),
        ("class:key", " N "), ("class:key.label", " No "),
    ])


def _apply_env_settings(app) -> None:
    """Background thread: apply environment + approval config to ADO."""
    env_svc = EnvironmentService(state.client)
    approval_svc = ApprovalService(state.client)

    for env_name in state.env_tabs:
        overwrite = state.env_overwrite.get(env_name, False)
        if not overwrite:
            state.env_apply_log.append(f"{env_name.upper()}: skipped (overwrite off)")
            app.invalidate()
            continue

        checked_ids = state.env_checked.get(env_name, set())
        if not checked_ids:
            state.env_apply_log.append(f"{env_name.upper()}: skipped (no approvers)")
            app.invalidate()
            continue

        approvers = [
            {"displayName": m["displayName"], "id": m["id"]}
            for m in state.env_members
            if m["id"] in checked_ids
        ]
        custom_min = int(state.env_custom_min.get(env_name, "1"))

        info = state.env_status.get(env_name, {})

        # Ensure environment exists
        if info.get("exists"):
            env_id = info["env_id"]
        else:
            try:
                env_id = env_svc.create(env_name)
                state.env_apply_log.append(f"{env_name.upper()}: environment created (id: {env_id})")
                app.invalidate()
            except Exception as exc:
                state.env_apply_log.append(f"{env_name.upper()}: ERROR creating env — {exc}")
                app.invalidate()
                continue

        # Create or update approval check
        try:
            if info.get("has_approval"):
                check = approval_svc.get_check_details(env_id)
                if check:
                    approval_svc.update(check["id"], env_id, env_name, approvers, custom_min)
                    state.env_apply_log.append(f"{env_name.upper()}: approval check updated")
                else:
                    approval_svc.create(env_id, env_name, approvers, custom_min)
                    state.env_apply_log.append(f"{env_name.upper()}: approval check created")
            else:
                approval_svc.create(env_id, env_name, approvers, custom_min)
                state.env_apply_log.append(f"{env_name.upper()}: approval check created")
            app.invalidate()
        except Exception as exc:
            state.env_apply_log.append(f"{env_name.upper()}: ERROR — {exc}")
            app.invalidate()

    state.env_applying = False
    app.invalidate()


def _fetch_env_data(app) -> None:
    """Background thread: query ADO for members and environment status."""
    # Fetch project members
    try:
        data = state.client.get_vsaex("_apis/userentitlements?$top=500")
        raw_members = data.get("members") or data.get("items") or data.get("value") or []
        members = []
        for m in raw_members:
            user = m.get("user", {})
            members.append({
                "displayName": user.get("displayName", ""),
                "id": m.get("id", user.get("originId", "")),
            })
        members.sort(key=lambda x: x["displayName"].lower())
        state.env_members = members
    except Exception:
        state.env_members = []

    state.env_members_loading = False
    app.invalidate()

    # Fetch environment status
    env_svc = EnvironmentService(state.client)
    approval_svc = ApprovalService(state.client)

    yaml_approver_ids = set()
    yaml_approver_names = set()
    try:
        for a in settings.approvers():
            yaml_approver_ids.add(a["id"])
            yaml_approver_names.add(a["displayName"])
    except SystemExit:
        pass

    result: dict = {}
    for env_name in state.env_tabs:
        yaml_min = settings.min_approvers(env_name)
        entry: dict = {"yaml_min": yaml_min}

        try:
            env_id = env_svc.get_by_name(env_name)
        except Exception:
            env_id = None

        if env_id is not None:
            entry["exists"] = True
            entry["env_id"] = env_id

            try:
                check = approval_svc.get_check_details(env_id)
            except Exception:
                check = None

            if check is not None:
                entry["has_approval"] = True
                check_settings = check.get("settings", {})
                entry["current_min"] = check_settings.get("minRequiredApprovers", 0)
                entry["current_approvers"] = [
                    a.get("displayName", a.get("id", "unknown"))
                    for a in check_settings.get("approvers", [])
                ]
            else:
                entry["has_approval"] = False
                entry["current_approvers"] = []
                entry["current_min"] = 0
        else:
            entry["exists"] = False
            entry["env_id"] = None
            entry["has_approval"] = False
            entry["current_approvers"] = []
            entry["current_min"] = 0

        result[env_name] = entry

        # Pre-populate checked members from settings.yaml
        checked = set()
        for member in state.env_members:
            if member["id"] in yaml_approver_ids or member["displayName"] in yaml_approver_names:
                checked.add(member["id"])
        state.env_checked.setdefault(env_name, checked)

        # Pre-populate min from settings.yaml
        state.env_custom_min.setdefault(env_name, str(yaml_min))

        # Pre-populate overwrite (default True if no existing approval)
        state.env_overwrite.setdefault(env_name, not entry.get("has_approval", False))

    state.env_status = result
    state.env_loading = False
    app.invalidate()


def _get_main_keys() -> FormattedText:
    focus_indicator = "BROWSER" if state.main_focus == "browser" else "CART"
    return FormattedText([
        ("", "  "),
        ("class:key", " Tab "), ("class:key.label", " Switch  "),
        ("class:key", " \u2191\u2193 "), ("class:key.label", " Navigate  "),
        ("class:key", " \u23ce "), ("class:key.label", " Select  "),
        ("class:key", " Space "), ("class:key.label", " Toggle  "),
        ("class:key", " Esc "), ("class:key.label", " Back  "),
        ("class:key", " Q "), ("class:key.label", " Quit  "),
        ("class:label", f"  \u25cf {focus_indicator}"),
    ])


def _get_status_text() -> FormattedText:
    pat_str = "\u2714" if state.pat_valid else "\u2013"
    parts = [
        ("class:status", "  "),
        ("class:status.field", "Org "),
        ("class:status.value", state.org),
        ("class:status.sep", "  \u2502  "),
        ("class:status.field", "Project "),
        ("class:status.value", state.project),
        ("class:status.sep", "  \u2502  "),
        ("class:status.field", "PAT "),
        ("class:ok" if state.pat_valid else "class:status", pat_str),
    ]
    if state.selected_dir:
        parts.extend([
            ("class:status.sep", "  \u2502  "),
            ("class:status.field", "Repo "),
            ("class:status.value", state.selected_dir.name),
        ])
    parts.append(("class:status", "  "))
    return FormattedText(parts)


def _get_edit_title() -> str:
    if state.edit_field == "org":
        return "Organization"
    elif state.edit_field == "min_approvers":
        return "Min Approvers"
    return "Project"


# -- Key bindings ------------------------------------------------------------

kb = KeyBindings()
_on_settings = Condition(lambda: state.screen == "settings" and not state.editing)
_editing = Condition(lambda: state.editing)
_on_pat = Condition(lambda: state.screen == "pat")
_on_main = Condition(lambda: state.screen == "main" and not state.show_promo_menu and not state.show_confirm_no_meta)
_on_browser = Condition(lambda: state.screen == "main" and state.main_focus == "browser" and not state.show_promo_menu and not state.show_confirm_no_meta)
_on_cart = Condition(lambda: state.screen == "main" and state.main_focus == "options" and not state.show_promo_menu and not state.show_confirm_no_meta)
_on_promo = Condition(lambda: state.show_promo_menu)
_on_confirm = Condition(lambda: state.show_confirm_no_meta)
_on_env_screen = Condition(lambda: state.screen == "env_status")
_on_env_status = Condition(lambda: state.screen == "env_status" and not state.editing and not state.show_env_confirm)
_on_env_members = Condition(lambda: state.screen == "env_status" and state.env_focus == "members" and not state.editing and not state.show_env_confirm)
_on_env_config = Condition(lambda: state.screen == "env_status" and state.env_focus == "config" and not state.editing and not state.show_env_confirm)
_on_env_confirm = Condition(lambda: state.show_env_confirm and not state.env_applying)
_on_env_confirm_done = Condition(lambda: state.show_env_confirm and not state.env_applying and bool(state.env_apply_log))


# -- Settings screen keys --

@kb.add("o", filter=_on_settings)
def _edit_org(event) -> None:
    state.edit_field = "org"
    state.editing = True
    edit_buffer.text = state.org
    edit_buffer.cursor_position = len(state.org)
    event.app.layout.focus(edit_buffer)


@kb.add("p", filter=_on_settings)
def _edit_project(event) -> None:
    state.edit_field = "project"
    state.editing = True
    edit_buffer.text = state.project
    edit_buffer.cursor_position = len(state.project)
    event.app.layout.focus(edit_buffer)


@kb.add("enter", filter=_editing)
def _confirm_edit(event) -> None:
    value = edit_buffer.text.strip()
    if value:
        if state.edit_field == "org":
            state.org = value
        elif state.edit_field == "project":
            state.project = value
        elif state.edit_field == "min_approvers":
            if value.isdigit() and int(value) > 0:
                current_env = state.env_tabs[state.env_tab_index]
                state.env_custom_min[current_env] = value
    state.editing = False


@kb.add("escape", filter=_editing)
def _cancel_edit(event) -> None:
    state.editing = False


@kb.add("enter", filter=_on_settings)
def _go_to_pat(event) -> None:
    state.screen = "pat"
    state.pat_status = ""
    pat_buffer.text = ""
    event.app.layout.focus(pat_buffer)


# -- PAT screen keys --

def _is_pat_valid(client: AdoClient) -> bool:
    """Check if PAT is valid using connectionData (requires no scopes).

    connectionData needs api-version with -preview flag, so we call
    _request directly to avoid get_org() which appends non-preview version.
    """
    url = f"https://dev.azure.com/{client.org}/_apis/connectionData?api-version=7.1-preview"
    try:
        client._request("GET", url)
        return True
    except AdoApiError:
        return False
    except Exception:
        return False


def _check_pat_scopes(client: AdoClient) -> list[str]:
    """Probe ADO API endpoints to detect missing PAT scopes.

    Returns a list of human-readable scope names that are missing.
    Each scope is tested by calling a lightweight read-only endpoint.
    A 401/403 or a non-JSON 203 response means the scope is not granted.
    """
    missing: list[str] = []

    # Project & Team (Read) — query project info
    try:
        client.get_org(f"_apis/projects/{client.project}")
    except AdoApiError as exc:
        if exc.status_code in (401, 403):
            missing.append("Project & Team (Read)")
    except Exception:
        missing.append("Project & Team (Read)")

    # Build (Read & execute) — list build definitions
    try:
        client.get("_apis/build/definitions?$top=1")
    except AdoApiError as exc:
        if exc.status_code in (401, 403):
            missing.append("Build (Read & execute)")
    except Exception:
        missing.append("Build (Read & execute)")

    # Environment (Read & manage) — list environments
    try:
        client.get("_apis/pipelines/environments?$top=1", preview=True)
    except AdoApiError as exc:
        if exc.status_code in (401, 403):
            missing.append("Environment (Read & manage)")
    except Exception:
        missing.append("Environment (Read & manage)")

    # Member Entitlement Management (Read) — list user entitlements
    try:
        client.get_vsaex("_apis/userentitlements?$top=1")
    except AdoApiError as exc:
        if exc.status_code in (401, 403):
            missing.append("Member Entitlement Management (Read)")
    except Exception:
        missing.append("Member Entitlement Management (Read)")

    return missing


@kb.add("enter", filter=_on_pat)
def _validate_pat(event) -> None:
    pat = pat_buffer.text.strip()
    if not pat:
        return
    state.pat_status = "validating"
    state.missing_scopes = []

    app = event.app

    def _clear_status() -> None:
        state.pat_status = ""
        state.missing_scopes = []
        app.invalidate()

    def _run_validation() -> None:
        try:
            client = AdoClient(state.org, state.project, pat)

            # Step 1: Check if PAT is valid at all (no scope needed)
            if not _is_pat_valid(client):
                state.pat_status = "fail"
                app.invalidate()
                threading.Timer(1.5, _clear_status).start()
                return

            state.client = client
            state.pat_valid = True
            state.pat_status = "scope_check"
            app.invalidate()

            # Step 2: Check individual scopes
            missing = _check_pat_scopes(client)
            state.missing_scopes = missing

            if not missing:
                state.pat_status = "scope_ok"
                app.invalidate()
                def _go_main() -> None:
                    state.screen = "main"
                    state.refresh_browse()
                    app.invalidate()
                threading.Timer(0.8, _go_main).start()
            else:
                state.pat_status = "scope_fail"
                app.invalidate()
        except Exception:
            state.pat_status = "fail"
            app.invalidate()
            threading.Timer(1.5, _clear_status).start()

    threading.Thread(target=_run_validation, daemon=True).start()


@kb.add("escape", filter=_on_pat)
def _back_to_settings(event) -> None:
    state.screen = "settings"
    state.pat_status = ""


# -- Main screen keys --

@kb.add("tab", filter=_on_main)
def _toggle_focus(event) -> None:
    state.main_focus = "options" if state.main_focus == "browser" else "browser"


# Browser navigation
@kb.add("up", filter=_on_browser)
def _browser_up(event) -> None:
    if state.browse_index > 0:
        state.browse_index -= 1
        if state.browse_index > 0 and state.browse_index - 1 < state.browse_scroll:
            state.browse_scroll = max(0, state.browse_index - 1)


@kb.add("down", filter=_on_browser)
def _browser_down(event) -> None:
    max_idx = len(state.browse_entries)
    if state.browse_index < max_idx:
        state.browse_index += 1
        max_visible = 15
        if state.browse_index > 0 and state.browse_index - 1 >= state.browse_scroll + max_visible:
            state.browse_scroll = state.browse_index - max_visible


@kb.add("enter", filter=_on_browser)
def _browser_enter(event) -> None:
    if state.browse_index == 0:
        parent = state.browse_path.parent
        if parent != state.browse_path:
            state.browse_path = parent
            state.refresh_browse()
    else:
        entry = state.browse_entries[state.browse_index - 1]
        if state.is_git_dir(entry):
            # Check for meta.yaml
            meta = _read_meta(entry)
            if meta is None:
                # No meta.yaml — ask for confirmation
                state._pending_repo = entry
                state.show_confirm_no_meta = True
            else:
                state.select_repo(entry)
        else:
            state.browse_path = entry
            state.refresh_browse()


# Confirm dialog (no meta.yaml)
@kb.add("y", filter=_on_confirm)
def _confirm_yes(event) -> None:
    state.show_confirm_no_meta = False
    entry = getattr(state, "_pending_repo", None)
    if entry:
        state.select_repo(entry)


@kb.add("n", filter=_on_confirm)
@kb.add("escape", filter=_on_confirm)
def _confirm_no(event) -> None:
    state.show_confirm_no_meta = False


# Cart navigation
@kb.add("up", filter=_on_cart)
def _cart_up(event) -> None:
    if state.cart_index > 0:
        state.cart_index -= 1


@kb.add("down", filter=_on_cart)
def _cart_down(event) -> None:
    can_continue = bool(state.cart_items) and state.selected_dir is not None
    max_idx = 3 if can_continue else 2
    if state.cart_index < max_idx:
        state.cart_index += 1


@kb.add("space", filter=_on_cart)
def _cart_toggle(event) -> None:
    if state.cart_index == 0:
        state.cart_main = not state.cart_main
    elif state.cart_index == 2:
        state.cart_overwrite = not state.cart_overwrite


@kb.add("enter", filter=_on_cart)
def _cart_enter(event) -> None:
    if state.cart_index == 0:
        state.cart_main = not state.cart_main
    elif state.cart_index == 1:
        state.show_promo_menu = True
        state.promo_index = 0
    elif state.cart_index == 2:
        state.cart_overwrite = not state.cart_overwrite
    elif state.cart_index == 3:
        # Continue — if promos selected, show env status; otherwise skip
        if state.cart_has_promo:
            state.env_tabs = ["qa", "stg", "prd"]
            state.env_tab_index = 0
            state.env_focus = "members"
            state.env_member_index = 0
            state.env_member_scroll = 0
            state.env_config_index = 0
            state.env_members = []
            state.env_members_loading = True
            state.env_status = {}
            state.env_loading = True
            state.env_checked = {}
            state.env_overwrite = {}
            state.env_custom_min = {}
            state.screen = "env_status"
            threading.Thread(
                target=_fetch_env_data, args=(event.app,), daemon=True
            ).start()
        else:
            # No promos selected — future install step
            pass


# Promotion submenu
@kb.add("up", filter=_on_promo)
def _promo_up(event) -> None:
    if state.promo_index > 0:
        state.promo_index -= 1


@kb.add("down", filter=_on_promo)
def _promo_down(event) -> None:
    if state.promo_index < 2:
        state.promo_index += 1


@kb.add("space", filter=_on_promo)
def _promo_toggle(event) -> None:
    keys = ["cart_promo_devqa", "cart_promo_qastg", "cart_promo_stgprd"]
    key = keys[state.promo_index]
    setattr(state, key, not getattr(state, key))


@kb.add("enter", filter=_on_promo)
def _promo_done(event) -> None:
    state.show_promo_menu = False


@kb.add("escape", filter=_on_promo)
def _promo_cancel(event) -> None:
    state.show_promo_menu = False


@kb.add("escape", filter=_on_main)
def _main_back(event) -> None:
    state.screen = "pat"
    pat_buffer.text = ""
    state.pat_status = ""
    event.app.layout.focus(pat_buffer)


# -- Environment status screen keys --

@kb.add("tab", filter=_on_env_status)
def _env_toggle_focus(event) -> None:
    state.env_focus = "config" if state.env_focus == "members" else "members"


@kb.add("[", filter=_on_env_status)
def _env_tab_prev(event) -> None:
    if state.env_tab_index > 0:
        state.env_tab_index -= 1


@kb.add("]", filter=_on_env_status)
def _env_tab_next(event) -> None:
    if state.env_tab_index < len(state.env_tabs) - 1:
        state.env_tab_index += 1


# Members navigation
@kb.add("up", filter=_on_env_members)
def _env_member_up(event) -> None:
    if state.env_member_index > 0:
        state.env_member_index -= 1
        if state.env_member_index < state.env_member_scroll:
            state.env_member_scroll = state.env_member_index


@kb.add("down", filter=_on_env_members)
def _env_member_down(event) -> None:
    if state.env_member_index < len(state.env_members) - 1:
        state.env_member_index += 1
        max_visible = 16
        if state.env_member_index >= state.env_member_scroll + max_visible:
            state.env_member_scroll = state.env_member_index - max_visible + 1


@kb.add("space", filter=_on_env_members)
@kb.add("enter", filter=_on_env_members)
def _env_member_toggle(event) -> None:
    if not state.env_members:
        return
    current_env = state.env_tabs[state.env_tab_index]
    member = state.env_members[state.env_member_index]
    checked = state.env_checked.setdefault(current_env, set())
    if member["id"] in checked:
        checked.discard(member["id"])
    else:
        checked.add(member["id"])


# Config navigation
@kb.add("up", filter=_on_env_config)
def _env_config_up(event) -> None:
    if state.env_config_index > 0:
        state.env_config_index -= 1


@kb.add("down", filter=_on_env_config)
def _env_config_down(event) -> None:
    if state.env_config_index < 2:
        state.env_config_index += 1


@kb.add("space", filter=_on_env_config)
def _env_config_toggle(event) -> None:
    if state.env_config_index == 0:
        current_env = state.env_tabs[state.env_tab_index]
        state.env_overwrite[current_env] = not state.env_overwrite.get(current_env, False)


@kb.add("enter", filter=_on_env_config)
def _env_config_enter(event) -> None:
    if state.env_config_index == 0:
        current_env = state.env_tabs[state.env_tab_index]
        state.env_overwrite[current_env] = not state.env_overwrite.get(current_env, False)
    elif state.env_config_index == 1:
        current_env = state.env_tabs[state.env_tab_index]
        current_min = state.env_custom_min.get(current_env, "1")
        state.edit_field = "min_approvers"
        state.editing = True
        edit_buffer.text = current_min
        edit_buffer.cursor_position = len(current_min)
        event.app.layout.focus(edit_buffer)
    elif state.env_config_index == 2:
        # Continue — show confirmation dialog
        state.show_env_confirm = True
        state.env_applying = False
        state.env_apply_log = []


# Env confirm dialog
@kb.add("y", filter=_on_env_confirm & ~_on_env_confirm_done)
def _env_confirm_yes(event) -> None:
    state.env_applying = True
    state.env_apply_log = []
    threading.Thread(
        target=_apply_env_settings, args=(event.app,), daemon=True
    ).start()


@kb.add("n", filter=_on_env_confirm & ~_on_env_confirm_done)
@kb.add("escape", filter=_on_env_confirm & ~_on_env_confirm_done)
def _env_confirm_no(event) -> None:
    state.show_env_confirm = False
    state.env_apply_log = []


@kb.add("enter", filter=_on_env_confirm_done)
def _env_confirm_ok(event) -> None:
    state.show_env_confirm = False
    state.env_apply_log = []


@kb.add("escape", filter=_on_env_status)
def _env_status_back(event) -> None:
    state.screen = "main"


@kb.add("q", filter=_on_env_status)
def _env_status_quit(event) -> None:
    event.app.exit()


# -- Global keys --

@kb.add("q", filter=_on_settings)
@kb.add("q", filter=_on_main)
@kb.add("c-q")
def _quit(event) -> None:
    event.app.exit()


# -- Layout ------------------------------------------------------------------

# Top
logo_window = Window(
    FormattedTextControl(_get_logo_text),
    height=8,
    align=WindowAlign.CENTER,
)

title_bar = Window(
    FormattedTextControl(_get_title_bar_text),
    height=1,
    style="class:title-bar",
)

# Settings screen
settings_content = Frame(
    HSplit([
        Window(FormattedTextControl(_get_settings_text), height=5),
        Window(height=1, char="\u2500", style="class:separator"),
        Window(FormattedTextControl(_get_settings_keys), height=1),
    ]),
    title="Connection",
    style="class:frame",
)

settings_panel = ConditionalContainer(
    HSplit([Window(height=1), settings_content]),
    filter=Condition(lambda: state.screen == "settings"),
)

# PAT screen
pat_input_row = VSplit([
    Window(
        FormattedTextControl(lambda: [("class:input-label", "  \u276f PAT  ")]),
        width=10, style="class:input",
    ),
    Window(
        BufferControl(buffer=pat_buffer, input_processors=[PasswordProcessor()]),
        style="class:input",
    ),
])

pat_content = Frame(
    HSplit([
        Window(FormattedTextControl(_get_pat_text)),
        Window(height=1, char="\u2500", style="class:separator"),
        pat_input_row,
        Window(height=1, char="\u2500", style="class:separator"),
        Window(FormattedTextControl(_get_pat_keys), height=1),
    ]),
    title="Authentication",
    style="class:frame",
)

pat_panel = ConditionalContainer(
    HSplit([Window(height=1), pat_content]),
    filter=_on_pat,
)

# Main screen
browser_frame = Frame(
    Window(FormattedTextControl(_get_browser_text)),
    title="Select Git Repository",
    style="class:frame",
)

cart_frame = Frame(
    Window(FormattedTextControl(_get_cart_text)),
    title="Pipelines",
    style="class:frame",
)

main_split = VSplit([
    HSplit([browser_frame], width=D(weight=6)),
    Window(width=1, char="\u2502", style="class:separator"),
    HSplit([cart_frame], width=D(weight=4)),
])

main_keys_bar = Window(FormattedTextControl(_get_main_keys), height=1)

main_panel = ConditionalContainer(
    HSplit([
        main_split,
        Window(height=1, char="\u2500", style="class:separator"),
        main_keys_bar,
    ]),
    filter=Condition(lambda: state.screen == "main"),
)

# Environment status screen
env_tab_bar = Window(
    FormattedTextControl(_get_env_tab_bar_text),
    height=1,
)

env_members_frame = Frame(
    Window(FormattedTextControl(_get_env_members_text)),
    title="Project Members",
    style="class:frame",
)

env_config_frame = Frame(
    Window(FormattedTextControl(_get_env_config_text)),
    title="Configuration",
    style="class:frame",
)

env_split = VSplit([
    HSplit([env_members_frame], width=D(weight=5)),
    Window(width=1, char="\u2502", style="class:separator"),
    HSplit([env_config_frame], width=D(weight=5)),
])

env_keys_bar = Window(FormattedTextControl(_get_env_status_keys), height=1)

env_status_panel = ConditionalContainer(
    HSplit([
        env_tab_bar,
        Window(height=1, char="\u2500", style="class:separator"),
        env_split,
        Window(height=1, char="\u2500", style="class:separator"),
        env_keys_bar,
    ]),
    filter=_on_env_screen,
)

# Status bar
status_bar = Window(
    FormattedTextControl(_get_status_text),
    height=1,
    style="class:status",
)

# Floating dialogs
edit_dialog_content = Frame(
    Window(BufferControl(buffer=edit_buffer), height=1, style="class:input"),
    title=_get_edit_title,
    style="class:dialog",
)

edit_float = Float(
    ConditionalContainer(Shadow(edit_dialog_content), filter=_editing),
    left=4, top=9, width=55,
)

promo_float = Float(
    ConditionalContainer(
        Shadow(Frame(
            Window(FormattedTextControl(_get_promo_menu_text), height=10),
            title="Promotion Pipelines",
            style="class:dialog",
        )),
        filter=_on_promo,
    ),
    right=3, top=12, width=40,
)

confirm_float = Float(
    ConditionalContainer(
        Shadow(Frame(
            Window(FormattedTextControl(_get_confirm_text), height=10),
            title="Confirm",
            style="class:dialog",
        )),
        filter=_on_confirm,
    ),
    left=5, top=12, width=40,
)

env_confirm_float = Float(
    ConditionalContainer(
        Shadow(Frame(
            Window(FormattedTextControl(_get_env_confirm_text)),
            title="Apply Settings",
            style="class:dialog",
        )),
        filter=Condition(lambda: state.show_env_confirm),
    ),
    left=8, top=12, width=45,
)

# Main layout
body = HSplit([
    logo_window,
    title_bar,
    settings_panel,
    pat_panel,
    main_panel,
    env_status_panel,
    Window(),
    status_bar,
])

root = FloatContainer(content=body, floats=[edit_float, promo_float, confirm_float, env_confirm_float])
layout = Layout(root)

application = Application(
    layout=layout,
    key_bindings=kb,
    style=STYLE,
    full_screen=True,
    mouse_support=True,
)


# -- Entry -------------------------------------------------------------------

def main() -> None:
    application.run()


if __name__ == "__main__":
    main()
