import importlib
import unittest

from tests.fake_streamlit import FakeStreamlit, install


class NavGroupTests(unittest.TestCase):

    def css(self, starts):
        written = []
        stub = FakeStreamlit()
        stub.markdown = lambda body, **kwargs: written.append(body)
        self.addCleanup(install(stub))

        theme = importlib.import_module("app.ui.theme")
        theme.nav_groups(starts)

        return written[-1]

    def test_each_heading_sits_above_its_first_page(self):
        css = self.css({0: "Overview", 1: "Monitor"})

        self.assertIn("label:nth-child(1)::before", css)
        self.assertIn('content: "Overview"', css)
        self.assertIn("label:nth-child(2)::before", css)
        self.assertIn('content: "Monitor"', css)

    def test_headings_cannot_break_out_of_the_style_block(self):
        css = self.css({0: 'x"; } body { display:none } /*'})

        self.assertNotIn('"; }', css.split("content:")[1].split(";")[0])
        self.assertNotIn("<", css.replace("<style>", "").replace("</style>", ""))


if __name__ == "__main__":
    unittest.main()
