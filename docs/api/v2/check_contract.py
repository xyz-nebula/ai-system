"""Validate specification artifacts, not runtime or LLM quality.

Run with uv --with jsonschema --with openapi-spec-validator; see README.md.
"""

import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parent
VERSION = "2.0.0-rc.1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


SCHEMA = read(ROOT / "contract.schema.json")
DEFS = SCHEMA["$defs"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(items, label):
    require(len(items) == len(set(items)), f"Duplicate {label}")


def number(value):
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def instant(value):
    require(value.endswith("Z"), "UTC Z timestamp required")
    return datetime.fromisoformat(value)


def typed(value, term):
    kind = term["value_type"]
    if kind == "number":
        require(number(value), "Numeric value required, not boolean")
    elif kind == "boolean":
        require(isinstance(value, bool), "Boolean value required")
    else:
        require(isinstance(value, str) and value, "Nonempty string required")
        if kind == "choice":
            require(value in term["choices"], "Unknown choice")
        elif kind == "date":
            require(date.fromisoformat(value).isoformat() == value, "Invalid date")


def satisfies(rule, values):
    kind = rule["kind"]
    if kind == "linear":
        total = sum(
            Decimal(str(item["coefficient"])) * Decimal(str(values[item["term_id"]]))
            for item in rule["coefficients"]
        )
        bound = Decimal(str(rule["bound"]))
        return {"le": total <= bound, "ge": total >= bound, "eq": total == bound}[rule["relation"]]
    value = values[rule["term_id"]]
    if kind == "allowed_values":
        return any(
            (number(value) and number(candidate) or type(value) is type(candidate))
            and value == candidate
            for candidate in rule["values"]
        )
    if kind == "date_range":
        value = date.fromisoformat(value)
        low = date.fromisoformat(rule["minimum"]) if rule["minimum"] else None
        high = date.fromisoformat(rule["maximum"]) if rule["maximum"] else None
    else:
        low, high = rule["minimum"], rule["maximum"]
    return (low is None or value >= low) and (high is None or value <= high)


def check_terms(terms, config, step=None):
    catalogue = {term["id"]: term for term in config["negotiables"]}
    ids = [value["term_id"] for value in terms["values"]]
    unique(ids, "term values")
    require(set(ids) == set(catalogue), "Incomplete or unknown term values")
    values = {value["term_id"]: value["value"] for value in terms["values"]}
    for term_id, value in values.items():
        typed(value, catalogue[term_id])
    policy = config["agreement_policy"]
    rules = {rule["id"]: rule for rule in policy["constraints"]}
    active = policy["hard_constraint_ids"] + (step["constraint_ids"] if step else [])
    for rule_id in active:
        require(satisfies(rules[rule_id], values), f"Constraint violated: {rule_id}")
    roles = {config["player"]["role_id"], config["opponent"]["role_id"]}
    require(
        all(item["role_id"] in roles for item in terms["commitments"]),
        "Commitment belongs to inactive role",
    )
    require(terms["values"] or terms["commitments"], "Empty agreement package")


def check_case(config):
    participants = [item["id"] for item in config["participants"]]
    unique(participants, "participant IDs")
    roles = [config["player"]["role_id"], config["opponent"]["role_id"]]
    require(roles[0] != roles[1] and set(roles) <= set(participants), "Invalid role pair")
    terms = {item["id"]: item for item in config["negotiables"]}
    require(len(terms) == len(config["negotiables"]), "Duplicate negotiable IDs")
    for term in terms.values():
        require(
            bool(term["choices"]) == (term["value_type"] == "choice"),
            "Choices must be nonempty only for choice type",
        )
        unique(term["choices"], "choice values")
    policy = config["agreement_policy"]
    rules = {item["id"]: item for item in policy["constraints"]}
    require(len(rules) == len(policy["constraints"]), "Duplicate constraint IDs")
    require(set(policy["hard_constraint_ids"]) <= set(rules), "Unknown hard constraint")
    commitments = {item["id"]: item for item in policy["commitment_rules"]}
    require(len(commitments) == len(policy["commitment_rules"]), "Duplicate commitment IDs")
    require(
        set(policy["required_commitment_ids"]) <= set(commitments),
        "Unknown required commitment",
    )
    require(all(item["role_id"] in roles for item in commitments.values()), "Wrong rule role")
    for rule in rules.values():
        if rule["kind"] == "linear":
            ids = [item["term_id"] for item in rule["coefficients"]]
            unique(ids, "linear term IDs")
            require(
                all(
                    term_id in terms and terms[term_id]["value_type"] == "number" for term_id in ids
                ),
                "Linear rule must reference number terms",
            )
            continue
        term_id = rule["term_id"]
        require(term_id in terms, "Constraint references unknown term")
        if rule["kind"] == "allowed_values":
            for value in rule["values"]:
                typed(value, terms[term_id])
        else:
            expected = "number" if rule["kind"] == "numeric_range" else "date"
            require(terms[term_id]["value_type"] == expected, "Constraint type mismatch")
            low, high = rule["minimum"], rule["maximum"]
            require(low is not None or high is not None, "Unbounded range constraint")
            require(low is None or high is None or low <= high, "Reversed range")
    steps = config["opponent_strategy"]["steps"]
    unique([step["id"] for step in steps], "step IDs")
    kinds = [step["kind"] for step in steps]
    require(kinds[0] == "declared" and kinds[-1] == "red_line", "Wrong ladder ends")
    for kind in ("declared", "target", "red_line"):
        require(kinds.count(kind) == 1, "Wrong ladder kind count")
    require(not steps[0]["requires"], "Declared position cannot require a concession")
    require(all(step["requires"] for step in steps[1:]), "Missing earned concession rule")
    unique([item["id"] for step in steps for item in step["requires"]], "concession IDs")
    for step in steps:
        require(set(step["constraint_ids"]) <= set(rules), "Unknown position constraint")
        covered = set()
        for rule_id in step["constraint_ids"]:
            rule = rules[rule_id]
            if rule["kind"] == "linear":
                covered.update(item["term_id"] for item in rule["coefficients"])
            else:
                covered.add(rule["term_id"])
        require(covered == set(terms), "Position window does not cover all terms")
        check_terms(step["terms"], config, step)


def check_snapshot(snapshot, case=None):
    if case:
        for field, expected in (
            ("case_id", case["id"]),
            ("case_config_version", case["config_version"]),
            ("player_role_id", case["player"]["role_id"]),
            ("opponent_role_id", case["opponent"]["role_id"]),
        ):
            require(snapshot[field] == expected, f"Snapshot mismatch: {field}")
    round_ = snapshot["round"]
    if round_["status"] == "ready":
        require(
            all(
                round_[key] is None
                for key in ("started_at", "deadline_at", "finished_at", "end_reason")
            ),
            "Ready round has timestamps",
        )
    else:
        start, deadline = instant(round_["started_at"]), instant(round_["deadline_at"])
        require(0 < (deadline - start).total_seconds() <= 300, "Invalid round duration")
        closed = round_["status"] in ("finishing", "finished")
        require(closed == (round_["finished_at"] is not None), "Round end mismatch")
        require(closed == (round_["end_reason"] is not None), "Round reason mismatch")
    unique([item["message_id"] for item in snapshot["transcript"]], "message IDs")
    for entry in snapshot["transcript"]:
        stamp = instant(entry["created_at"])
        require(round_["started_at"] is not None, "Message in unstarted round")
        elapsed = int((stamp - instant(round_["started_at"])).total_seconds() * 1000)
        require(elapsed == entry["elapsed_ms"], "Elapsed time mismatch")
        require(stamp < instant(round_["deadline_at"]), "Late transcript entry")
    state = snapshot["state"]
    if state["stage"] == "agreed":
        require(
            state["agreement"] is not None and state["decision"] is None, "Agreement state mismatch"
        )
    elif state["stage"] in ("partial_agreement", "deferred"):
        require(
            state["agreement"] is None
            and state["decision"] is not None
            and state["decision"]["kind"] == state["stage"],
            "Decision state mismatch",
        )
    else:
        require(
            state["agreement"] is None and state["decision"] is None, "Negotiating state has deal"
        )


def evidence(item, snapshot, player_only=False):
    entries = [
        entry for entry in snapshot["transcript"] if entry["message_id"] == item["message_id"]
    ]
    require(len(entries) == 1, "Unknown evidence message")
    entry = entries[0]
    require(entry["status"] == "accepted", "Evidence from unaccepted entry")
    require(
        all(item[key] == entry[key] for key in ("turn_id", "speaker", "elapsed_ms")),
        "Evidence identity mismatch",
    )
    require(item["quote"] in entry["text"], "Nonliteral evidence quote")
    require(not player_only or entry["speaker"] == "player", "Wrong coaching speaker")


def check_result(result, request):
    snapshot = request["snapshot"]
    require(result["session_id"] == snapshot["session_id"], "Result session mismatch")
    outcome = result["outcome"]
    require(
        (outcome["kind"] == "agreement") == (outcome["agreement"] is not None),
        "Outcome agreement mismatch",
    )
    require(
        (outcome["analysis_status"] == "ready") == (outcome["analysis_error_code"] is None),
        "Outcome analysis status mismatch",
    )
    for item in outcome["evidence"]:
        evidence(item, snapshot)
    if outcome["agreement"]:
        check_terms(outcome["agreement"], request["case"])
        require(
            {item["speaker"] for item in outcome["evidence"]} == {"player", "opponent"},
            "Agreement requires bilateral evidence",
        )
    for item in outcome["concessions"] + outcome["costs"] + outcome["consequences"]:
        for proof in item["evidence"]:
            evidence(proof, snapshot)
    unique([slot["college"] for slot in result["judge_verdicts"]], "judge colleges")
    for slot in result["judge_verdicts"]:
        ready = slot["status"] == "ready"
        require(
            ready == (slot["verdict"] is not None) == (slot["error_code"] is None),
            "Judge slot mismatch",
        )
        if ready:
            require(slot["college"] == slot["verdict"]["college"], "Wrong verdict college")
            criteria = DEFS["JudgeVerdict"]["properties"]["decisive_criterion"]["enum"]
            index = {"hiring": 0, "negotiation": 1, "ownership": 2}[slot["college"]]
            require(
                slot["verdict"]["decisive_criterion"] in criteria[index * 5 : index * 5 + 5],
                "Criterion belongs to another college",
            )
            visible = " ".join(
                [
                    slot["verdict"]["decisive_criterion"],
                    slot["verdict"]["evidence"]["quote"],
                    *[slot["verdict"][key] for key in ("observation", "effect", "comparison")],
                ]
            )
            require(len(visible.split()) <= 120, "Judge comment too long")
            evidence(slot["verdict"]["evidence"], snapshot)
    slot = result["trainer_feedback"]
    ready = slot["status"] == "ready"
    require(
        ready == (slot["feedback"] is not None) == (slot["error_code"] is None),
        "Trainer slot mismatch",
    )
    if not ready:
        return
    feedback = slot["feedback"]
    require(feedback["strengths"] or feedback["mistakes"], "Trainer has no observed episode")
    for point in feedback["strengths"] + feedback["mistakes"] + feedback["missed_opportunities"]:
        evidence(point["evidence"], snapshot, player_only=True)
    preparation = request.get("preparation")
    comparison = feedback["plan_vs_reality"]
    require(preparation is not None or comparison is None, "Comparison without preparation")
    if comparison:
        for item in comparison["items"]:
            require(item["preparation_text"] in preparation, "Invented preparation quote")
            observed = item["status"] != "not_observed"
            require(observed == (item["evidence"] is not None), "Plan evidence mismatch")
            if observed:
                evidence(item["evidence"], snapshot, player_only=True)
    goal = feedback["goal_assessment"]
    require(
        (goal["status"] == "not_assessable") == (goal["goal_text"] is None), "Goal status mismatch"
    )
    if goal["goal_text"]:
        require(preparation is not None and goal["goal_text"] in preparation, "Invented goal")
    for item in goal["evidence"]:
        evidence(item, snapshot)


def check(value, definition):
    schema = {**SCHEMA, "$ref": f"#/$defs/{definition}"}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    if definition in ("TurnRequest", "FinishRequest"):
        check_case(value["case"])
        check_snapshot(value["snapshot"], value["case"])
        preparation = value.get("preparation")
        require(preparation is None or preparation.strip(), "Blank preparation")
    if definition == "TurnRequest":
        require(value["snapshot"]["round"]["status"] == "open", "Turn outside open round")
        require(
            value["user_message_id"] != value["opponent_message_id"], "Duplicate turn message IDs"
        )
    if definition == "CanonicalCase":
        ids = [participant["id"] for participant in value["participants"]]
        unique(ids, "canonical participant IDs")
        configs = {config["role_id"]: config for config in value["role_configs"]}
        require(len(configs) == len(value["role_configs"]), "Duplicate role configs")
        require(
            all(config["brief"]["role_id"] == config["role_id"] for config in configs.values()),
            "Role config brief mismatch",
        )
        for pair in value["allowed_role_pairs"]:
            player, opponent = pair["player_role_id"], pair["opponent_role_id"]
            require(player != opponent and {player, opponent} <= set(ids), "Invalid canonical pair")
            require({player, opponent} <= set(configs), "Missing role config")
            author = configs[opponent]
            require(author["opponent_strategy"] is not None, "AI role has no strategy")
            check_case(
                {
                    "participants": value["participants"],
                    "player": configs[player]["brief"],
                    "opponent": author["brief"],
                    "negotiables": author["negotiables"],
                    "opponent_strategy": author["opponent_strategy"],
                    "agreement_policy": author["agreement_policy"],
                }
            )
    if definition in ("PublicCase", "SessionView"):
        public = value if definition == "PublicCase" else value["case"]
        require(
            all(item["visibility"] == "public" for item in public["possible_outcomes"]),
            "Private outcome in public case",
        )
    if definition == "CommandEnvelope":
        completed = value["status"] == "completed"
        require(completed == (value["result"] is not None), "Command result/status mismatch")
        require(
            (value["status"] in ("failed", "unknown")) == (value["error"] is not None),
            "Command error/status mismatch",
        )
        if completed:
            expected = {
                "turn": "PublicTurnResult",
                "finish": "FinishResponse",
                "preparation_review": "PreparationReviewResponse",
            }[value["operation"]]
            check(value["result"], expected)
    if definition == "PreparationReviewResponse":
        ready = value["status"] == "ready"
        require(
            ready == (value["feedback"] is not None) == (value["error_code"] is None),
            "Review slot mismatch",
        )


def refs(value):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for child in value.values():
            yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)


def main():
    Draft202012Validator.check_schema(SCHEMA)
    for reference in refs(SCHEMA):
        require(
            reference.startswith("#/$defs/") and reference.split("/")[-1] in DEFS,
            "Broken schema reference",
        )
    routes = 0
    for owner in ("backend", "ai", "audio"):
        api = read(ROOT / f"{owner}.openapi.json")
        validate(api, base_uri=(ROOT / f"{owner}.openapi.json").as_uri())
        require(
            api["openapi"] == "3.1.0" and api["info"]["version"] == VERSION, "Wrong OpenAPI version"
        )
        for reference in refs(api):
            require(
                reference.startswith("./contract.schema.json#/$defs/")
                and reference.split("/")[-1] in DEFS,
                "Broken OpenAPI reference",
            )
        for operations in api["paths"].values():
            routes += len(operations)
    manifest = read(ROOT / "examples" / "manifest.json")
    fixtures = {}
    for filename, definition in manifest.items():
        value = read(ROOT / "examples" / filename)
        check(value, definition)
        fixtures[filename] = value
    check_result(
        fixtures["finish-partial.response.json"],
        fixtures["finish-without-preparation.request.json"],
    )
    check_result(
        fixtures["finish-with-preparation.response.json"],
        fixtures["finish-with-preparation.request.json"],
    )
    check_result(fixtures["empty-finish.response.json"], fixtures["empty-finish.request.json"])
    invalid = []
    original = fixtures["finish-with-preparation.request.json"]
    for field, value in (
        ("extra", True),
        ("preparation", {"desired_position": "wrong"}),
        ("preparation", "   "),
    ):
        changed = deepcopy(original)
        changed[field] = value
        invalid.append((changed, "FinishRequest"))
    changed = deepcopy(original)
    changed["snapshot"]["case_config_version"] = "wrong"
    invalid.append((changed, "FinishRequest"))
    changed = deepcopy(original)
    changed["case"]["opponent"]["role_id"] = changed["case"]["player"]["role_id"]
    invalid.append((changed, "FinishRequest"))
    changed = deepcopy(original)
    changed["case"]["opponent_strategy"]["steps"][0]["terms"]["values"][0]["value"] = True
    invalid.append((changed, "FinishRequest"))
    changed = deepcopy(original)
    changed["case"]["opponent_strategy"]["steps"][0]["terms"]["values"][0]["value"] = 99999
    invalid.append((changed, "FinishRequest"))
    changed = deepcopy(fixtures["command-completed.response.json"])
    changed["status"] = "queued"
    invalid.append((changed, "CommandEnvelope"))
    changed = deepcopy(fixtures["command-completed.response.json"])
    changed["operation"] = "finish"
    invalid.append((changed, "CommandEnvelope"))
    typed_request = fixtures["typed-bounds-turn.request.json"]
    for term_id, bad_value in (
        ("delivery_date", "2026-02-30"),
        ("handover", "unknown-choice"),
        ("price_per_unit", 5500),
    ):
        changed = deepcopy(typed_request)
        terms = changed["case"]["opponent_strategy"]["steps"][0]["terms"]["values"]
        next(item for item in terms if item["term_id"] == term_id)["value"] = bad_value
        invalid.append((changed, "TurnRequest"))
    for value, definition in invalid:
        try:
            check(value, definition)
        except (ValueError, ValidationError):
            continue
        raise ValueError("Negative fixture was accepted")
    changed = deepcopy(fixtures["finish-with-preparation.response.json"])
    changed["trainer_feedback"]["feedback"]["strengths"][0]["evidence"]["quote"] = "Invented quote"
    try:
        check_result(changed, original)
    except ValueError:
        pass
    else:
        raise ValueError("Invented evidence was accepted")
    print(
        f"Contract {VERSION}: {len(DEFS)} definitions, {routes} REST operations, {len(fixtures)} fixtures, {len(invalid) + 1} negative checks passed"
    )


if __name__ == "__main__":
    main()
