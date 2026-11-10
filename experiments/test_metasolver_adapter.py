"""Synthetic malformed-output tests independent of the actual author runs."""
import copy
import json
import unittest
from experiments.adapt_metasolver_output import extract_and_verify


class MetasolverAdapterTests(unittest.TestCase):
    def setUp(self):
        self.inst = dict(pid="sample", box=(4,4,4), types=[dict(t=1,dims=(2,2,2),flags=(1,1,1),qty=2)])
        self.payload = dict(type="output", large_object=dict(measurement=dict(x=4,y=4,z=4)),
                            small_items=[dict(measurement=dict(x=2,y=2,z=2),position=dict(x=0,y=0,z=0))])
        self.stats = dict(remaining=[[1,1]], loaded=[[1,1]], utilization=0.125)

    def text(self, payload=None, stats=None, trailing=False):
        body = json.dumps(payload or self.payload)
        if trailing:
            body = body[:-2]+",]}"
        return "author log\n"+body+"\n"+json.dumps(stats or self.stats)+"\n"

    def test_known_trailing_comma_only(self):
        result = extract_and_verify(self.text(trailing=True),self.inst)
        self.assertEqual(result["result"]["placed"],1)
        self.assertTrue(result["normalization"]["trailing_array_comma_removed"])

    def test_count_and_utilization_mismatch(self):
        for field,value in (("loaded",[[1,2]]),("remaining",[[1,2]]),("utilization",0.5),("utilization",float("nan"))):
            stats = dict(self.stats, **{field:value})
            with self.assertRaises(ValueError):
                extract_and_verify(self.text(stats=stats),self.inst)

    def test_duplicate_layout_and_illegal_geometry(self):
        with self.assertRaises(ValueError):
            extract_and_verify(self.text()+self.text(),self.inst)
        payload = copy.deepcopy(self.payload)
        payload["small_items"][0]["position"]["x"] = 3
        with self.assertRaises(ValueError):
            extract_and_verify(self.text(payload=payload),self.inst)


if __name__ == "__main__":
    unittest.main()
