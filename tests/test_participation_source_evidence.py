from __future__ import annotations

import unittest

from services.participation_source_evidence import (
    participation_source_evidence_mapping,
    source_evidence_get,
)


class ParticipationSourceEvidenceTests(unittest.TestCase):
    def test_tuple_kv_pairs_to_mapping(self) -> None:
        evidence = (("provider", "SEC"), ("cik", "320193"))
        mapping = participation_source_evidence_mapping(evidence)
        self.assertEqual(mapping["provider"], "SEC")
        self.assertEqual(mapping["cik"], "320193")

    def test_source_evidence_get(self) -> None:
        evidence = (("provider", "SEC"),)
        self.assertEqual(source_evidence_get(evidence, "provider"), "SEC")
        self.assertEqual(source_evidence_get(evidence, "missing", default=""), "")

    def test_mapping_input_passthrough(self) -> None:
        mapping = participation_source_evidence_mapping({"provider": "SEC"})
        self.assertEqual(mapping["provider"], "SEC")

    def test_empty_evidence(self) -> None:
        self.assertEqual(participation_source_evidence_mapping(()), {})
        self.assertEqual(participation_source_evidence_mapping(None), {})


if __name__ == "__main__":
    unittest.main()
