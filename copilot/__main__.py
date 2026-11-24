"""Run the Track B agent or inspect a saved session from the terminal."""
import argparse
import json
import sys
from uuid import uuid4

from .runtime import build_copilot, settings
from .store import Store, checked_session

DEMO_TURNS = (
    {"item": "monitor", "price": "180", "credits": "30", "draft": True},
    {"allowance": "annual_refresh"},
    {"eligible": True, "remaining": "200"},
)


def main():
    defaults = settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=defaults["path"])
    parser.add_argument("--mode", choices=("demo", "live"), default=defaults["mode"])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Run the three-turn equipment example with the bundled handbook passages.")
    equipment = commands.add_parser("equipment", help="Continue an equipment reimbursement session.")
    equipment.add_argument("session")
    equipment.add_argument("update", help="A JSON object of the new fields for this turn.")
    policy = commands.add_parser("policy", help="Ask a public handbook policy question.")
    policy.add_argument("session")
    policy.add_argument("question")
    traces = commands.add_parser("traces", help="Read local traces for one session.")
    traces.add_argument("session")
    args = parser.parse_args()

    try:
        if args.command == "demo":
            session = uuid4().hex
            agent = build_copilot(args.db, telemetry=defaults["telemetry"])
            result = {"session": session, "turns": [agent.equipment(session, turn) for turn in DEMO_TURNS]}
        else:
            session = checked_session(args.session)
            if args.command == "traces":
                result = Store(args.db).traces(session)
            else:
                agent = build_copilot(args.db, args.mode, defaults["telemetry"])
                if args.command == "equipment":
                    try:
                        update = json.loads(args.update)
                    except (ValueError, RecursionError):
                        parser.error("update must be a JSON object with supported equipment fields")
                    result = agent.equipment(session, update)
                else:
                    result = agent.policy(session, args.question)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"Could not run the copilot: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    status = result.get("status") if isinstance(result, dict) else None
    return int(status in {"invalid", "unavailable", "unverified", "rate_limited", "conflict"})


if __name__ == "__main__":
    sys.exit(main())
