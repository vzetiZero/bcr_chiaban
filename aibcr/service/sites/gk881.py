"""JSON-RPC service endpoint for GK881 Dream Gaming entry and saved session."""


def dispatch_open(controller, params):
    return controller.gk881_entry.open_dg(params or {})


def dispatch_session_info(controller, params):
    return controller.gk881_entry.session_info()


def dispatch_session_clear(controller, params):
    return controller.gk881_entry.session_clear()
