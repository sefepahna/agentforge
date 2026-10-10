"""Structural checks before a workflow is saved. This does not call Freya."""


def _walk_nulls(value, path, errors):
    if value is None:
        errors.append("null at " + path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _walk_nulls(item, path + "." + str(key), errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_nulls(item, path + "[" + str(index) + "]", errors)


def validate_workflow(workflow, server):
    """Return a list of problems. An empty list means the workflow is safe to save."""
    errors = []
    _walk_nulls(workflow, "workflow", errors)
    if "agent_config" in workflow:
        errors.append("agent_config must be omitted")
    nodes = workflow.get("nodes") or {}
    initial = workflow.get("initial_node")
    if initial not in nodes:
        errors.append("initial_node is missing")
    for key, node in nodes.items():
        if node.get("name") != key:
            errors.append(key + " name mismatch")
        for edge in node.get("transitions") or []:
            target = edge.get("target_node")
            if target not in nodes and target != "__previous__":
                errors.append(key + " -> " + str(target))
        if node.get("passthrough"):
            operators = []
            for edge in node.get("transitions") or []:
                condition = edge.get("condition") or {}
                operators.append(condition.get("operator"))
            if "always" not in operators:
                errors.append(key + " passthrough has no always transition")
        if node.get("node_type") == "end_call":
            handler = (((node.get("terminal") or {}).get("function") or {}).get("handler"))
            if handler != "__function__:end_call":
                errors.append(key + " missing end_call terminal")
        if node.get("node_type") == "conversation" and node.get("pre_actions"):
            errors.append(key + " conversation has pre_actions")
        if node.get("node_type") != "conversation" and node.get("tools"):
            errors.append(key + " non-conversation has tools")
        for action in node.get("pre_actions") or []:
            code = (((action.get("function") or {}).get("parameters") or {}).get("properties") or {}).get("code", {}).get("default") or ""
            if "{{" in code or "}}" in code:
                errors.append(key + " code contains template braces")
            url = (((action.get("function") or {}).get("parameters") or {}).get("properties") or {}).get("url", {}).get("default") or ""
            if url and server and not url.startswith(server):
                errors.append(key + " url is not the brief server")
    lifecycle = workflow.get("tools") or []
    if not any((tool.get("config") or {}).get("alwaysRunsAt") == ["end_of_call"] and (tool.get("function") or {}).get("name") == "close_call" for tool in lifecycle):
        errors.append("close_call is not an end_of_call tool")
    for name in ("greet", "id_talk", "cb_talk", "present"):
        tools = (nodes.get(name) or {}).get("tools") or []
        names = [(tool.get("function") or {}).get("name") for tool in tools]
        if "get_account" in names or "create_promise" in names or "verify_identity" in names:
            errors.append(name + " exposes an account tool to the model")
    greet_targets = [edge.get("target_node") for edge in (nodes.get("brain_greet") or {}).get("transitions") or []]
    if "api_account" in greet_targets or "api_verify" in greet_targets:
        errors.append("greeting can reach account tools")
    return errors
