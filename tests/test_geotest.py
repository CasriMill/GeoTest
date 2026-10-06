import unittest
from io import StringIO
from unittest.mock import patch

from geotest.__main__ import main


class MainTests(unittest.TestCase):
    def test_main_prints_ready_message(self) -> None:
        output = StringIO()
        with patch("sys.stdout", output):
            main()

        self.assertEqual(output.getvalue(), "GeoTest project is ready.\n")


if __name__ == "__main__":
    unittest.main()
