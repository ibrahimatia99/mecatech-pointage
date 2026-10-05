import hashlib
from pathlib import Path
import unittest

EXPECTED_SHA256 = "6f43a814c7c2e4709cbb4628ec23db37beaee4069b698246fcd4e70a2802fa04"
START = "@api_bp.route('/heartbeat'"
END = "# --- ATTENDANCE BUSINESS RULE HELPERS ---"


class ESPContractTests(unittest.TestCase):
    def test_esp_facing_region_is_unchanged(self):
        path = Path(__file__).resolve().parents[1] / "routes" / "api.py"
        source = path.read_text(encoding="utf-8")
        start = source.index(START)
        end = source.index(END, start)
        region = source[start:end]
        digest = hashlib.sha256(region.encode("utf-8")).hexdigest()
        self.assertEqual(
            digest,
            EXPECTED_SHA256,
            "ESP-facing heartbeat/enrollment/Joker/scan code was modified. Review before release.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
