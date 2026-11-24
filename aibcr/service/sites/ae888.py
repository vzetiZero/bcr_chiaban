"""JSON-RPC service endpoint for 888AE66 Dream Gaming entry."""


def dispatch(controller, params):
    return controller.ae888_entry.open_dg(params or {})
