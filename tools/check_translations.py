import ast
import io
import os
import sys
import tokenize
from collections import OrderedDict


"""
CLI utility that reports which translatable strings in `src/` are missing from
`l10n/messages.pot` (and which entries in the .pot no longer exist in the code).

Why this exists:
    The .pot file is normally regenerated with `python setup.py extract_messages`,
    which needs Babel. This script needs nothing outside the standard library, so the
    catalog can be kept honest in environments where Babel is not available, and it
    gives a quick way to answer "did I forget to mark a string?".

    It is a checker, not a replacement for Babel. `extract_messages` remains the
    source of truth; run it when you can.

Usage:
    python tools/check_translations.py           # report only; exits 1 if out of date
    python tools/check_translations.py --append  # append the missing entries to the .pot

What it mirrors from setup.cfg:
    keywords     = _ _mft mark_for_translation ButtonOption
    add_comments = TRANSLATOR_NOTE:
    add_location = file      (locations are filenames, no line numbers)
    input_dirs   = src
"""


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(REPO_ROOT, "src")
POT_PATH = os.path.join(REPO_ROOT, "l10n", "messages.pot")

# Only the FIRST positional argument of each of these is extracted, matching Babel's
# default behavior for the keywords listed in setup.cfg.
KEYWORDS = {"_", "_mft", "mark_for_translation", "ButtonOption"}

# setup.cfg's `keywords` does not displace Babel's built-in gettext keywords, so plural
# calls are extracted too -- the catalog contains their entries. `ngettext` is the only
# one this codebase uses; its 1st arg is the msgid and its 2nd the msgid_plural.
PLURAL_KEYWORDS = {"ngettext"}

COMMENT_TAG = "TRANSLATOR_NOTE:"


def iter_python_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def get_called_name(func: ast.AST) -> str:
    """ The bare name for `foo(...)` and for `mod.foo(...)`. """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def collect_comments(source: str) -> dict:
    """ line number -> TRANSLATOR_NOTE text, for comments carrying the tag. """
    comments = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token_type, token_string, start, _end, _line in tokens:
            if token_type != tokenize.COMMENT:
                continue
            text = token_string.lstrip("#").strip()
            if text.startswith(COMMENT_TAG):
                comments[start[0]] = text[len(COMMENT_TAG):].strip()
    except (tokenize.TokenError, IndentationError):
        pass
    return comments


def comment_for(call_line: int, comments: dict) -> str:
    """
        Babel attaches a tagged comment that sits on the lines immediately above the
        call. Walk upward across contiguous tagged comment lines and join them.
    """
    collected = []
    line = call_line - 1
    while line in comments:
        collected.insert(0, comments[line])
        line -= 1
    return " ".join(collected)


def extract_from_file(path: str) -> list:
    """ Returns (msgid, msgid_plural, translator_comment) tuples found in one file. """
    with open(path, encoding="utf-8") as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"  !! could not parse {path}: {e}", file=sys.stderr)
        return []

    comments = collect_comments(source)
    found = []

    def literal(arg) -> str:
        # Babel can only extract literal strings; anything computed is skipped.
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = get_called_name(node.func)
        if called not in KEYWORDS and called not in PLURAL_KEYWORDS:
            continue
        if not node.args:
            continue

        msgid = literal(node.args[0])
        if msgid is None:
            continue

        msgid_plural = None
        if called in PLURAL_KEYWORDS and len(node.args) > 1:
            msgid_plural = literal(node.args[1])

        found.append((msgid, msgid_plural, comment_for(node.lineno, comments)))

    return found


def parse_pot_msgids(path: str) -> set:
    """ Every msgid in the .pot, including multi-line ones. The header's "" is skipped. """
    msgids = set()
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("msgid "):
            parts = [ast.literal_eval(line[len("msgid "):].strip())]
            index += 1
            # Continuation lines are bare quoted strings.
            while index < len(lines) and lines[index].startswith('"'):
                parts.append(ast.literal_eval(lines[index].strip()))
                index += 1
            msgid = "".join(parts)
            if msgid:
                msgids.add(msgid)
            continue
        index += 1

    return msgids


def po_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def format_entry(msgid: str, comment: str, locations: list, msgid_plural: str = None) -> str:
    out = ""
    if comment:
        out += f"#. {comment}\n"
    out += f"#: {' '.join(sorted(locations))}\n"
    out += f'msgid "{po_escape(msgid)}"\n'
    if msgid_plural:
        out += f'msgid_plural "{po_escape(msgid_plural)}"\n'
        out += 'msgstr[0] ""\nmsgstr[1] ""\n'
    else:
        out += 'msgstr ""\n'
    return out


def main() -> int:
    append = "--append" in sys.argv[1:]

    # msgid -> [comment, {relative file paths}, msgid_plural or None]
    extracted = OrderedDict()
    for path in sorted(iter_python_files(INPUT_DIR)):
        relative_path = os.path.relpath(path, REPO_ROOT)
        for msgid, msgid_plural, comment in extract_from_file(path):
            if not msgid:
                continue
            if msgid not in extracted:
                extracted[msgid] = [comment, set(), msgid_plural]
            extracted[msgid][1].add(relative_path)
            # Keep the first non-empty comment we see, as Babel does.
            if comment and not extracted[msgid][0]:
                extracted[msgid][0] = comment
            if msgid_plural and not extracted[msgid][2]:
                extracted[msgid][2] = msgid_plural

    in_pot = parse_pot_msgids(POT_PATH)
    missing = [msgid for msgid in extracted if msgid not in in_pot]
    obsolete = sorted(in_pot - set(extracted))

    print(f"extracted from src/: {len(extracted)} strings")
    print(f"present in {os.path.relpath(POT_PATH, REPO_ROOT)}: {len(in_pot)} strings")

    if missing:
        print(f"\nMISSING from the catalog ({len(missing)}):")
        for msgid in missing:
            comment, locations, _plural = extracted[msgid]
            print(f"  {msgid!r}")
            print(f"      in {', '.join(sorted(locations))}")
            if comment:
                print(f"      note: {comment}")

    if obsolete:
        print(f"\nIn the catalog but no longer in src/ ({len(obsolete)}):")
        for msgid in obsolete:
            print(f"  {msgid!r}")

    if not missing and not obsolete:
        print("\nCatalog is up to date.")
        return 0

    if append and missing:
        with open(POT_PATH, "a", encoding="utf-8") as f:
            for msgid in missing:
                comment, locations, msgid_plural = extracted[msgid]
                f.write("\n" + format_entry(msgid, comment, sorted(locations), msgid_plural))
        print(f"\nAppended {len(missing)} entries to {os.path.relpath(POT_PATH, REPO_ROOT)}.")
        print("Obsolete entries are left alone; run Babel's extract_messages to prune them.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
