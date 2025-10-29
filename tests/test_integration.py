import subprocess
import sys
import socket
import time
import os
import pytest

def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def run_proc(cmd, logfile_path):
    f = open(logfile_path, "wb")
    proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    return proc, f

def read_log(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return "<could not read log>"

def test_test_py_pair_integration():
    """
    Starts two instances of test.py (mimicking running the two terminals with last arg 1 and 2),
    waits for them to finish, and asserts both exit with code 0.

    Uses ephemeral free ports so CI runners don't conflict with other services.
    """
    p1 = find_free_port()
    p2 = find_free_port()
    # Ensure ports are different
    if p1 == p2:
        p2 = find_free_port()

    log1 = "ci_proc1.log"
    log2 = "ci_proc2.log"

    cmd1 = [sys.executable, "test.py", str(p1), str(p2), "1"]
    cmd2 = [sys.executable, "test.py", str(p1), str(p2), "2"]

    proc1, f1 = run_proc(cmd1, log1)
    proc2, f2 = run_proc(cmd2, log2)

    timeout_seconds = 120

    try:
        # Wait for processes to finish with timeout
        proc1.wait(timeout=timeout_seconds)
        proc2.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        # kill both on timeout and fail with logs
        proc1.kill()
        proc2.kill()
        f1.flush(); f2.flush()
        f1.close(); f2.close()
        out1 = read_log(log1)
        out2 = read_log(log2)
        pytest.fail(f"Timeout after {timeout_seconds}s.\n--- proc1 log ---\n{out1}\n--- proc2 log ---\n{out2}")

    # close log files
    f1.flush(); f2.flush()
    f1.close(); f2.close()

    out1 = read_log(log1)
    out2 = read_log(log2)

    assert proc1.returncode == 0, f"proc1 exited with code {proc1.returncode}\n--- proc1 log ---\n{out1}"
    assert proc2.returncode == 0, f"proc2 exited with code {proc2.returncode}\n--- proc2 log ---\n{out2}"

    # Optionally cleanup logs
    try:
        os.remove(log1)
        os.remove(log2)
    except Exception:
        pass
