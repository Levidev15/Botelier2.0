"""Actual callback routes/auth only; never the full API/server or a real DB."""

from application_guard import main
from lifecycle_guard import LifecycleServices


class CallbackServices(LifecycleServices):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ("botelier.api.calls", "botelier.api._twilio_auth"):
            return None
        return super().find_spec(fullname, path, target)


def prepare_tests():
    from callback_io import load_callbacks

    load_callbacks()


if __name__ == "__main__":
    raise SystemExit(main(
        import_policy=CallbackServices,
        scope="actual_callback_router_and_twilio_auth_not_server_or_customer_database",
        self_test_import="botelier.api.websockets",
        prepare_tests=prepare_tests,
    ))
