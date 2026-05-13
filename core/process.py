import subprocess
import threading

_lock = threading.Lock()

current_process = None
live_log = []
running = False


def is_running():
    with _lock:
        return running


def get_log():
    with _lock:
        return list(live_log)


def set_running(value: bool):
    global running
    with _lock:
        running = value


def set_process(proc):
    global current_process
    with _lock:
        current_process = proc


def append_log(msg: str):
    with _lock:
        live_log.append(msg)


def clear_log():
    with _lock:
        live_log.clear()


def cancel_process():
    global current_process, running

    with _lock:
        proc = current_process

    if proc:
        try:
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            append_log(f"\nErro ao cancelar: {str(e)}\n")

    set_running(False)
