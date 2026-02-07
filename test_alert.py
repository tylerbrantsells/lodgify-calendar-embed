#!/usr/bin/env python3
import json
import os
import subprocess
import sys


def load_env(path):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def main():
    env_path = os.path.join(os.getcwd(), ".env")
    env = load_env(env_path)
    raw = env.get("ICS_URLS_JSON")
    if not raw:
        print("ICS_URLS_JSON not found in .env")
        return 1

    try:
        data = json.loads(raw)
    except Exception as exc:
        print(f"ICS_URLS_JSON is invalid JSON: {exc}")
        return 1

    broken = None
    if isinstance(data, dict):
        for key in data:
            broken = key
            data[key] = data[key] + "-broken"
            break
    elif isinstance(data, list):
        if not data:
            print("ICS_URLS_JSON list is empty")
            return 1
        if isinstance(data[0], dict):
            broken = data[0].get("name", "unknown")
            data[0]["url"] = str(data[0].get("url", "")) + "-broken"
        else:
            broken = "first_url"
            data[0] = str(data[0]) + "-broken"
    else:
        print("ICS_URLS_JSON must be dict or list")
        return 1

    print(f"Intentionally breaking feed for: {broken}")

    new_env = os.environ.copy()
    new_env.update(env)
    new_env["ICS_URLS_JSON"] = json.dumps(data)
    new_env["ICS_INSECURE_SSL"] = "true"

    result = subprocess.run([sys.executable, "build_calendar_data.py"], env=new_env)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
