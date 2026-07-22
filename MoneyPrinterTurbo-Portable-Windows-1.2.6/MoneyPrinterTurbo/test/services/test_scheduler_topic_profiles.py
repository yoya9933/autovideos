import unittest
from pathlib import Path
from xml.etree import ElementTree as ET


TASK_NAMESPACE = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class TestSchedulerTopicProfiles(unittest.TestCase):
    def test_each_scheduler_task_has_expected_topic_profile(self):
        workspace_root = Path(__file__).resolve().parents[4]
        expected_arguments = {
            "task_tech_4h.xml": "--topic-profile tech",
            "task_consumer_4h.xml": "--topic-profile consumer_money",
            "task_cybersecurity_4h.xml": "--topic-profile cybersecurity",
            "task_science_future_4h.xml": "--topic-profile science_future",
        }

        actual_arguments = {}
        for filename in expected_arguments:
            root = ET.parse(workspace_root / filename).getroot()
            node = root.find("./task:Actions/task:Exec/task:Arguments", TASK_NAMESPACE)
            actual_arguments[filename] = node.text.strip() if node is not None and node.text else ""

        self.assertEqual(actual_arguments, expected_arguments)


if __name__ == "__main__":
    unittest.main()
