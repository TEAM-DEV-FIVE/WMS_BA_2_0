from urllib.parse import urlencode

from apps.desktop.presenters.orders import OrderPresenter

PATHS = {"PO": "purchase-orders", "SO": "sales-orders", "RECEIPT": "receipts"}


class ApprovalPresenter(OrderPresenter):
    """Inbox uses the existing scoped list/detail/decision APIs, without catalogue grants."""

    def load(self, path, warehouse, status="SUBMITTED", after=None, query=""):
        def run():
            permissions = self.api.permissions(warehouse)
            params = {"warehouse_id": warehouse, "status": "SUBMITTED", "limit": 25}
            if after:
                params["after"] = after
            return self.api.get(path + "?" + urlencode(params)), {}, permissions

        self.submit("load", run)

    def read(self, path, doc_id):
        def run():
            doc = self.api.get(path + "/" + doc_id)
            doc["_permissions"] = self.api.permissions(doc["warehouse_id"])
            return doc

        self.submit("read", run)


def decision_explanation(doc, user_id, permissions):
    """Explain denial without inventing eligibility; only server can_decide enables a decision."""
    pending = next((a for a in doc["approvals"] if a["status"] == "PENDING"), None)
    if doc["status"] != "SUBMITTED" or not pending:
        return "Phiếu không còn chờ duyệt."
    if "document.approve" not in permissions:
        return "Thiếu quyền duyệt tại kho đang chọn; quyền ở kho khác không áp dụng."
    actors = {doc["created_by"], pending["requested_by"]}
    actors.update(s["decided_by"] for s in pending["steps"] if s["decided_by"])
    if str(user_id) in actors:
        return "Không được tự duyệt: bạn là người lập, người gửi hoặc đã duyệt bước trước (SOD)."
    if not pending["can_decide"]:
        return "Máy chủ chưa cho phép duyệt: kiểm tra vai trò của bước hiện tại, quyền kho và nội dung phiếu."
    return "Máy chủ cho phép quyết định ở phiên bản đang xem; quyền và nội dung được kiểm tra lại khi gửi."
