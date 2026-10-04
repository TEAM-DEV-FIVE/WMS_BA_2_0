from urllib.parse import urlencode

from apps.desktop.presenters.master_data import MasterDataPresenter
from packages.contracts.traceability import OwnershipBalance


class OwnershipPresenter(MasterDataPresenter):
    def search(self, warehouse_id, location_id, stock_item_id):
        params = {"warehouse_id": str(warehouse_id), "location_id": str(location_id), "stock_item_id": str(stock_item_id)}
        def run():
            return OwnershipBalance.model_validate(self.api.get("stock-ownership?" + urlencode(params)))
        self.submit("page", run)
