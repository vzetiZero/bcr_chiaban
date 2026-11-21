"""JSON-RPC service endpoint for VNWTop Dream Gaming entry."""


def dispatch(controller, params):
    return controller.vnwtop_entry.open_dg(params or {})
