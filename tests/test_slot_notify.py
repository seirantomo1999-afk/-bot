import sys
import unittest
from unittest.mock import MagicMock

# selenium_check は実行環境のブラウザ依存をトップレベルで読む。
# 通知判定だけを試すため、未インストールの依存はここで置き換える。
for _name in (
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.common",
    "selenium.webdriver.common.by",
    "selenium.webdriver.common.action_chains",
    "selenium.webdriver.support",
    "selenium.webdriver.support.ui",
    "selenium.webdriver.support.expected_conditions",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.service",
    "selenium.common",
    "selenium.common.exceptions",
    "webdriver_manager",
    "webdriver_manager.chrome",
    "google",
    "google.oauth2",
    "google.oauth2.credentials",
    "googleapiclient",
    "googleapiclient.discovery",
    "google.auth",
    "google.auth.transport",
    "google.auth.transport.requests",
):
    sys.modules.setdefault(_name, MagicMock())

import selenium_check as checker


class SlotNotifyTests(unittest.TestCase):
    def test_nineteen_oclock_is_detected_but_not_emailed(self):
        hour = checker.slot_to_hour("60")
        self.assertEqual(hour, "19時")
        self.assertFalse(checker.should_notify_hour(hour))

    def test_earlier_slots_are_still_emailed(self):
        for code in ("10", "20", "30", "40", "50"):
            self.assertTrue(checker.should_notify_hour(checker.slot_to_hour(code)))


if __name__ == "__main__":
    unittest.main()
