"""Offline subprocess fixtures. Used only from a temporary test PATH."""
import datetime
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

TOOL = Path(sys.argv[0]).name
ARGS = sys.argv[1:]
TOKEN = "FAKE_ISSUED_TOKEN_MUST_NOT_LEAK"
SECRET = "FAKE_PASSWORD_MUST_NOT_LEAK"
EX = "92ccf1f3-e96c-4abd-b37c-57c8d8859e2f"
stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

if TOOL == "openstack":
    assert ARGS == ["token", "issue", "-f", "value", "-c", "id"]
    if os.environ.get("MISTRAL_FIXTURE_AUTH_FAIL"):
        print("OS_PASSWORD=" + SECRET, file=sys.stderr)
        sys.exit(1)
    print(TOKEN)
elif TOOL == "curl":
    assert TOKEN not in str(ARGS)
    assert sys.stdin.read() == "X-Auth-Token: " + TOKEN + "\n"
    endpoint = urlsplit(ARGS[-1])
    path = endpoint.path
    counter = Path(os.environ["MISTRAL_FIXTURE_DIR"]) / ("count-" + str(endpoint.port))
    count = int(counter.read_text()) if counter.exists() else 0
    execution = {"id": EX, "workflow_name": "power_ops.power_on_and_return",
                 "state": "PAUSED" if count >= 2 else "RUNNING", "state_info": "",
                 "input": {"password": SECRET}, "created_at": stamp, "updated_at": stamp}
    code = 504 if os.environ.get("MISTRAL_FIXTURE_API_FAIL") else 200
    if path.endswith("/executions"):
        count += 1
        counter.write_text(str(count))
        body = {"executions": [execution] if count == 1 else []}
    elif path.endswith("/" + EX):
        body = execution
    elif path.endswith("/tasks"):
        body = {"tasks": [{"id": EX, "state": "PAUSED", "name": "operator_inspection_gate", "result": {"token": TOKEN}}]}
    elif path.endswith("/workflows"):
        body = {"workflows": [{"id": EX, "name": "power_ops.power_on_and_return"}]}
    else:
        body = {"name": "std.noop"}
    if code != 200:
        body = {"error": "Gateway Timeout", "password": SECRET, "echo": TOKEN}
    sys.stdout.write("HTTP/1.1 %d OK\r\nX-Openstack-Request-Id: req-fixture-%s\r\n\r\n" % (code, endpoint.port))
    sys.stdout.write(json.dumps(body))
    sys.stdout.write("\nMISTRAL_DIAG_METRICS %d 0.001 0.010 0.020\n" % code)
elif TOOL == "hostname":
    print("wrong-host.invalid" if os.environ.get("MISTRAL_FIXTURE_WRONG_HOST") else "mistral-fixture.invalid")
elif TOOL == "podman":
    if ARGS[:2] == ["ps", "-a"]:
        print("mistral_api\tfixture:image\tUp\nmistral_executor\tfixture:image\tUp\nrabbitmq\tfixture:image\tUp")
    elif ARGS[:1] == ["inspect"]:
        print("image_id=sha256:fixture status=running oom=false")
    elif ARGS[:1] == ["exec"] and "rabbitmqctl" in ARGS:
        if "list_queues" in ARGS:
            print("name\tconsumers\tmessages_ready\tmessages_unacknowledged\tstate\nmistral_engine\t2\t0\t0\trunning")
        elif "list_vhosts" in ARGS:
            print("name\n/")
        else:
            print("Cluster name: fixture")
    elif ARGS[:1] == ["exec"] and "rabbitmq-diagnostics" in ARGS:
        print("OK")
    elif ARGS[:1] == ["exec"] and "database_probe" in ARGS[-1]:
        print(json.dumps({"status": "ok", "checks": [{"name": "connection", "status": "ok", "seconds": .001, "rows": [{"ok": 1}]}]}))
    elif ARGS[:1] == ["exec"]:
        print(json.dumps({"DEFAULT": {"transport_url_endpoint": {"scheme": "rabbit", "hostport": "fixture:5672", "path": "/"}}}))
    elif ARGS[:1] == ["logs"]:
        print(stamp + " ERROR req-fixture-log password=" + SECRET)
    else:
        print("fixture metadata")
else:
    print("fixture " + TOOL + " metadata")
