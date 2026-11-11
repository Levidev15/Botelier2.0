"""CI-only PostgreSQL through one disposable Unix socket; providers stay denied."""

import guard
from application_guard import main
from callback_guard import CallbackServices


FIXTURE_CONNECTION = {
    "host": "/offline-db", "dbname": "voice_recovery_fixture", "user": "postgres",
    "connect_timeout": 3, "options": "-c statement_timeout=5000 -c lock_timeout=3000",
}


class RecoveryServices(CallbackServices):
    forbidden_imports = tuple(
        name for name in CallbackServices.forbidden_imports if name != "psycopg2"
    )


def validate_fixture_connection(args, kwargs):
    if args or kwargs != FIXTURE_CONNECTION:
        guard.deny("non_fixture_database_connection")


def prepare_tests():
    from callback_io import load_callbacks
    load_callbacks()
    import psycopg2

    original = psycopg2.connect

    def connect(*args, **kwargs):
        validate_fixture_connection(args, kwargs)
        return original(**kwargs)

    psycopg2.connect = connect


if __name__ == "__main__":
    raise SystemExit(main(
        import_policy=RecoveryServices,
        scope="disposable_ci_postgresql_unix_socket_only_not_customer_database",
        self_test_import="botelier.api.websockets",
        prepare_tests=prepare_tests,
    ))
