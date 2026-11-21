"""JSON-RPC service endpoint for GK881 Dream Gaming entry."""


def dispatch(controller, params):
    return controller.gk881_entry.open_dg(params or {})

