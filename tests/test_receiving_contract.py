"""Check receiving examples against the published OpenAPI schemas."""

import json
from pathlib import Path
import unittest
from decimal import Decimal

from jsonschema import RefResolver
from jsonschema.exceptions import ValidationError
from openapi_schema_validator import OAS30Validator


API = json.loads((Path(__file__).resolve().parents[1] / "05_API/openapi_core.json").read_text(encoding="utf-8"))
RESOLVER = RefResolver.from_schema(API)


class ReceivingContractTests(unittest.TestCase):
    def validate_example(self, schema_name, example):
        schema = API["components"]["schemas"][schema_name]
        OAS30Validator(schema, resolver=RESOLVER).validate(example)

    def test_published_examples_match_dtos(self):
        create = API["paths"]["/receipts"]["post"]
        patch = API["paths"]["/receipts/{id}"]["patch"]
        post = API["paths"]["/receipts/{id}/post"]["post"]
        revise = API["paths"]["/receipts/{id}/revise"]["post"]
        purchase_orders = API["paths"]["/purchase-orders"]["get"]
        self.validate_example("ReceiptDraftInput", create["requestBody"]["content"]["application/json"]["example"])
        self.validate_example("PurchaseOrderPage", purchase_orders["responses"]["200"]["content"]["application/json"]["example"])
        self.validate_example("Receipt", create["responses"]["201"]["content"]["application/json"]["example"])
        self.validate_example("Receipt", patch["responses"]["200"]["content"]["application/json"]["example"])
        self.validate_example("Receipt", revise["responses"]["200"]["content"]["application/json"]["example"])
        for example in post["requestBody"]["content"]["application/json"]["examples"].values():
            self.validate_example("ReceiptPostCommand", example["value"])
        self.validate_example("ReceiptPostResult", post["responses"]["200"]["content"]["application/json"]["example"])
        self.validate_example("SimpleCommand", revise["requestBody"]["content"]["application/json"]["example"])

    def test_quantities_are_positive_decimal_strings(self):
        create = API["paths"]["/receipts"]["post"]["requestBody"]["content"]["application/json"]["example"]
        for invalid in (80, "0", "0.000000", "1.0000001", "100000000000000", "-1"):
            with self.subTest(invalid=invalid):
                payload = {**create, "lines": [{**create["lines"][0], "quantity": invalid}]}
                with self.assertRaises(ValidationError):
                    self.validate_example("ReceiptDraftInput", payload)

    def test_post_requires_destination_location(self):
        post = API["paths"]["/receipts/{id}/post"]["post"]["requestBody"]["content"]["application/json"]["examples"]["existingItem"]["value"]
        line = {key: value for key, value in post["lines"][0].items() if key != "destination_location_id"}
        with self.assertRaises(ValidationError):
            self.validate_example("ReceiptPostCommand", {**post, "lines": [line]})

    def test_new_serial_can_be_resolved_at_post(self):
        post = API["paths"]["/receipts/{id}/post"]["post"]["requestBody"]["content"]["application/json"]["examples"]["existingItem"]["value"]
        line = {key: value for key, value in post["lines"][0].items() if key != "stock_item_id"}
        line.update(serial_code="SN-001", quantity_base="1")
        self.validate_example("ReceiptPostCommand", {**post, "lines": [line]})
        with self.assertRaises(ValidationError):
            self.validate_example("ReceiptPostCommand", {**post, "lines": [{**line, "stock_item_id": post["lines"][0]["stock_item_id"]}]})

    def test_new_lot_expiry_examples_and_errors(self):
        operation = API["paths"]["/receipts/{id}/post"]["post"]
        media = operation["requestBody"]["content"]["application/json"]
        lot = media["examples"]["newExpiringLot"]["value"]
        self.validate_example("ReceiptPostCommand", lot)
        missing = {**lot["lines"][0]}
        missing.pop("expires_on")
        self.validate_example("ReceiptPostCommand", {**lot, "lines": [missing]})
        # OpenAPI cannot inspect product.expiry_required; the server-side 422 rule is documented.
        self.assertIn("expiry_required=true", operation["description"])
        expiry_error = operation["responses"]["422"]["content"]["application/json"]["example"]
        self.validate_example("Error", expiry_error)
        self.assertEqual(expiry_error["code"], "LOT_EXPIRY_REQUIRED")
        rule = operation["x-conditional-validation"][0]
        self.assertEqual(rule["when"], {"tracking": "LOT", "expiry_required": True, "lot_exists": False})
        self.assertEqual((rule["required_field"], rule["http_status"], rule["error_code"]),
                         ("lines[].expires_on", 422, "LOT_EXPIRY_REQUIRED"))
        conflict = operation["responses"]["409"]["content"]["application/json"]["example"]
        self.validate_example("Error", conflict)
        self.assertEqual(conflict["code"], "LOT_METADATA_CONFLICT")
        serial_with_lot_date = {key: value for key, value in lot["lines"][0].items() if key not in ("lot_code", "manufactured_on")}
        serial_with_lot_date["serial_code"] = "SN-001"
        with self.assertRaises(ValidationError):
            self.validate_example("ReceiptPostCommand", {**lot, "lines": [serial_with_lot_date]})

    def test_operation_lookup_projects_command_results(self):
        lookup_operation = API["paths"]["/operations/{key}"]["get"]
        examples = lookup_operation["responses"]["200"]["content"]["application/json"]["examples"]
        commands = {
            "createReceipt": API["paths"]["/receipts"]["post"]["responses"]["201"]["content"]["application/json"]["example"],
            "patchReceipt": API["paths"]["/receipts/{id}"]["patch"]["responses"]["200"]["content"]["application/json"]["example"],
            "reviseReceipt": API["paths"]["/receipts/{id}/revise"]["post"]["responses"]["200"]["content"]["application/json"]["example"],
            "postReceipt": API["paths"]["/receipts/{id}/post"]["post"]["responses"]["200"]["content"]["application/json"]["example"],
        }
        self.assertEqual(set(examples), set(commands))
        for name, command in commands.items():
            with self.subTest(command=name):
                lookup = examples[name]["value"]
                self.validate_example("OperationLookupResult", lookup)
                self.assertEqual(lookup["operation_status"], "COMMITTED")
                self.assertEqual({key: lookup[key] for key in ("id", "status", "version")},
                                 {key: command[key] for key in ("id", "status", "version")})
                self.assertEqual(lookup.get("transaction_id"), command.get("transaction_id"))
                if "request_id" in command:
                    self.assertEqual(lookup["request_id"], command["request_id"])
        not_found = lookup_operation["responses"]["404"]["content"]["application/json"]["example"]
        self.validate_example("Error", not_found)
        self.assertEqual(not_found["code"], "OPERATION_NOT_FOUND")

    def test_submit_approve_post_version_chain(self):
        create = API["paths"]["/receipts"]["post"]["responses"]["201"]["content"]["application/json"]["example"]
        submit = API["paths"]["/documents/{id}/submit"]["post"]["x-receiving-example"]
        approve = API["paths"]["/approval-requests/{id}/decide"]["post"]["x-receiving-example"]
        post = API["paths"]["/receipts/{id}/post"]["post"]
        post_request = post["requestBody"]["content"]["application/json"]["examples"]["existingItem"]["value"]
        post_result = post["responses"]["200"]["content"]["application/json"]["example"]
        self.validate_example("SimpleCommand", submit["request"])
        self.validate_example("Result", submit["response"])
        self.validate_example("Decision", approve["request"])
        self.validate_example("Result", approve["response"])
        self.assertEqual(submit["request"]["expected_version"], create["version"])
        self.assertEqual(approve["request"]["expected_version"], submit["response"]["version"])
        self.assertEqual(post_request["expected_version"], approve["response"]["version"])
        self.assertGreater(post_result["version"], post_request["expected_version"])

    def test_baseline_extension_examples(self):
        ownership = API["paths"]["/stock-ownership"]["get"]
        balance = ownership["responses"]["200"]["content"]["application/json"]["example"]
        self.validate_example("OwnershipBalance", balance)
        self.assertEqual(Decimal(balance["physical_base"]), Decimal(balance["owned_base"]) +
                         sum(Decimal(item["quantity_base"]) for item in balance["consigned_by_owner"]))
        warranty = API["paths"]["/serials/{id}/warranty"]["get"]
        unknown = warranty["responses"]["200"]["content"]["application/json"]["example"]
        self.validate_example("SerialWarranty", unknown)
        self.assertEqual(unknown["status"], "UNKNOWN")
        self.assertIsNone(unknown["warranty_ends_on"])
        for operation in (ownership, warranty):
            self.assertTrue(operation["x-contract-status"].startswith("PROVISIONAL_BLOCKED"))


if __name__ == "__main__":
    unittest.main()
