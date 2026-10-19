"""Passive two-port RS-232 sniffer for the Proteus <-> DigiMaxx C-20 link.

Wiring (from the Y-cable's spare end; connect ONLY sniffer inputs, never
sniffer TX/DTR/RTS, or they fight the PC's drivers on the live link):
    --pc-port   adapter pin 2 (RX) <- line pin 3  (PC -> controller)
    --ctrl-port adapter pin 2 (RX) <- line pin 2  (controller -> PC)
    adapter pin 5 (GND)            <- line pin 5
With a single adapter, give only one of the two ports and capture one
direction per session.

Usage:
    python tools/sniff.py --list
    python tools/sniff.py --scan --ctrl-port COM5
    python tools/sniff.py --ctrl-port COM5 --baud 9600
    python tools/sniff.py --pc-port COM5 --ctrl-port COM6 --baud 9600

While capturing, type a note and press Enter (e.g. "clicked Zero") to drop a
marker into the log. Ctrl+C stops. Each session writes captures/<timestamp>.jsonl
(machine-readable) and .txt (human-readable).
"""

import argparse
import json
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

COMMON_BAUDS = [9600, 19200, 38400, 57600, 115200, 4800, 2400, 1200]
PARITY = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
MODEM_LINES = ("cts", "dsr", "ri", "cd")


def open_port(name, args, baud=None):
    port = serial.Serial(
        baudrate=baud or args.baud,
        bytesize=args.bytesize,
        parity=PARITY[args.parity],
        stopbits=args.stopbits,
        timeout=0.005,
    )
    # Keep our outputs deasserted; they must not be wired to the tap anyway.
    port.dtr = False
    port.rts = False
    port.port = name
    port.open()
    return port


def hexdump(data):
    hx = " ".join(f"{b:02X}" for b in data)
    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{hx}  |{asc}|"


def reader(port, direction, events, stop):
    """Read raw bytes and modem-line changes, push timestamped events."""
    last_lines = None
    while not stop.is_set():
        data = port.read(port.in_waiting or 1)
        now = time.perf_counter()
        if data:
            events.put((now, direction, "data", data))
        lines = {name: getattr(port, name) for name in MODEM_LINES}
        if lines != last_lines:
            events.put((now, direction, "lines", lines))
            last_lines = lines


def note_reader(events, stop):
    for line in sys.stdin:
        if stop.is_set():
            break
        if line.strip():
            events.put((time.perf_counter(), "NOTE", "note", line.strip()))


def capture(args):
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    names = {"PC>CTRL": args.pc_port, "CTRL>PC": args.ctrl_port}
    ports = {direction: open_port(name, args) for direction, name in names.items() if name}
    events, stop = queue.Queue(), threading.Event()
    readers = [threading.Thread(target=reader, args=(port, direction, events, stop), daemon=True)
               for direction, port in ports.items()]
    for thread in readers:
        thread.start()
    threading.Thread(target=note_reader, args=(events, stop), daemon=True).start()

    settings = f"{args.baud} {args.bytesize}{args.parity}{args.stopbits}"
    listening = ", ".join(f"{names[d]}={d}" for d in ports)
    print(f"Capturing {listening} @ {settings}")
    print(f"Logging to {stem}.jsonl / .txt  (type a note + Enter to mark, Ctrl+C to stop)\n")

    t0 = time.perf_counter()
    gap = args.gap_ms / 1000
    pending = {"dir": None, "t": 0.0, "last": 0.0, "buf": bytearray()}

    with open(f"{stem}.jsonl", "w") as jl, open(f"{stem}.txt", "w", encoding="utf-8") as tx:
        jl.write(json.dumps({"type": "meta", "settings": settings, "ports": {d: names[d] for d in ports},
                             "start": datetime.now().isoformat()}) + "\n")

        def emit(line, record):
            print(line)
            tx.write(line + "\n")
            jl.write(json.dumps(record) + "\n")

        def flush():
            if pending["buf"]:
                t = pending["t"] - t0
                data = bytes(pending["buf"])
                emit(f"{t:10.4f}  {pending['dir']:8} {hexdump(data)}",
                     {"type": "frame", "t": round(t, 6), "dir": pending["dir"], "hex": data.hex()})
                pending["buf"].clear()

        try:
            while not args.duration or time.perf_counter() - t0 < args.duration:
                try:
                    now, direction, kind, payload = events.get(timeout=gap)
                except queue.Empty:
                    flush()
                    continue
                if kind == "data":
                    # A new frame starts on direction change or after an idle gap.
                    if direction != pending["dir"] or now - pending["last"] > gap:
                        flush()
                        pending["dir"], pending["t"] = direction, now
                    pending["buf"] += payload
                    pending["last"] = now
                    if len(pending["buf"]) >= args.max_frame:
                        flush()
                else:
                    flush()
                    t = now - t0
                    if kind == "note":
                        emit(f"{t:10.4f}  ======== NOTE: {payload}",
                             {"type": "note", "t": round(t, 6), "text": payload})
                    elif args.lines:
                        flags = " ".join(f"{k.upper()}={int(v)}" for k, v in payload.items())
                        emit(f"{t:10.4f}  {direction:8} lines {flags}",
                             {"type": "lines", "t": round(t, 6), "dir": direction, **payload})
                jl.flush()
                tx.flush()
            flush()
        except KeyboardInterrupt:
            flush()
        finally:
            stop.set()
            for thread in readers:
                thread.join(timeout=1)
            for port in ports.values():
                port.close()
    print(f"\nSaved {stem}.jsonl and {stem}.txt")


def printable_ratio(data):
    if not data:
        return 0.0
    return sum(32 <= b < 127 or b in (10, 13) for b in data) / len(data)


def scan(args):
    """Listen at each common baud rate and report what arrives.

    A correct rate typically gives stable, repeating frames and (for ASCII
    protocols) a high printable ratio. Keep Proteus polling the controller
    (e.g. the measurement window open) while scanning.
    """
    print(f"Scanning {args.scan_seconds}s per rate. Keep Proteus talking to the controller.\n")
    for baud in COMMON_BAUDS:
        for name, label in ((args.pc_port, "PC>CTRL"), (args.ctrl_port, "CTRL>PC")):
            if not name:
                continue
            with open_port(name, args, baud) as port:
                port.reset_input_buffer()
                deadline = time.time() + args.scan_seconds
                data = bytearray()
                while time.time() < deadline:
                    data += port.read(port.in_waiting or 1)
            print(f"{baud:>6} {label:8} {len(data):5d} bytes  printable={printable_ratio(data):4.0%}  "
                  f"{hexdump(bytes(data[:24]))}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="list available serial ports and exit")
    p.add_argument("--scan", action="store_true", help="try common baud rates and report traffic")
    p.add_argument("--pc-port", help="sniffer port listening to PC TX (DB9 pin 3)")
    p.add_argument("--ctrl-port", help="sniffer port listening to controller TX (DB9 pin 2)")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--bytesize", type=int, default=8, choices=[5, 6, 7, 8])
    p.add_argument("--parity", default="N", choices=list(PARITY))
    p.add_argument("--stopbits", type=float, default=1, choices=[1, 1.5, 2])
    p.add_argument("--gap-ms", type=float, default=20, help="idle gap that ends a frame")
    p.add_argument("--max-frame", type=int, default=256, help="split frames longer than this")
    p.add_argument("--lines", action="store_true", help="also log CTS/DSR/RI/CD changes")
    p.add_argument("--duration", type=float, default=0, help="stop after this many seconds (0 = until Ctrl+C)")
    p.add_argument("--scan-seconds", type=float, default=3)
    p.add_argument("--out", default="captures")
    args = p.parse_args()

    if args.list:
        for info in list_ports.comports():
            print(f"{info.device:8} {info.description}  [{info.hwid}]")
        return
    if args.scan:
        scan(args)
        return
    if not (args.pc_port or args.ctrl_port):
        p.error("give --pc-port and/or --ctrl-port")
    capture(args)


if __name__ == "__main__":
    main()
