import copy


def materialize_node_config(config: dict, token_factory) -> tuple[dict, dict, dict, bool]:
    """
    Build runtime node maps from config and replace AUTO_GENERATED tokens.

    Returns (node_tokens, token_map, updated_config, needs_save).
    """
    updated_config = copy.deepcopy(config)
    nodes = updated_config.get("nodes", {})
    node_tokens = {}
    token_map = {}
    needs_save = False

    for node_name, node_conf in nodes.items():
        token = node_conf.get("token", "AUTO_GENERATED")
        if token == "AUTO_GENERATED":
            token = token_factory()
            node_conf["token"] = token
            needs_save = True

        node_tokens[node_name] = {
            "token": token,
            "role": node_conf.get("role", "reader"),
            "description": node_conf.get("description", ""),
        }
        token_map[token] = node_name

    if needs_save:
        updated_config["nodes"] = {
            name: {
                "token": info["token"],
                "role": info["role"],
                "description": info["description"],
            }
            for name, info in node_tokens.items()
        }

    return node_tokens, token_map, updated_config, needs_save

