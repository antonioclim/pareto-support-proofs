from __future__ import annotations

import json
from pathlib import Path
import unittest

import jsonschema

from common import ROOT


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instance_schema = json.loads((ROOT / "schemas" / "instance-v1.schema.json").read_text(encoding="utf-8"))
        cls.certificate_schema = json.loads((ROOT / "schemas" / "certificate-v1.schema.json").read_text(encoding="utf-8"))

    def test_all_reference_instances(self):
        count = 0
        for path in sorted((ROOT / "examples" / "instances").glob("*.json")):
            if ".instance." in path.name:
                continue
            jsonschema.Draft202012Validator(self.instance_schema).validate(json.loads(path.read_text(encoding="utf-8")))
            count += 1
        self.assertGreaterEqual(count, 6)

    def test_all_reference_certificates(self):
        count = 0
        for path in sorted((ROOT / "examples" / "certificates").glob("*_certificate.json")):
            jsonschema.Draft202012Validator(self.certificate_schema).validate(json.loads(path.read_text(encoding="utf-8")))
            count += 1
        self.assertGreaterEqual(count, 6)


if __name__ == "__main__":
    unittest.main()
