"""A small stand-in for ``streamlit`` so UI code can run in tests.

It is NOT Streamlit: it records what the page asked to show, and returns each
widget's default (or a value the test sets) so page logic executes end to
end. It cannot check how a page looks, or that real Streamlit accepts every
argument, so run the app itself too.
"""

import io
import sys
import types
from contextlib import contextmanager


class StopPage(Exception):
    """Raised by ``st.stop()``."""


class Slot:
    """Stands in for columns, tabs, containers, expanders and placeholders."""

    def __init__(self, st):
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return getattr(self._st, name)


class Cache:
    def __init__(self):
        self.cleared = 0

    def __call__(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        return lambda function: function

    def clear(self):
        self.cleared += 1


class UploadedFile:
    def __init__(self, name, data):
        self.name = name
        self._data = data
        self.size = len(data)

    def getvalue(self):
        return self._data

    def getbuffer(self):
        return memoryview(self._data)


class FakeStreamlit(types.ModuleType):

    def __init__(self, uploads=None, clicks=(), values=None, headers=None):
        super().__init__("streamlit")
        self.context = types.SimpleNamespace(headers=dict(headers or {}))
        self.session_state = {}
        self.calls = []
        self.uploads = uploads or {}
        self.clicks = set(clicks)
        self.values = values or {}
        self.cache_resource = Cache()
        self.cache_data = Cache()
        self.sidebar = Slot(self)

    # -- recording ----------------------------------------------------------

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return Slot(self)

        return record

    def called(self, name):
        return [c for c in self.calls if c[0] == name]

    def text(self):
        """Everything passed to markdown/caption/info/... as one string."""

        parts = []

        for name, args, kwargs in self.calls:
            parts.extend(str(a) for a in args if isinstance(a, str))
            parts.extend(str(v) for v in kwargs.values() if isinstance(v, str))

        return "\n".join(parts)

    # -- layout -------------------------------------------------------------

    def columns(self, spec, **kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [Slot(self) for _ in range(count)]

    def tabs(self, labels):
        self.calls.append(("tabs", (labels,), {}))
        return [Slot(self) for _ in labels]

    def container(self, **kwargs):
        return Slot(self)

    def expander(self, *args, **kwargs):
        self.calls.append(("expander", args, kwargs))
        return Slot(self)

    @contextmanager
    def spinner(self, *args, **kwargs):
        yield

    def stop(self):
        raise StopPage()

    def fragment(self, *args, **kwargs):
        """``@st.fragment`` or ``@st.fragment(run_every=...)``: run as is."""

        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        return lambda function: function

    # -- widgets: return the default, or a value the test chose ------------

    def _value(self, key, default):
        return self.values.get(key, default)

    def button(self, label, key=None, disabled=False, **kwargs):
        self.calls.append(("button", (label,), {"key": key,
                                                "disabled": disabled}))
        return key in self.clicks and not disabled

    def checkbox(self, label, value=False, key=None, **kwargs):
        return self._value(key, value)

    def slider(self, label, min_value=None, max_value=None, value=None,
               step=None, key=None, **kwargs):
        return self._value(key, min_value if value is None else value)

    def number_input(self, label, min_value=None, max_value=None, value=None,
                     step=None, key=None, **kwargs):
        return self._value(key, min_value if value is None else value)

    def radio(self, label, options, index=0, key=None, **kwargs):
        self.calls.append(("radio", (label, list(options)), {"key": key}))
        # Widgets without a key (the sidebar page picker) are looked up
        # by their label.
        default = self.values.get(label, list(options)[index])
        return self._value(key, default)

    def selectbox(self, label, options, index=0, key=None, **kwargs):
        default = self.values.get(label, list(options)[index])
        return self._value(key, default)

    def text_input(self, label, value="", key=None, **kwargs):
        return self._value(key, value)

    def date_input(self, label, value=None, key=None, **kwargs):
        return self._value(key, value)

    def multiselect(self, label, options=(), default=None, key=None, **kw):
        return self._value(key, list(default or []))

    def file_uploader(self, label, type=None, accept_multiple_files=False,
                      key=None, **kwargs):
        found = self.uploads.get(key)

        if accept_multiple_files:
            return found or []

        return found

    def form_submit_button(self, label="", key=None, **kwargs):
        return (key or label) in self.clicks

    def download_button(self, *args, **kwargs):
        self.calls.append(("download_button", args, kwargs))
        return False


def install(stub):
    """Make ``import streamlit`` return the stub and force fresh imports."""

    previous = sys.modules.get("streamlit")
    sys.modules["streamlit"] = stub

    for name in [m for m in sys.modules if m.startswith("app.ui")
                 or m == "app.main"]:
        del sys.modules[name]

    def restore():
        if previous is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = previous

        for name in [m for m in sys.modules if m.startswith("app.ui")
                     or m == "app.main"]:
            del sys.modules[name]

    return restore
