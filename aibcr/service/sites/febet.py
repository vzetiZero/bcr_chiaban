"""JSON-RPC service endpoint for FEBET Dream Gaming entry."""


def dispatch(controller, params):
    return controller.febet_entry.open_dg(params or {})

