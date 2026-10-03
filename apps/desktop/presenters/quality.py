from urllib.parse import urlencode

from apps.desktop.presenters.moves import MovePresenter


class QualityPresenter(MovePresenter):
    def load(self, resource="quality/sources", after=None):
        return super().load(resource, after)

    def read(self, source_id, after=None):
        params = {"limit": 50, **({"after": after} if after else {})}
        return self.submit("history", "GET", "quality/sources/" + str(source_id) + "?" + urlencode(params))
