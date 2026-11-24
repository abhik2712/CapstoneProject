"""Exercise the presentation flow through Streamlit widgets."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


@unittest.skipUnless(AppTest, "Install requirements.txt to run Streamlit tests.")
class StreamlitTests(unittest.TestCase):
    def test_handbook_search_shows_prepared_answer_and_citation(self):
        with TemporaryDirectory() as folder, patch.dict("os.environ", {
            "CAPSTONE_STATE_DB": str(Path(folder) / "streamlit.sqlite"),
            "CAPSTONE_MODE": "demo",
        }):
            app = AppTest.from_file(str(APP)).run()
            next(field for field in app.text_input if field.label == "Question").set_value(
                "What should I attach if I lost a receipt ?"
            )
            next(button for button in app.button if button.label == "Search handbook").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Prepared handbook answer" in caption.value for caption in app.caption))
            self.assertTrue(any("attach it as a PDF" in text.value for text in app.text))
            self.assertTrue(any(source.label == "Handbook sources" for source in app.expander))

    def test_equipment_flow_and_trace(self):
        with TemporaryDirectory() as folder, patch.dict("os.environ", {
            "CAPSTONE_STATE_DB": str(Path(folder) / "streamlit.sqlite"),
            "CAPSTONE_MODE": "demo",
        }):
            app = AppTest.from_file(str(APP)).run()
            self.assertFalse(app.exception)
            next(button for button in app.button if button.label == "Start $180 monitor example").click().run()
            self.assertTrue(any("new-hire stipend" in message.value for message in app.info))
            app.radio[0].set_value("annual_refresh")
            next(button for button in app.button if button.label == "Continue").click().run()
            self.assertTrue(any("entire calendar year" in message.value for message in app.info))
            app.radio[0].set_value(True)
            next(button for button in app.button if button.label == "Continue").click().run()
            app.text_input[0].set_value("200")
            next(button for button in app.button if button.label == "Calculate").click().run()
            self.assertFalse(app.exception)
            self.assertIn("USD 150.00", app.success[0].value)
            self.assertTrue(any("Draft for human review" in code.value for code in app.code))
            self.assertTrue(any("9 steps · 3 tool calls" in caption.value for caption in app.caption))
