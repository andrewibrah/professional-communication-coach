"""Operator-only Supabase account controls; backend credentials stay private."""

import argparse
from app import Settings, cutover_verified
from supabase_store import Store


def main(argv=None, store=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["suspend", "unsuspend"])
    parser.add_argument("user_id", help="Verified Supabase subject to control")
    args = parser.parse_args(argv)
    owned = store is None
    try:
        if owned:
            settings = Settings()
            if not cutover_verified(settings):
                raise SystemExit("Control verification failed")
            store = Store(settings)
        expected = args.action == "suspend"
        store.suspend(args.user_id, expected)
        reader = getattr(store, "read_control", None)
        if reader is not None:  # Explicit injected test adapter only.
            control = reader(args.user_id)
        else:
            response = store._client.get(
                "/rest/v1/controls",
                params={"user_id": "eq." + args.user_id, "select": "user_id,suspended"},
            )
            rows = response.json() if response.status_code == 200 else None
            control = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
        if (
            not isinstance(control, dict)
            or set(control) != {"user_id", "suspended"}
            or control["user_id"] != args.user_id
            or control["suspended"] is not expected
        ):
            raise SystemExit("Control verification failed")
        print("Account control updated and verified.")
    except Exception:
        raise SystemExit("Control verification failed") from None
    finally:
        if owned:
            close = getattr(store, "close", None)
            if close:
                close()
            else:
                client = getattr(store, "_client", None)
                if client is not None:
                    client.close()


if __name__ == "__main__":
    main()
