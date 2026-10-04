"""Opening endpoints over the existing authenticated desktop HTTP client."""

from urllib.parse import urlencode

from apps.desktop.api.client import ApiError
from packages.contracts.consignments import ConsignmentReceiptView, IncomingOwner
from packages.contracts.master_data import LocationData, Page, ProductData, UomData, entity_models
from packages.contracts.openings import OpeningPostResult, OpeningView
from packages.contracts.orders import OrderPage, OrderResult
from packages.contracts.receipts import OperationView

PRODUCT_VIEW = entity_models(ProductData)[2]
LOCATION_VIEW = entity_models(LocationData)[2]
UOM_VIEW = entity_models(UomData)[2]


def validated(model, data):
    try:
        return model.model_validate(data).model_dump(mode="json")
    except ValueError:
        raise ApiError(
            "INVALID_RESPONSE", "Phản hồi tồn đầu kỳ không hợp lệ; chưa xác nhận kết quả."
        ) from None


class OpeningApi:
    def __init__(self, client, *, consignment=False):
        self.client = client
        self.route = "consignment-receipts" if consignment else "openings"
        self.kind = "RECEIPT" if consignment else "OPENING"
        self.view_model = ConsignmentReceiptView if consignment else OpeningView

    def page(self, warehouse, status="", after=None):
        params = {"warehouse_id": warehouse, "limit": 25}
        if status:
            params["status"] = status
        if after:
            params["after"] = after
        return validated(OrderPage, self.client.get(self.route + "?" + urlencode(params)))

    def read(self, doc_id):
        result = validated(self.view_model, self.client.get(self.route + "/" + doc_id))
        if (
            result["id"] != doc_id
            or result["kind"] != self.kind
            or len(result["lines"]) != len(result["plan"])
            or {line["id"] for line in result["lines"]}
            != {line["document_line_id"] for line in result["plan"]}
        ):
            raise ApiError("INVALID_RESPONSE", "Chi tiết phiếu và kế hoạch tồn đầu kỳ không khớp.")
        return result

    def operation(self, key):
        result = validated(OperationView, self.client.get(self.route + "/operations/" + str(key)))
        if result["operation_status"] != "COMMITTED" or result["status"] != "COMPLETED":
            raise ApiError("INVALID_RESPONSE", "Chưa nhận được ACK ghi sổ hoàn tất.")
        return result

    def execute(self, command):
        result = self.client.command(command.method, command.path, command.body, command.key)
        result = validated(OpeningPostResult if command.post else OrderResult, result)
        if result["kind"] != self.kind or result["warehouse_id"] != command.warehouse:
            raise ApiError("INVALID_RESPONSE", "Phản hồi không thuộc phiếu/kho tồn đầu kỳ đang gửi.")
        if command.doc_id and result["id"] != command.doc_id:
            raise ApiError("INVALID_RESPONSE", "Phản hồi không thuộc phiếu đang gửi.")
        if command.post and result["status"] != "COMPLETED":
            raise ApiError("INVALID_RESPONSE", "Chưa nhận được ACK ghi sổ hoàn tất.")
        return result

    def inspect(self, command):
        if command.post:
            result = self.operation(command.key)
            if result["id"] != command.doc_id:
                raise ApiError("INVALID_RESPONSE", "ACK không thuộc phiếu đang gửi.")
            return result
        if command.doc_id:
            return self.read(command.doc_id)
        # The list contract has no batch filter. Inspect every page, without
        # guessing that absence on the first page means create did not commit.
        after = None
        while True:
            page = self.page(command.warehouse, after=after)
            for item in page["items"]:
                doc = self.read(item["id"])
                if doc["batch_key"] == command.body["batch_key"]:
                    return doc
            after = page["next_after"]
            if not after:
                return None

    def catalog(self, resource, warehouse=None, query="", after=None):
        params = {"active": "true", "limit": 100, "q": query}
        if warehouse:
            params["warehouse_id"] = warehouse
        if after:
            params["after"] = after
        if resource == "owners":
            return validated(
                Page[IncomingOwner], self.client.get(self.route + "/owners?" + urlencode(params))
            )
        model = PRODUCT_VIEW if resource == "products" else LOCATION_VIEW
        return validated(Page[model], self.client.get("master/" + resource + "?" + urlencode(params)))

    def references(self, warehouse):
        try:
            products = self.catalog("products")
            locations = self.catalog("locations", warehouse)
            return {"products": products, "locations": locations, "owners": self.catalog("owners", warehouse)}
        except ApiError as error:
            if error.code != "FORBIDDEN":
                raise
            return {}

    def product(self, product_id):
        product = validated(PRODUCT_VIEW, self.client.get("master/products/" + product_id))
        unit = validated(UOM_VIEW, self.client.get("master/uoms/" + product["base_uom_id"]))
        return product, unit
