import pytest


class Controls:
    def __init__(self):
        self.suspended = False
        self.closed = False

    def suspend(self, owner, value):
        self.suspended = value

    def read_control(self, owner):
        return {"user_id": owner, "suspended": self.suspended}

    def close(self):
        self.closed = True


def test_admin_suspension_command_changes_injected_store(capsys):
    from admin import main

    store = Controls()
    main(["suspend", "alice"], store=store)
    assert store.suspended
    main(["unsuspend", "alice"], store=store)
    assert not store.suspended
    assert "verified" in capsys.readouterr().out
    assert not store.closed


def test_admin_default_uses_supabase_settings_and_closes(monkeypatch):
    import admin

    store = Controls()
    settings_type = admin.Settings
    monkeypatch.setattr(admin, "Settings", lambda: settings_type(_env_file=None))
    monkeypatch.setattr(admin, "cutover_verified", lambda settings: True)

    def constructor(settings):
        assert isinstance(settings, settings_type)
        return store

    monkeypatch.setattr(admin, "Store", constructor)
    main = admin.main
    main(["suspend", "alice"])
    assert store.closed


def test_admin_requires_explicit_control_readback():
    from admin import main

    store = Controls()
    store.read_control = lambda owner: {"user_id": owner, "suspended": False}
    with pytest.raises(SystemExit, match="verification failed"):
        main(["suspend", "alice"], store=store)


def test_admin_default_blocks_control_without_receipt(monkeypatch):
    import admin

    settings_type = admin.Settings
    monkeypatch.setattr(admin, "Settings", lambda: settings_type(_env_file=None))
    calls = []
    monkeypatch.setattr(admin, "Store", lambda settings: calls.append(settings))
    with pytest.raises(SystemExit, match="verification failed"):
        admin.main(["suspend", "alice"])
    assert not calls


def test_admin_readback_is_exact_and_error_output_safe(capsys):
    import httpx
    from admin import main

    owner = "11111111-1111-4111-8111-111111111111"
    seen = []

    class Remote:
        def suspend(self, uid, value):
            assert uid == owner and value is True

    store = Remote()

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[{"user_id": owner, "suspended": True}])

    store._client = httpx.Client(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    )
    main(["suspend", owner], store=store)
    assert seen[0].url.path == "/rest/v1/controls"
    assert dict(seen[0].url.params) == {
        "user_id": "eq." + owner,
        "select": "user_id,suspended",
    }
    store.suspend = lambda *args: (_ for _ in ()).throw(RuntimeError("private detail"))
    with pytest.raises(SystemExit, match="verification failed") as error:
        main(["suspend", owner], store=store)
    output = capsys.readouterr()
    assert owner not in output.out and "private detail" not in str(error.value)
    store._client.close()
