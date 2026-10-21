"""Contract-configured hard-rule extensions (v0.4).

Three optional contract fields, all covered by the contract hash:

  argument_rules   per tool: which argument names are allowed and full-match
                   regexes for argument values.
                     {"transfer_funds": {"allowed_args": ["amount", "to_account"],
                                         "patterns": {"to_account": "\\d{4}"},
                                         "max_length": 64}}
  confirm_above    inside parameter_constraints: values above it need a human
                   confirmation (NEEDS_CONFIRMATION) instead of executing.
  deny_patterns    opt-in regex heuristics matched against the user message:
                   shipped packs, the contract's own regexes, and a list of
                   prohibited terms (whole word, case-insensitive).
                     {"packs": ["role_reassignment", {"name": "objective_override", "action": "warn"}],
                      "custom": [{"id": "crypto", "regex": "\\bcrypto\\b", "action": "block"}],
                      "prohibited_terms": {"terms": ["tax return"], "action": "block"}}

Deny patterns are heuristics: they catch explicit wording and miss rewordings.
Everything here is deterministic; nothing uses embeddings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "ACTIONS",
    "DEFAULT_MAX_ARGUMENT_LENGTH",
    "DENY_PATTERN_PACKS",
    "MAX_PATTERN_LENGTH",
    "ArgumentRule",
    "DenyPatternConfig",
    "DenyRule",
    "check_argument_rules",
    "confirmation_reason",
    "deny_pattern_matches",
    "parse_argument_rules",
    "parse_deny_patterns",
]

MAX_PATTERN_LENGTH = 500  # characters per regex in a contract
DEFAULT_MAX_ARGUMENT_LENGTH = 1024  # characters of an argument value a pattern is run against
MAX_TERM_LENGTH = 200
ACTIONS = ("block", "warn")
_PATTERN_ID = re.compile(r"[a-z0-9_]{1,64}")

# Shipped packs. Heuristics: explicit instruction-override wording only.
DENY_PATTERN_PACKS: dict[str, dict[str, str]] = {
    "role_reassignment": {
        "you_are_now": r"\byou(?:'re| are) (?:now|my)\b",
        "you_are_a_role_now": r"\byou(?:'re| are) (?:a|an|the) [\w-]+(?: [\w-]+)? now\b",
        "from_now_on": r"\bfrom now on\b",
        "switch_roles": r"\bswitch(?:ing)? roles?\b",
        "act_as": r"\b(?:act|behave|talk|respond|answer)(?: to me)? (?:as|like)\b",
        "pretend": r"\bpretend(?:ing)? (?:to be|you(?:'re| are))\b",
        "roleplay": r"\brole-?play\b",
        "be_a_role": r"\bbe (?:my|a|an) [\w-]+",
        "drop_persona": r"\bdrop the [\w-]+ (?:persona|act)\b",
        "as_my_role": r"\bas (?:my|your) (?:[\w-]+ ){0,2}(?:advisor|adviser|accountant|attorney|counsel|lawyer|therapist|buddy|friend|doctor|self)\b",
    },
    "objective_override": {
        "your_new_goal": r"\byour (?:new )?(?:goal|objective|mission|job|task|priority)\b",
        "make_it_your_job": r"\bmake it your (?:job|goal|mission)\b",
        "stop_or_forget": r"^\s*(?:stop|forget)\b",
        "instead_of_task": r"\binstead of (?:handling|helping|summari[sz]ing|troubleshooting|fixing|reviewing|processing)\b",
    },
    "guardrail_removal": {
        "unfiltered": r"\bunfiltered\b",
        "no_restrictions": r"\bno[- ](?:restrictions|rules|disclaimers|limits)\b",
        "skip_verification": r"\bwithout (?:the usual |any )?(?:verification|verifying|checks)\b",
        "bypass": r"\bbypass\b",
        "disable_security": r"\b(?:turn off|disable)\b.{0,40}\b(?:two-factor|2fa|authentication|security)\b",
    },
}


def _normalize_tool_name(name: str) -> str:
    """Same matching rule as the forbidden/allowed tool checks."""
    return (name or "").strip().lower().replace(" ", "_").replace("-", "_")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compile(pattern: Any, where: str, problems: list[str], flags: int = 0) -> re.Pattern[str] | None:
    if not isinstance(pattern, str) or not pattern:
        problems.append(f"{where}: must be a non-empty regex string")
        return None
    if len(pattern) > MAX_PATTERN_LENGTH:
        problems.append(f"{where}: regex is {len(pattern)} characters, the limit is {MAX_PATTERN_LENGTH}")
        return None
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        problems.append(f"{where}: invalid regex ({exc})")
        return None


def _action(value: Any, where: str, problems: list[str]) -> str:
    if value is None:
        return "block"
    if value not in ACTIONS:
        problems.append(f"{where}: action must be one of {list(ACTIONS)}, got {value!r}")
        return "block"
    return value


# ── argument_rules ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArgumentRule:
    tool: str
    allowed_args: frozenset[str] | None
    patterns: tuple[tuple[str, re.Pattern[str]], ...]
    max_length: int
    raw_json: str = field(repr=False, compare=False)  # original spec, for an exact to_dict() round trip


def parse_argument_rules(
    raw: Any, *, allowed_actions: tuple[str, ...] = (), problems: list[str] | None = None
) -> tuple[ArgumentRule, ...]:
    """Validate and compile contract["argument_rules"]. Problems are appended to
    ``problems`` (or raised as ValueError when it is None)."""
    collect = problems if problems is not None else []
    rules = _parse_argument_rules(raw, allowed_actions, collect)
    if problems is None and collect:
        raise ValueError("; ".join(collect))
    return rules


def _parse_argument_rules(raw: Any, allowed_actions: tuple[str, ...], problems: list[str]) -> tuple[ArgumentRule, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Mapping) or not raw:
        problems.append("argument_rules: must be a non-empty object mapping tool names to rules")
        return ()
    allowed_norm = {_normalize_tool_name(a) for a in allowed_actions}
    seen: dict[str, str] = {}
    rules: list[ArgumentRule] = []
    for tool, spec in raw.items():
        where = f"argument_rules.{tool}"
        norm = _normalize_tool_name(str(tool))
        if norm in seen:
            problems.append(f"{where}: duplicates argument_rules.{seen[norm]} (tool names are matched case-insensitively)")
            continue
        seen[norm] = str(tool)
        if allowed_norm and norm not in allowed_norm:
            problems.append(f"{where}: {tool!r} is not in allowed_actions, so this rule could never apply")
        if not isinstance(spec, Mapping):
            problems.append(f"{where}: must be an object with allowed_args and/or patterns")
            continue
        unknown = set(spec) - {"allowed_args", "patterns", "max_length"}
        if unknown:
            problems.append(f"{where}: unknown keys {sorted(unknown)} (expected allowed_args, patterns, max_length)")
        if "allowed_args" not in spec and "patterns" not in spec:
            problems.append(f"{where}: needs allowed_args and/or patterns")

        allowed_args: frozenset[str] | None = None
        if "allowed_args" in spec:
            args = spec["allowed_args"]
            if not isinstance(args, list) or not all(isinstance(a, str) and a for a in args):
                problems.append(f"{where}.allowed_args: must be a list of argument names")
            elif len(set(args)) != len(args):
                problems.append(f"{where}.allowed_args: contains duplicates")
            else:
                allowed_args = frozenset(args)

        patterns: list[tuple[str, re.Pattern[str]]] = []
        if "patterns" in spec:
            pats = spec["patterns"]
            if not isinstance(pats, Mapping) or not pats:
                problems.append(f"{where}.patterns: must be a non-empty object mapping argument names to regexes")
            else:
                for arg, pattern in pats.items():
                    if allowed_args is not None and arg not in allowed_args:
                        problems.append(f"{where}.patterns.{arg}: argument is not in allowed_args")
                    compiled = _compile(pattern, f"{where}.patterns.{arg}", problems)
                    if compiled is not None:
                        patterns.append((str(arg), compiled))

        max_length = DEFAULT_MAX_ARGUMENT_LENGTH
        if "max_length" in spec:
            ml = spec["max_length"]
            if isinstance(ml, bool) or not isinstance(ml, int) or ml < 1:
                problems.append(f"{where}.max_length: must be a positive integer")
            else:
                max_length = ml

        rules.append(ArgumentRule(str(tool), allowed_args, tuple(patterns), max_length, _canonical(spec)))
    return tuple(rules)


def check_argument_rules(rules: tuple[ArgumentRule, ...], tool_name: str, arguments: Mapping[str, Any]) -> str | None:
    """BLOCK reason for the first violated argument rule, or None."""
    planned = _normalize_tool_name(tool_name)
    for rule in rules:
        if _normalize_tool_name(rule.tool) != planned:
            continue
        if rule.allowed_args is not None:
            for arg in arguments:
                if arg not in rule.allowed_args:
                    return f"argument_not_allowed:{rule.tool}:{arg}"
        for arg, pattern in rule.patterns:
            if arg in arguments and not _value_matches(arguments[arg], pattern, rule.max_length):
                return f"argument_pattern:{rule.tool}:{arg}"
    return None


def _as_text(value: Any) -> str | None:
    """Strings as-is; ints/floats by their decimal form (models often emit account
    numbers as JSON numbers); anything else (bool, None, dict, ...) has no text."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _value_matches(value: Any, pattern: re.Pattern[str], max_length: int) -> bool:
    """A string or number must full-match; a list/tuple matches if every element
    does; any other type, or text longer than max_length, does not match."""
    items = value if isinstance(value, (list, tuple)) else [value]
    for item in items:
        text = _as_text(item)
        if text is None or len(text) > max_length or pattern.fullmatch(text) is None:
            return False
    return True


# ── confirm_above ───────────────────────────────────────────────────────────


def confirmation_reason(constraints: Any, arguments: Mapping[str, Any]) -> str | None:
    """'confirm_above:<param>' for the first argument above its confirm_above, else None.

    Runs after the hard limits, so values here are already numeric and within min/max.
    """
    for c in constraints:
        if c.confirm_above is None or c.name not in arguments:
            continue
        try:
            value = float(arguments[c.name])
        except (TypeError, ValueError):
            continue
        if value > float(c.confirm_above):
            return f"confirm_above:{c.name}"
    return None


# ── deny_patterns ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DenyRule:
    pack: str  # shipped pack name, "custom" or "prohibited_terms"
    pattern_id: str
    regex: re.Pattern[str]
    action: str  # "block" | "warn"

    @property
    def reason(self) -> str:
        return f"deny_pattern:{self.pack}:{self.pattern_id}"


@dataclass(frozen=True)
class DenyPatternConfig:
    rules: tuple[DenyRule, ...]
    raw_json: str = field(repr=False, compare=False)


def _term_id(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_")[:64] or "term"


def _term_regex(term: str) -> str:
    words = [re.escape(w) for w in term.split()]
    return r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)"


def parse_deny_patterns(raw: Any, *, problems: list[str] | None = None) -> DenyPatternConfig | None:
    collect = problems if problems is not None else []
    config = _parse_deny_patterns(raw, collect)
    if problems is None and collect:
        raise ValueError("; ".join(collect))
    return config


def _parse_deny_patterns(raw: Any, problems: list[str]) -> DenyPatternConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or not raw:
        problems.append("deny_patterns: must be a non-empty object with packs, custom and/or prohibited_terms")
        return None
    unknown = set(raw) - {"packs", "custom", "prohibited_terms"}
    if unknown:
        problems.append(f"deny_patterns: unknown keys {sorted(unknown)} (expected packs, custom, prohibited_terms)")
    rules: list[DenyRule] = []
    flags = re.IGNORECASE

    packs = raw.get("packs")
    if packs is not None:
        if not isinstance(packs, list) or not packs:
            problems.append("deny_patterns.packs: must be a non-empty list of pack names or {name, action} objects")
        else:
            seen: set[str] = set()
            for i, entry in enumerate(packs):
                where = f"deny_patterns.packs[{i}]"
                if isinstance(entry, str):
                    name, action = entry, "block"
                elif isinstance(entry, Mapping) and set(entry) <= {"name", "action"} and "name" in entry:
                    name, action = entry["name"], _action(entry.get("action"), where, problems)
                else:
                    problems.append(f"{where}: must be a pack name or {{\"name\": ..., \"action\": \"block\"|\"warn\"}}")
                    continue
                if name not in DENY_PATTERN_PACKS:
                    problems.append(f"{where}: unknown pack {name!r}; shipped packs: {sorted(DENY_PATTERN_PACKS)}")
                    continue
                if name in seen:
                    problems.append(f"{where}: pack {name!r} listed twice")
                    continue
                seen.add(name)
                for pid, pattern in DENY_PATTERN_PACKS[name].items():
                    rules.append(DenyRule(name, pid, re.compile(pattern, flags), action))

    custom = raw.get("custom")
    if custom is not None:
        if not isinstance(custom, list) or not custom:
            problems.append("deny_patterns.custom: must be a non-empty list of {id, regex, action} objects")
        else:
            ids: set[str] = set()
            for i, entry in enumerate(custom):
                where = f"deny_patterns.custom[{i}]"
                if not isinstance(entry, Mapping) or not {"id", "regex"} <= set(entry) or set(entry) - {"id", "regex", "action"}:
                    problems.append(f"{where}: must be an object with id, regex and optional action")
                    continue
                pid = entry["id"]
                if not isinstance(pid, str) or not _PATTERN_ID.fullmatch(pid):
                    problems.append(f"{where}.id: must match [a-z0-9_]{{1,64}}, got {pid!r}")
                    continue
                if pid in ids:
                    problems.append(f"{where}.id: duplicate id {pid!r}")
                    continue
                ids.add(pid)
                action = _action(entry.get("action"), where, problems)
                compiled = _compile(entry["regex"], f"{where}.regex", problems, flags)
                if compiled is None:
                    continue
                if compiled.search("") is not None:
                    problems.append(f"{where}.regex: matches the empty string, so it would match every message")
                    continue
                rules.append(DenyRule("custom", pid, compiled, action))

    terms_spec = raw.get("prohibited_terms")
    if terms_spec is not None:
        where = "deny_patterns.prohibited_terms"
        if not isinstance(terms_spec, Mapping) or "terms" not in terms_spec or set(terms_spec) - {"terms", "action"}:
            problems.append(f"{where}: must be an object {{\"terms\": [...], \"action\": \"block\"|\"warn\"}}")
        else:
            action = _action(terms_spec.get("action"), where, problems)
            terms = terms_spec["terms"]
            if not isinstance(terms, list) or not terms:
                problems.append(f"{where}.terms: must be a non-empty list of words or phrases")
            else:
                ids = set()
                for j, term in enumerate(terms):
                    if not isinstance(term, str) or not term.strip() or len(term) > MAX_TERM_LENGTH:
                        problems.append(f"{where}.terms[{j}]: must be a non-empty phrase of at most {MAX_TERM_LENGTH} characters")
                        continue
                    tid = _term_id(term)
                    if tid in ids:
                        problems.append(f"{where}.terms[{j}]: {term!r} duplicates another term")
                        continue
                    ids.add(tid)
                    rules.append(DenyRule("prohibited_terms", tid, re.compile(_term_regex(term), flags), action))

    return DenyPatternConfig(tuple(rules), _canonical(raw))


def deny_pattern_matches(config: DenyPatternConfig | None, message: str) -> tuple[str | None, tuple[str, ...]]:
    """(first BLOCK reason or None, all WARN reasons) for the user message."""
    if config is None or not message:
        return None, ()
    warnings: list[str] = []
    for rule in config.rules:
        if rule.regex.search(message) is None:
            continue
        if rule.action == "block":
            return rule.reason, tuple(warnings)
        warnings.append(rule.reason)
    return None, tuple(warnings)
