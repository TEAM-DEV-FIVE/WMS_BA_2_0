"""Load a workspace once per session/scope, without replacing an active draft."""


class WorkspaceLoading:
    def __init__(self):
        self.visited = {}
        self.pending = {}

    @staticmethod
    def scope(view):
        presenter = view.presenter
        variables = getattr(view, 'variables', {})
        criteria = tuple((key, variables[key].get()) for key in ('warehouse', 'kind', 'filter') if key in variables)
        selector = getattr(view, 'selector', None)
        warehouse = selector.get() if selector is not None else ''
        api = presenter.api
        return (id(view), api.session_generation, warehouse, criteria)

    def open(self, view, loader):
        key = self.scope(view)
        if self.visited.get(id(view)) == key or getattr(view, 'busy', False) or getattr(view.presenter, 'pending', None):
            return
        if getattr(view.presenter, 'uncertain', None) or getattr(view, 'dirty', False):
            return
        lines = getattr(view, 'lines', None)
        if getattr(view, 'doc', None) or (isinstance(lines, (list, tuple, dict)) and lines):
            return
        self.visited[id(view)] = key
        loader()
        self.pending[view] = key

    def drain(self):
        for view, key in list(self.pending.items()):
            if key != self.scope(view):
                self.pending.pop(view, None)
                continue
            if getattr(view, 'busy', False) or getattr(view.presenter, 'pending', None):
                continue
            self.pending.pop(view, None)
            table = getattr(view, 'table', None)
            if table is not None and table.get_children() and not table.selection():
                first = table.get_children()[0]
                table.selection_set(first)
                table.focus(first)
                if hasattr(view, 'select'):
                    view.select()

    def clear(self):
        self.visited.clear()
        self.pending.clear()
