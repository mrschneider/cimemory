"""cimemory.dashboard — the Gemba Board.

A live board that replays a real improvement programme frame by frame: five
stations on a shop floor, their andon lamps, the standards ratchet, the A3 of
the problem being worked, the 5-Why ladder, the waste ledger and the yokoten map.

    python3 -m cimemory.dashboard           # serve at http://127.0.0.1:8700
    python3 -m cimemory.dashboard --regen   # rebuild the telemetry first
"""
