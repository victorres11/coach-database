import unittest

from api.head_coach_resolution import is_canonical_head_coach_title, resolve_head_coach


class HeadCoachResolutionTests(unittest.TestCase):
    def test_excludes_assistant_head_coach_titles(self):
        self.assertFalse(is_canonical_head_coach_title("Assistant Head Coach for Defense"))
        self.assertFalse(is_canonical_head_coach_title("Associate Head Coach"))
        self.assertFalse(is_canonical_head_coach_title("Interim Head Coach"))

    def test_accepts_primary_head_coach_titles(self):
        self.assertTrue(is_canonical_head_coach_title("Head Coach"))
        self.assertTrue(is_canonical_head_coach_title("C. & J. Elerding Head Football Coach"))

    def test_resolve_usc_like_staff_prefers_lincoln_over_assistant_hc(self):
        staff = [
            {"id": 1006, "year": 2025, "name": "Dennis Simmons", "position": "Assistant Head Coach / Co-Offensive Coordinator / Wide Receivers Coach"},
            {"id": 1007, "year": 2025, "name": "Rob Ryan", "position": "Assistant Head Coach for Defense"},
            {"id": 1008, "year": 2025, "name": "Lincoln Riley", "position": "C. & J. Elerding Head Football Coach"},
        ]
        resolved = resolve_head_coach(staff)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["name"], "Lincoln Riley")


if __name__ == "__main__":
    unittest.main()
