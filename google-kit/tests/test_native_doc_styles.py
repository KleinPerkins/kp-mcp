"""Dependency-free contract checks for native-provider style planning."""
from __future__ import annotations

import copy
import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import unittest

MODULE = Path(__file__).parents[1] / "src/google_kit/services/docs/style_profile.py"
spec = importlib.util.spec_from_file_location("native_doc_style_contract", MODULE)
styles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(styles)


def profile():
    return {
        "schema": 1,
        "named_styles": {"NORMAL_TEXT": {
            "textStyle": {"fontSize": {"magnitude": 12, "unit": "PT"}},
            "paragraphStyle": {"lineSpacing": 120},
        }},
        "document_style": {"marginTop": {"magnitude": 72, "unit": "PT"}},
    }


def document():
    return {
        "documentId": "fixture-doc", "revisionId": "fixture-revision",
        "tabs": [{"tabProperties": {"tabId": "fixture-tab"}, "documentTab": {
            "body": {"content": [{"startIndex": 1, "endIndex": 5, "paragraph": {
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                "elements": [{"textRun": {"content": "A🌱\n"}}],
            }}]},
            "namedStyles": {"styles": [{"namedStyleType": "NORMAL_TEXT",
                "textStyle": {"fontSize": {"magnitude": 11, "unit": "PT"}},
                "paragraphStyle": {"lineSpacing": 115}}]},
            "documentStyle": {"marginTop": {"magnitude": 72, "unit": "PT"}},
        }}],
    }


class NativeStyleContract(unittest.TestCase):
    def flattened(self):
        doc = document(); tab = doc["tabs"][0]
        doc["tabs"] = [{"tabId":tab["tabProperties"]["tabId"],
            "documentId":doc["documentId"], "title":"Synthetic tab",
            **copy.deepcopy(tab["documentTab"])}]
        return doc

    def test_flattened_native_readback_capture_and_plan(self):
        doc = self.flattened(); before = copy.deepcopy(doc)
        captured = styles.capture_native_profile(doc, document_id="fixture-doc")
        self.assertEqual(captured, styles.capture_native_profile(document(), document_id="fixture-doc"))
        self.assertEqual(self.plan(doc)["requests"], self.plan()["requests"])
        self.assertEqual(doc, before)

    def test_flattened_multiple_tabs_need_explicit_selection(self):
        doc = self.flattened(); tab = copy.deepcopy(doc["tabs"][0]); tab["tabId"] = "second-tab"
        doc["tabs"].append(tab)
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)
        self.assertEqual(self.plan(doc, tab_id="second-tab")["tab_id"], "second-tab")

    def test_ambiguous_tab_shape_refused(self):
        doc = self.flattened(); doc["tabs"][0]["tabProperties"] = {"tabId":"other-tab"}
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_flattened_foreign_document_refused(self):
        doc = self.flattened(); doc["tabs"][0]["documentId"] = "foreign-doc"
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_flattened_partial_response_refused(self):
        doc = self.flattened(); del doc["tabs"][0]["namedStyles"]
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_complete_native_readback_is_hash_bound(self):
        doc = self.flattened(); doc["tabs"][0]["inlineObjects"] = {"fixture-object":{"synthetic":True}}
        expected = hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
        self.assertEqual(self.plan(doc)["document_sha256"], expected)
        doc["tabs"][0]["inlineObjects"]["fixture-object"]["synthetic"] = False
        self.assertNotEqual(self.plan(doc)["document_sha256"], expected)

    def test_planner_has_no_account_or_io_imports(self):
        tree = ast.parse(MODULE.read_text())
        allowed = {"__future__", "copy", "hashlib", "json", "typing"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(x.name in allowed for x in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "eval", "exec", "compile", "__import__", "print", "input"})

    def plan(self, doc=None, data=None, **kwargs):
        return styles.prepare_native_update(document() if doc is None else doc,
            profile() if data is None else data, document_id="fixture-doc",
            revision_id="fixture-revision", **kwargs)

    def test_capture_uses_canonical_shape(self):
        got = styles.capture_native_profile(document(), document_id="fixture-doc")
        self.assertEqual(got["source_doc_id"], "fixture-doc")
        self.assertEqual(got["tab_id"], "fixture-tab")
        self.assertEqual(got["named_styles"]["NORMAL_TEXT"]["textStyle"]["fontSize"]["magnitude"], 11)

    def test_explicit_revision_guard_and_target(self):
        got = self.plan()
        self.assertEqual(got["document_id"], "fixture-doc")
        self.assertEqual(got["write_control"], {"requiredRevisionId": "fixture-revision"})
        self.assertEqual(got["requests"][0]["updateNamedStyle"]["tabId"], "fixture-tab")

    def test_does_not_mutate_inputs(self):
        doc, data = document(), profile()
        before = copy.deepcopy((doc, data))
        self.plan(doc, data, mode="normalize")
        self.assertEqual((doc, data), before)

    def test_normalize_uses_provider_utf16_ranges_and_range_tab_id(self):
        got = self.plan(mode="normalize")
        para = next(x["updateParagraphStyle"] for x in got["requests"] if "updateParagraphStyle" in x)
        text = next(x["updateTextStyle"] for x in got["requests"] if "updateTextStyle" in x)
        self.assertEqual(para["range"], {"startIndex": 1, "endIndex": 5, "tabId": "fixture-tab"})
        self.assertEqual(text["range"], {"startIndex": 1, "endIndex": 4, "tabId": "fixture-tab"})
        self.assertNotIn("tabId", text)
        self.assertNotIn("tabId", para)

    def test_foreign_source_tab_is_not_reused(self):
        data = profile(); data.update(source_doc_id="other-doc", tab_id="other-tab")
        self.assertEqual(self.plan(data=data)["tab_id"], "fixture-tab")

    def test_multiple_tabs_require_exact_selection(self):
        doc = document(); tab = copy.deepcopy(doc["tabs"][0]); tab["tabProperties"]["tabId"] = "second-tab"
        doc["tabs"].append(tab)
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)
        self.assertEqual(self.plan(doc, tab_id="second-tab")["tab_id"], "second-tab")

    def test_child_tab_can_be_selected_without_changing_siblings(self):
        doc = document(); tab = copy.deepcopy(doc["tabs"][0]); tab["tabProperties"]["tabId"] = "child-tab"
        doc["tabs"][0]["childTabs"] = [tab]
        before = copy.deepcopy(doc)
        got = self.plan(doc, tab_id="child-tab")
        self.assertEqual(got["tab_id"], "child-tab")
        self.assertEqual(doc, before)
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_duplicate_tab_ids_refused(self):
        doc = document(); doc["tabs"].append(copy.deepcopy(doc["tabs"][0]))
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_missing_tab_id_refused(self):
        doc = document(); del doc["tabs"][0]["tabProperties"]["tabId"]
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_missing_selected_tab_refused(self):
        with self.assertRaises(styles.StyleProfileError): self.plan(tab_id="missing")

    def test_empty_or_nonstring_tab_selection_refused(self):
        for tab in ["", True, 1, []]:
            with self.subTest(tab=tab):
                with self.assertRaises(styles.StyleProfileError): self.plan(tab_id=tab)

    def test_tab_count_and_nesting_bounds(self):
        doc = document()
        for i in range(64):
            tab = copy.deepcopy(doc["tabs"][0]); tab["tabProperties"]["tabId"] = str(i)
            doc["tabs"].append(tab)
        with self.assertRaises(styles.StyleProfileError): self.plan(doc, tab_id="fixture-tab")
        doc = document(); last = doc["tabs"][0]
        for i in range(9):
            child = copy.deepcopy(document()["tabs"][0]); child["tabProperties"]["tabId"] = str(i)
            last["childTabs"] = [child]; last = child
        with self.assertRaises(styles.StyleProfileError): self.plan(doc, tab_id="fixture-tab")

    def test_capture_discards_output_only_and_unrecognized_fields(self):
        doc = document(); style = doc["tabs"][0]["documentTab"]["namedStyles"]["styles"][0]
        style["paragraphStyle"]["headingId"] = "fixture-heading"
        style["textStyle"]["link"] = {"url": "https://example.invalid"}
        got = styles.capture_native_profile(doc, document_id="fixture-doc")
        self.assertNotIn("headingId", got["named_styles"]["NORMAL_TEXT"]["paragraphStyle"])
        self.assertNotIn("link", got["named_styles"]["NORMAL_TEXT"]["textStyle"])

    def test_wrong_document_refused(self):
        doc = document(); doc["documentId"] = "foreign"
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_missing_revision_refused(self):
        doc = document(); del doc["revisionId"]
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_changed_revision_refused(self):
        doc = document(); doc["revisionId"] = "newer"
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_partial_response_refused(self):
        doc = document(); del doc["tabs"][0]["documentTab"]["namedStyles"]
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_bad_profile_schema_refused(self):
        for schema in [None, True, 2, "1"]:
            with self.subTest(schema=schema):
                data = profile(); data["schema"] = schema
                with self.assertRaises(styles.StyleProfileError): self.plan(data=data)

    def test_unknown_profile_and_style_fields_refused(self):
        for mutate in [lambda p:p.update(unknown=True),
            lambda p:p["named_styles"].update(UNKNOWN={}),
            lambda p:p["named_styles"]["NORMAL_TEXT"].update(unknown=True),
            lambda p:p["named_styles"]["NORMAL_TEXT"]["textStyle"].update(link={"url":"https://example.invalid"}),
            lambda p:p["document_style"].update(unknown=True)]:
            data = profile(); mutate(data)
            with self.assertRaises(styles.StyleProfileError): self.plan(data=data)

    def test_nonfinite_profile_refused(self):
        for value in [math.nan, math.inf, -math.inf]:
            data = profile(); data["named_styles"]["NORMAL_TEXT"]["textStyle"]["fontSize"]["magnitude"] = value
            with self.assertRaises(styles.StyleProfileError): self.plan(data=data)

    def test_empty_starter_is_no_capture_claim(self):
        data = {"schema":1,"named_styles":{},"document_style":{}}
        self.assertEqual(self.plan(data=data)["requests"], [])

    def test_pageless_profile_omits_page_margins(self):
        data = profile(); data["document_style"]["documentFormat"] = {"documentMode":"PAGELESS"}
        requests = self.plan(data=data)["requests"]
        self.assertFalse(any("marginTop" in x.get("updateDocumentStyle", {}).get("documentStyle",{}) for x in requests))

    def test_legacy_single_tab_document(self):
        doc = document(); doc.update(doc.pop("tabs")[0]["documentTab"])
        got = self.plan(doc)
        self.assertIsNone(got["tab_id"])
        self.assertTrue(all("tabId" not in next(iter(x.values())) for x in got["requests"]))

    def test_bad_mode_refused(self):
        with self.assertRaises(styles.StyleProfileError): self.plan(mode="everything")

    def test_bounded_snapshot(self):
        doc = document(); doc["title"] = "x" * (2**20 + 1)
        with self.assertRaises(styles.StyleProfileError): self.plan(doc)

    def test_request_and_profile_hashes_are_stable(self):
        a, b = self.plan(), self.plan()
        self.assertEqual(a, b)
        self.assertEqual(len(a["profile_sha256"]),64)
        self.assertEqual(len(a["document_sha256"]),64)
        self.assertEqual(len(a["requests_sha256"]),64)
        json.dumps(a,allow_nan=False)


if __name__ == "__main__": unittest.main()
