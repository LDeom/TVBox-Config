import sys, unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from audit_reference_api_candidates import extract_sites, with_list_action, probe, append_verified

class CandidateAuditTests(unittest.TestCase):
    def test_extract_only_vod_site_types_and_deduplicate(self):
        rows=extract_sites({"sites":[{"name":"A","api":"https://a.test/api","type":1},{"name":"B","api":"https://b.test/api","type":3},{"name":"dup","api":"https://a.test/api","type":1}]})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["name"],"A")

    def test_list_action_preserves_existing_query(self):
        self.assertEqual(with_list_action("https://a.test/api?token=x"),"https://a.test/api?token=x&ac=list")

    def test_probe_requires_recognizable_vod_payload(self):
        good=lambda url,**kw: SimpleNamespace(status_code=200,body=b'{"list":[{"vod_id":1,"vod_name":"demo"}]}')
        bad=lambda url,**kw: SimpleNamespace(status_code=200,body=b'{"hello":"world"}')
        row={"group":"g","name":"n","api":"https://a.test/api","type":"1"}
        self.assertTrue(probe(row,good)["valid"])
        self.assertFalse(probe(row,bad)["valid"])

    def test_only_valid_new_urls_are_appended(self):
        old="# header\nA, https://a.test/api\n"
        rows=[{"group":"g","name":"valid","api":"https://b.test/api","valid":True},
              {"group":"g","name":"bad","api":"https://c.test/api","valid":False},
              {"group":"g","name":"dup","api":"https://a.test/api","valid":True}]
        new,count=append_verified(old,rows)
        self.assertEqual(count,1)
        self.assertIn("https://b.test/api",new)
        self.assertNotIn("https://c.test/api",new)
        self.assertTrue(new.endswith("\n"))

    def test_fixed_paths_do_not_create_date_suffixes(self):
        new,count=append_verified("",[{"group":"G","name":"N","api":"https://a.test/api","valid":True}])
        self.assertEqual(count,1)
        self.assertNotIn("2026",new)

if __name__=="__main__": unittest.main()
