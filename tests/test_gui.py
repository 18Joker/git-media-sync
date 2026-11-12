import pytest

from downloader.config import Config, ConfigStore, Project
from downloader.core import FileEntry
from downloader.gui import App


class FakeStorage:
    def __init__(self):
        self.login_qr_calls = 0

    def login_qr(self, on_qr):
        self.login_qr_calls += 1
        return "user"

    def login_token(self, token):
        return "user"


class FakeDialog:
    def set_status(self, text):
        pass


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gui")
    store = ConfigStore(tmp / "c.json")
    store.save(
        Config(
            [
                Project("A", "/cloud/A", str(tmp / "A")),
                Project("B", "/cloud/B", str(tmp / "B")),
            ]
        )
    )
    a = App(store, FakeStorage())
    yield a
    a.destroy()


def _entries():
    return [
        FileEntry("a/x.png", "x.png", 1, "f1", "pending"),
        FileEntry("a/y.png", "y.png", 1, "f2", "same"),
    ]


def test_populate_enables_download(app):
    app._populate(_entries())
    app.update()
    assert str(app.download_btn["state"]) == "normal"
    assert len(app._checked) == 1


def test_project_switch_clears_state(app):
    app._populate(_entries())
    app.update()
    app.project_list.selection_set(1)
    app._on_select_project()
    app.update()
    assert app._entries == []
    assert app._checked == set()
    assert app.tree.get_children() == ()
    assert str(app.download_btn["state"]) == "disabled"


def test_toggle_folder_tristate(app):
    app._populate(_entries())
    folder = next(n for n in app._roots if n.name == "a")
    app._toggle(folder)
    assert app._checked == {"a/x.png", "a/y.png"}
    app._toggle(folder)
    assert app._checked == set()


def test_login_single_flight(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "_run", lambda fn: calls.append(fn))
    app._login_busy = True
    app._start_qr_login(FakeDialog())
    assert calls == []


def test_login_ok_resets_busy(app):
    app._login_busy = True
    app._handle(("login_ok", "user"))
    assert app._login_busy is False
    assert app.logged_in is True