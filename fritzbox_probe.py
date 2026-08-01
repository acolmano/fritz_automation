"""Standalone FritzBox TR-064 probe script.

Use this from VS Code to test data retrieval from a FritzBox without installing the Home Assistant addon.

Requirements:
    pip install fritzconnection==1.15.0

Example:
    python fritzbox_probe.py --host 192.168.178.1 --username admin --password secret
"""

import argparse
from typing import Any

from fritzconnection import FritzConnection


def create_fritz_connection(host: str, username: str, password: str) -> FritzConnection:
    return FritzConnection(address=host, user=username, password=password)


def safe_call_action(fritz_conn: FritzConnection, service: str, action: str) -> dict[str, Any] | None:
    try:
        response = fritz_conn.call_action(service, action)
        if isinstance(response, dict):
            return response
    except Exception as err:
        print(f"Warning: failed {service}.{action}: {err}")
    return None


def _extract_first_value(data: dict[str, Any], keys: list[str]) -> Any:
    """Extract the first matching value from a nested dict for a list of keys."""
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data:
            return data[key]
    for value in data.values():
        if isinstance(value, dict):
            found = _extract_first_value(value, keys)
            if found is not None:
                return found
    return None


def _collect_texts(data: Any) -> list[str]:
    if isinstance(data, dict):
        texts: list[str] = []
        for value in data.values():
            texts.extend(_collect_texts(value))
        return texts
    if isinstance(data, (list, tuple)):
        texts: list[str] = []
        for item in data:
            texts.extend(_collect_texts(item))
        return texts
    if isinstance(data, (str, int, float, bool)):
        return [str(data)]
    return []


def get_wan_info(fritz_conn: FritzConnection) -> dict[str, Any]:
    data: dict[str, Any] = {}

    data["GetCommonLinkProperties"] = safe_call_action(
        fritz_conn,
        "WANCommonInterfaceConfig:1",
        "GetCommonLinkProperties",
    ) or {}

    data["GetInfo"] = safe_call_action(
        fritz_conn,
        "WANDSLInterfaceConfig:1",
        "GetInfo",
    ) or {}

    data["GetDefaultConnectionService"] = safe_call_action(
        fritz_conn,
        "Layer3Forwarding:1",
        "GetDefaultConnectionService",
    ) or {}

    mobile_info = {}
    for action in (
        "GetInfo",
        "GetInfoEx",
        "GetAccessTechnology",
    ):
        mobile_info[action] = safe_call_action(
            fritz_conn,
            "X_AVM-DE_WANMobileConnection:1",
            action,
        ) or {}

    data["mobile_info"] = mobile_info
    return data


def determine_active_connection(wan_info: dict[str, Any]) -> dict[str, str]:
    common_link = wan_info.get("GetCommonLinkProperties", {}) or {}
    dsl_info = wan_info.get("GetInfo", {}) or {}
    default_conn = wan_info.get("GetDefaultConnectionService", {}) or {}

    mobile_info = wan_info.get("mobile_info", {}) or {}
    mobile_info_combined: dict[str, Any] = {}
    for action in ("GetInfo", "GetInfoEx", "GetAccessTechnology"):
        mobile_info_combined.update(mobile_info.get(action, {}) or {})

    wan_access_type = _extract_first_value(common_link, ["NewWANAccessType"]) or "unknown"
    dsl_state_raw = _extract_first_value(dsl_info, ["NewStatus", "NewLinkStatus", "NewX_AVM-DE_DSLStatus"])
    mobile_state_raw = _extract_first_value(
        mobile_info_combined,
        ["NewStatus", "NewEnable", "NewConnectionStatus", "NewLinkStatus"],
    )
    mobile_access_tech = _extract_first_value(
        mobile_info_combined,
        ["NewCurrentAccessTechnology", "NewAccessTechnology", "NewTechnology"],
    )

    combined_text = " ".join(
        text.lower()
        for text in _collect_texts(
            {
                "wan_access_type": wan_access_type,
                "dsl_info": dsl_info,
                "default_conn": default_conn,
                "mobile_info": mobile_info_combined,
            }
        )
        if isinstance(text, str)
    )

    dsl_state = str(dsl_state_raw).strip().lower() if dsl_state_raw is not None else ""
    mobile_state = str(mobile_state_raw).strip().lower() if mobile_state_raw is not None else ""
    access_technology_raw = str(mobile_access_tech).strip().lower() if mobile_access_tech is not None else ""

    dsl_is_active = dsl_state in {"up", "active", "established", "connected", "ok", "true", "1"}
    lte_is_active = (
        "lte" in combined_text
        or "mobile" in combined_text
        or access_technology_raw == "lte"
        or mobile_state in {"up", "active", "established", "connected", "ok", "true", "1"}
    )

    connection_type = "unknown"
    if dsl_is_active:
        if "vdsl" in combined_text:
            connection_type = "vdsl"
        elif "adsl" in combined_text:
            connection_type = "adsl"
        else:
            connection_type = "dsl"
    elif lte_is_active:
        connection_type = "lte"
    elif "vdsl" in combined_text:
        connection_type = "vdsl"
    elif "adsl" in combined_text:
        connection_type = "adsl"
    elif "dsl" in combined_text:
        connection_type = "dsl"

    wan_failover_active = "unknown"
    if connection_type == "lte" and dsl_is_active:
        wan_failover_active = "on"
    elif connection_type in {"adsl", "vdsl", "dsl"}:
        wan_failover_active = "off"

    access_technology = "unknown"
    if connection_type == "vdsl":
        access_technology = "vdsl"
    elif connection_type == "adsl":
        access_technology = "adsl"
    elif connection_type == "dsl":
        access_technology = "dsl"
    elif access_technology_raw:
        access_technology = access_technology_raw
    elif "lte" in combined_text or "mobile" in combined_text:
        access_technology = "lte"
    else:
        access_technology = str(wan_access_type).lower()

    return {
        "connection_type": connection_type,
        "access_technology": access_technology,
        "dsl_link_state": dsl_state or "unknown",
        "lte_link_state": mobile_state or "unknown",
        "wan_failover_active": wan_failover_active,
    }


def get_device_info(fritz_conn: FritzConnection) -> dict[str, Any]:
    return safe_call_action(fritz_conn, "DeviceInfo:1", "GetInfo") or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe FritzBox TR-064 data from VS Code")
    parser.add_argument("--host", required=True, help="FritzBox host or IP")
    parser.add_argument("--username", required=True, help="FritzBox username")
    parser.add_argument("--password", required=True, help="FritzBox password")
    parser.add_argument(
        "--action",
        choices=["wan", "device", "connection", "all"],
        default="all",
        help="Which data set to read",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fritz_conn = create_fritz_connection(args.host, args.username, args.password)

    if args.action in {"wan", "connection", "all"}:
        print("=== WAN / DSL info ===")
        wan_info = get_wan_info(fritz_conn)
        for key, value in wan_info.items():
            print(f"\n[{key}]")
            print(value)

        if args.action in {"connection", "all"}:
            print("\n=== Active connection ===")
            summary = determine_active_connection(wan_info)
            print(f"connection_type: {summary['connection_type']}")
            print(f"access_technology: {summary['access_technology']}")
            print(f"dsl_link_state: {summary['dsl_link_state']}")
            print(f"lte_link_state: {summary['lte_link_state']}")
            print(f"wan_failover_active: {summary['wan_failover_active']}")

    if args.action in {"device", "all"}:
        print("\n=== Device info ===")
        device_info = get_device_info(fritz_conn)
        print(device_info)


if __name__ == "__main__":
    main()
