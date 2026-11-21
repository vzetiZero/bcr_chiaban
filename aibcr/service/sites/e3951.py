"""JSON-RPC service endpoint for E3951 Dream Gaming entry."""


def dispatch(controller, params):
    return controller.e3951_entry.open_dg(params or {})
