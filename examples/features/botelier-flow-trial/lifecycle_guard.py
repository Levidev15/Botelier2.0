"""Admit the real call coordinator, never the application server or database.

This separate entry point shares the component guard's audit/environment
protections. Its sole import-policy difference admits call_handler; fixtures
must still provide explicit persistence/provider I/O boundaries.
"""

from application_guard import FORBIDDEN_IMPORTS, NoLiveApplicationServices, main


class LifecycleServices(NoLiveApplicationServices):
    forbidden_imports = tuple(
        name for name in FORBIDDEN_IMPORTS
        if name != "botelier.voice.call_handler"
    )


def prepare_tests():
    from application_support import load_function_mapper

    load_function_mapper()


if __name__ == "__main__":
    raise SystemExit(main(
        import_policy=LifecycleServices,
        scope="real_call_coordinator_and_worker_not_server_or_live_providers",
        self_test_import="botelier.api",
        prepare_tests=prepare_tests,
    ))
