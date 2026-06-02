from __future__ import annotations

import sys
import time
import shutil
import os
import termios
import tty
from threading import Event, Thread
from collections.abc import Callable


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
BRIGHT_CYAN = "\033[96m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
BRIGHT_MAGENTA = "\033[95m"
GREEN = "\033[32m"
BRIGHT_GREEN = "\033[92m"
YELLOW = "\033[33m"
WHITE = "\033[97m"
GRAY = "\033[90m"


def startup_animation(enabled: bool = True) -> None:
    if not enabled or not sys.stdout.isatty():
        print("DeepSeek TuLAgent")
        return
    width = min(shutil.get_terminal_size((88, 24)).columns, 96)
    stages = [
        ("kernel", "load terminal runtime"),
        ("model", "bind DeepSeek flash route"),
        ("tools", "mount shell, files, patch, services"),
        ("skills", "scan local SKILL.md directories"),
        ("policy", "apply root approval profile"),
        ("session", "open conversation ledger"),
    ]
    capabilities = [
        ("READ", "files/search/git"),
        ("WRITE", "patch/create/edit"),
        ("SHELL", "commands/services"),
        ("NET", "download/model API"),
        ("SKILL", "local workflows"),
    ]

    print("\033[2J\033[H", end="")
    print(color("╭" + "─" * (width - 2) + "╮", BRIGHT_CYAN))
    print(center_line(color("DEEPSEEK", BRIGHT_CYAN + BOLD) + " " + color("TuLAGENT", BRIGHT_MAGENTA + BOLD), width))
    print(center_line(color("root fast boot", GREEN) + color(" · ", GRAY) + color("terminal coding cockpit", WHITE), width))
    print(color("├" + "─" * (width - 2) + "┤", BRIGHT_CYAN))
    for index, (name, detail) in enumerate(stages, 1):
        bar_width = max(width - 36, 12)
        filled = int(bar_width * index / len(stages))
        bar = color("█" * filled, stage_color(index)) + color("░" * (bar_width - filled), GRAY)
        line = " " + color(f"{name:<8}", stage_color(index) + BOLD) + " " + bar + " " + color(detail, DIM + WHITE)
        print(color("│", BRIGHT_CYAN) + pad_ansi(line, width - 2) + color("│", BRIGHT_CYAN), flush=True)
        time.sleep(0.09)
    print(color("├" + "─" * (width - 2) + "┤", BRIGHT_CYAN))
    print(center_line(color("capability matrix", YELLOW + BOLD), width))
    for left, right in zip(capabilities[::2], capabilities[1::2] + [("", "")]):
        left_text = capability(left[0], left[1]) if left[0] else ""
        right_text = capability(right[0], right[1]) if right[0] else ""
        print(color("│ ", BRIGHT_CYAN) + pad_ansi(f"{left_text}  {right_text}", width - 4) + color(" │", BRIGHT_CYAN))
    print(center_line(color("press ", GRAY) + color("/", YELLOW + BOLD) + color(" inside chat for commands and skills", GRAY), width))
    print(color("╰" + "─" * (width - 2) + "╯", BRIGHT_CYAN))
    time.sleep(0.12)


def confirm_tool(name: str, arguments: dict) -> bool:
    print(f"\nTool requires confirmation: {name}")
    for key, value in arguments.items():
        preview = str(value)
        if len(preview) > 500:
            preview = preview[:500] + "..."
        print(f"  {key}: {preview}")
    answer = input("type yes to approve> ").strip().lower()
    return answer == "yes"


class ThinkingSpinner:
    def __init__(self, label: str = "thinking"):
        self.label = label
        self.stop_event = Event()
        self.thread: Thread | None = None

    def __enter__(self):
        if not sys.stderr.isatty():
            return self
        self.thread = Thread(target=self._spin, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=0.2)
        if sys.stderr.isatty():
            print("\r" + " " * 60 + "\r", end="", file=sys.stderr, flush=True)

    def _spin(self) -> None:
        frames = ["thinking  ◐", "thinking  ◓", "thinking  ◑", "thinking  ◒"]
        index = 0
        while not self.stop_event.is_set():
            print("\r" + frames[index % len(frames)], end="", file=sys.stderr, flush=True)
            index += 1
            time.sleep(0.12)


def print_slash_palette(commands: list[tuple[str, str]], skills: list[tuple[str, str]]) -> None:
    print_box("Command Palette", [f"{name:<18} {description}" for name, description in commands])
    skill_lines = [f"/skill {name:<11} {description}" for name, description in skills] or ["none discovered"]
    print_box("Skills", skill_lines)


def print_tool_palette(tools: dict[str, str]) -> None:
    print_box("Tools", [f"{name:<16} {description}" for name, description in tools.items()])


def print_box(title: str, lines: list[str]) -> None:
    width = min(shutil.get_terminal_size((88, 24)).columns, 96)
    print(color("╭─ ", CYAN) + color(title, BOLD + WHITE) + color(" " + "─" * max(width - visible_len(title) - 5, 0) + "╮", CYAN))
    for line in lines:
        clipped = strip_ansi(line)[: max(width - 4, 1)] if visible_len(line) > width - 4 else line
        print(color("│ ", CYAN) + pad_ansi(clipped, width - 4) + color(" │", CYAN))
    print(color("╰" + "─" * (width - 2) + "╯", CYAN))


def center_line(text: str, width: int) -> str:
    inner = width - 2
    visible = visible_len(text)
    if visible > inner:
        text = strip_ansi(text)[:inner]
        visible = visible_len(text)
    left = (inner - visible) // 2
    right = inner - visible - left
    return color("│", BRIGHT_CYAN) + " " * left + text + " " * right + color("│", BRIGHT_CYAN)


def print_header(workspace: str, endpoint: str, model: str, mode: str, thinking: str, approval: str) -> None:
    lines = [
        label("workspace") + workspace,
        label("endpoint") + color(endpoint, BRIGHT_CYAN),
        label("model") + color(model, BRIGHT_GREEN if "flash" in model else BRIGHT_MAGENTA),
        label("mode") + color(mode, YELLOW if mode == "root" else GREEN),
        label("thinking") + color(thinking, BRIGHT_MAGENTA),
        label("approval") + color(approval, GREEN if approval == "all yes" else YELLOW),
    ]
    print_box("Session", lines)


def status_bar(model: str, mode: str, thinking: str, session_id: str | None = None) -> str:
    suffix = f" session={session_id}" if session_id else ""
    return (
        color("[model ", GRAY) + color(model, BRIGHT_GREEN if "flash" in model else BRIGHT_MAGENTA) + color("] ", GRAY)
        + color("[mode ", GRAY) + color(mode, YELLOW if mode == "root" else GREEN) + color("] ", GRAY)
        + color("[think ", GRAY) + color(thinking, BRIGHT_MAGENTA) + color("]", GRAY)
        + color(suffix, GRAY)
    )


def composer_prompt(model: str, mode: str, thinking: str, session_id: str | None = None) -> str:
    session = f" · {session_id[:8]}" if session_id else ""
    if sys.stdout.isatty() and not os.getenv("NO_COLOR"):
        return (
            color("▌ ", CYAN + BOLD)
            + color(f"{model}", BRIGHT_GREEN if "flash" in model else BRIGHT_MAGENTA)
            + color(f" {mode}/{thinking}{session}", GRAY)
            + color(" › ", CYAN + BOLD)
        )
    return f"[{model} {mode} {thinking}{session}] > "


def read_composer(prompt: str, slash_items: list[tuple[str, str]] | None = None) -> str:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return input(prompt)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buffer: list[str] = []
    try:
        tty.setraw(fd)
        sys.stdout.write(prompt)
        sys.stdout.flush()
        while True:
            char = sys.stdin.read(1)
            if char in {"\r", "\n"}:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)
            if char == "\x03":
                raise KeyboardInterrupt
            if char == "\x04":
                raise EOFError
            if char in {"\x7f", "\b"}:
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if char == "/" and not buffer and slash_items:
                sys.stdout.write("/\n")
                sys.stdout.flush()
                selected = slash_select(slash_items)
                if selected:
                    sys.stdout.write("\033[1F\033[2K\r")
                    sys.stdout.write(prompt + selected + "\n")
                    sys.stdout.flush()
                    return selected
                sys.stdout.write("\033[1F\033[2K\r")
                sys.stdout.write(prompt)
                sys.stdout.flush()
                continue
            if char.isprintable():
                buffer.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def slash_select(items: list[tuple[str, str]]) -> str | None:
    query = ""
    selected = 0
    last_lines = 0
    while True:
        filtered = filter_slash_items(items, query)
        if selected >= len(filtered):
            selected = 0
        last_lines = draw_slash_select(filtered, query, selected, last_lines)
        char = sys.stdin.read(1)
        if char in {"\r", "\n"}:
            if not filtered:
                clear_slash_select(last_lines)
                return None
            command = filtered[selected][0]
            clear_slash_select(last_lines)
            if command.startswith("/mode "):
                return command
            if command.startswith("/think "):
                return command
            if command in {"/models", "/doctor", "/skills", "/exit"}:
                return command
            return command
        if char == "\x1b":
            next_chars = sys.stdin.read(2)
            if next_chars == "[A":
                selected = max(0, selected - 1)
                continue
            if next_chars == "[B":
                selected = min(max(len(filtered) - 1, 0), selected + 1)
                continue
            clear_slash_select(last_lines)
            return None
        if char in {"\x7f", "\b"}:
            query = query[:-1]
            selected = 0
            continue
        if char == "\x03":
            raise KeyboardInterrupt
        if char.isprintable():
            query += char
            selected = 0


def filter_slash_items(items: list[tuple[str, str]], query: str) -> list[tuple[str, str]]:
    if not query:
        return items
    lowered = query.lower()
    command_matches = [
        item for item in items
        if item[0].lstrip("/").lower().startswith(lowered)
        or item[0].lower().startswith("/" + lowered)
    ]
    description_matches = [
        item for item in items
        if item not in command_matches and lowered in item[1].lower()
    ]
    return command_matches + description_matches


def draw_slash_select(items: list[tuple[str, str]], query: str, selected: int, previous_lines: int = 0) -> int:
    if previous_lines:
        sys.stdout.write(f"\033[{previous_lines}F")
        for _ in range(previous_lines):
            sys.stdout.write("\033[2K\r\033[1E")
        sys.stdout.write(f"\033[{previous_lines}F")
    sys.stdout.write("\033[2K\r")
    visible = items[:7]
    for index, (command, description) in enumerate(visible):
        desc = description[:62] + ("..." if len(description) > 62 else "")
        line = f"{command:<15} {desc}"
        if index == selected:
            line = color(line, BOLD + WHITE)
        else:
            line = color(line, GRAY)
        sys.stdout.write("  " + line + "\n")
    if not visible:
        sys.stdout.write("  " + color("no matches", GRAY) + "\n")
    sys.stdout.write("  " + color("enter run · ↑/↓ select · esc cancel", GRAY) + "\n")
    sys.stdout.flush()
    return 1 + max(len(visible), 1)


def clear_slash_select(lines: int) -> None:
    if not lines:
        return
    sys.stdout.write(f"\033[{lines}F")
    for _ in range(lines):
        sys.stdout.write("\033[2K\r\033[1E")
    sys.stdout.write(f"\033[{lines}F")
    sys.stdout.flush()


def assistant_prefix() -> str:
    if sys.stdout.isatty() and not os.getenv("NO_COLOR"):
        return color("assistant", BRIGHT_MAGENTA + BOLD) + color(" › ", GRAY)
    return "assistant> "


def color(text: str, code: str) -> str:
    if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
        return text
    return f"{code}{text}{RESET}"


def label(text: str) -> str:
    return color(f"{text:<10}", GRAY)


def capability(name: str, value: str) -> str:
    colors = {
        "READ": BRIGHT_CYAN,
        "WRITE": BRIGHT_MAGENTA,
        "SHELL": YELLOW,
        "NET": GREEN,
        "SKILL": BLUE,
    }
    return color(f"{name:<6}", colors.get(name, WHITE) + BOLD) + color(value.ljust(24), WHITE)


def stage_color(index: int) -> str:
    return [BRIGHT_CYAN, BRIGHT_GREEN, YELLOW, BRIGHT_MAGENTA, GREEN, BLUE][(index - 1) % 6]


def visible_len(text: str) -> int:
    return len(strip_ansi(text))


def strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)


def pad_ansi(text: str, width: int) -> str:
    visible = visible_len(text)
    if visible >= width:
        return text
    return text + " " * (width - visible)
