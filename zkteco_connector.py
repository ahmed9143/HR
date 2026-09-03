# ZKTeco Integration — Phase 2a: Connector / Adapter layer.
#
# Scope: connection + raw-record retrieval ONLY. No sync loop, no DB writes,
# no UI. This module is import-safe even when the `zk` (pyzk) package or
# real hardware is unavailable — server startup must never depend on either.
#
# ---------------------------------------------------------------------------
# Library decision: pyzk (PyPI: "pyzk", import name "zk"), v0.9.
#   - Actually installed and inspected (not assumed). It is the only
#     actively-packaged pure-Python ZKTeco client on PyPI; talks the legacy
#     ZKTeco TCP/UDP protocol (port 4370) that iFace-series terminals use.
#   - Confirmed against fananimi/pyzk source (zk/base.py, zk/attendance.py):
#       * connect(ip, port, timeout, password, force_udp, encoding)
#       * get_attendance() -> list[Attendance(user_id, timestamp, status, punch, uid)]
#       * live_capture(new_timeout) -> generator, for real-time polling
#       * enable_device()/disable_device() to pause the device during a pull
#
# ---------------------------------------------------------------------------
# CRITICAL FINDING — no real per-punch transaction/record id exists:
#   Attendance.uid is populated from the raw record's internal slot number.
#   pyzk's own source comments it "# not really used any more" (zk/attendance.py
#   line 4), and get_attendance()'s 8-byte record layout treats it as a
#   duplicate of the *user* table index, not a punch identifier — it is NOT
#   monotonic, NOT unique per event, and is reused/recycled once the device's
#   internal ring buffer wraps (devices like iFace 302 hold a few thousand
#   punches on-board before overwriting the oldest).
#   => There is no hardware transaction/record UID to key deduplication on.
#      This was left open in Phase 1 (see zkteco_core.py); it is now closed:
#      dedup uses a SYNTHETIC composite key, computed locally, documented in
#      zkteco_sync.py. record_uid in zk_attendance_raw stores this computed
#      hash, not anything the device sent.
#
# Expected attendance record shape (what get_attendance() actually returns):
#   user_id   -> str, the device-side user code (maps to employees.zk_user_id)
#   timestamp -> python datetime, no timezone (assume device-local time)
#   status    -> int, device-defined check state (varies by firmware/config)
#   punch     -> int, punch/verify method the device reports
#   uid       -> int, internal slot index (NOT a stable record id — ignored
#                for dedup, kept only for optional debugging/logging)
#
# ---------------------------------------------------------------------------
# What is verified OFFLINE (no hardware) in this repo:
#   - pyzk import, class shape, get_attendance() parsing logic (read from
#     pyzk's own source, not guessed).
#   - ZKDeviceAdapter constructs correctly and raises a clear, typed error
#     when no device is reachable (ConnectionRefusedError / socket errors),
#     rather than hanging or crashing the caller.
#   - MockZKAdapter implements the identical interface and is what
#     zkteco_sync.py's tests actually exercise end-to-end.
#
# What STILL requires a real iFace 302 on-site:
#   - Confirming actual `status`/`punch` integer meanings as configured on
#     that unit (these are firmware/config-dependent and not standardized
#     across ZKTeco models — pyzk does not decode them into semantic labels).
#   - Confirming TCP vs UDP reachability and default comm password.
#   - Confirming on-device buffer size / rollover behavior in practice.
#   - Real timezone/clock-drift behavior of that specific unit.
# ---------------------------------------------------------------------------

from datetime import datetime

try:
    import zk as _pyzk  # the "zk" package from PyPI "pyzk"
    PYZK_AVAILABLE = True
    PYZK_IMPORT_ERROR = None
except Exception as _e:  # pragma: no cover - environment dependent
    _pyzk = None
    PYZK_AVAILABLE = False
    PYZK_IMPORT_ERROR = str(_e)


class ZKConnectorError(Exception):
    """Raised for any connector-level failure (connect/fetch), never a raw
    socket/library exception, so callers (sync engine, UI) can handle one
    error type."""
    pass


class RawPunch:
    """Adapter-neutral representation of a single attendance event.
    Both the real device adapter and the mock adapter emit this shape, so
    zkteco_sync.py never has to know which one it's talking to."""
    __slots__ = ('zk_user_id', 'timestamp', 'status', 'punch', 'device_uid')

    def __init__(self, zk_user_id, timestamp, status, punch, device_uid=None):
        self.zk_user_id = str(zk_user_id)
        self.timestamp = timestamp  # python datetime, naive, device-local
        self.status = status
        self.punch = punch
        self.device_uid = device_uid  # informational only, never used for dedup

    def __repr__(self):
        return f"<RawPunch {self.zk_user_id} @ {self.timestamp} status={self.status} punch={self.punch}>"


class ZKDeviceAdapter:
    """Real adapter over pyzk for a single physical terminal.
    Never used automatically by server startup; only instantiated when a
    caller explicitly asks to sync a specific device_id."""

    def __init__(self, ip, port=4370, password=0, timeout=10, force_udp=False):
        if not PYZK_AVAILABLE:
            raise ZKConnectorError(
                f"pyzk is not installed/importable ({PYZK_IMPORT_ERROR}). "
                f"Install with: pip install pyzk"
            )
        self.ip = ip
        self.port = port
        self.password = password
        self.timeout = timeout
        self.force_udp = force_udp
        self._zk = _pyzk.ZK(ip, port=port, timeout=timeout, password=password,
                             force_udp=force_udp, ommit_ping=False)
        self._conn = None

    def connect(self):
        try:
            self._conn = self._zk.connect()
            return True
        except Exception as e:
            raise ZKConnectorError(f"Could not connect to device at {self.ip}:{self.port}: {e}")

    def disconnect(self):
        if self._conn is not None:
            try:
                self._conn.disconnect()
            except Exception:
                pass
            self._conn = None

    def test_connection(self):
        """Connect, immediately disconnect. Returns (ok: bool, message: str).
        Never raises -- safe to call from a health-check / UI ping button."""
        try:
            self.connect()
            self.disconnect()
            return True, "ok"
        except ZKConnectorError as e:
            return False, str(e)

    def fetch_attendance(self):
        """Returns list[RawPunch]. Caller is responsible for connect lifecycle
        being wrapped around this if calling multiple methods; this method
        will connect/disconnect on its own if not already connected."""
        owns_connection = self._conn is None
        if owns_connection:
            self.connect()
        try:
            records = self._conn.get_attendance() or []
            return [
                RawPunch(r.user_id, r.timestamp, r.status, r.punch, device_uid=r.uid)
                for r in records
            ]
        except Exception as e:
            raise ZKConnectorError(f"Failed reading attendance log from {self.ip}:{self.port}: {e}")
        finally:
            if owns_connection:
                self.disconnect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


class MockZKAdapter:
    """Offline stand-in with the exact same interface as ZKDeviceAdapter, so
    zkteco_sync.py's sync logic can be fully tested without hardware.

    `fixed_records`, if given, is returned verbatim on every fetch (useful
    for testing idempotency: call fetch twice, expect the sync layer to
    dedup identically both times). Otherwise a small built-in dataset is
    used."""

    def __init__(self, ip="mock", port=0, password=0, timeout=10, force_udp=False,
                 fixed_records=None, fail_connect=False):
        self.ip = ip
        self.port = port
        self._connected = False
        self.fail_connect = fail_connect
        self._records = fixed_records if fixed_records is not None else self._default_records()

    @staticmethod
    def _default_records():
        base = datetime(2026, 8, 20, 8, 0, 0)
        return [
            RawPunch("1001", base.replace(hour=8, minute=1), status=0, punch=0, device_uid=17),
            RawPunch("1001", base.replace(hour=17, minute=3), status=1, punch=0, device_uid=18),
            RawPunch("1002", base.replace(hour=8, minute=5), status=0, punch=0, device_uid=19),
            # zk_user_id with no matching employees.zk_user_id -> exercises zk_unmatched
            RawPunch("9999", base.replace(hour=9, minute=0), status=0, punch=1, device_uid=20),
        ]

    def connect(self):
        if self.fail_connect:
            raise ZKConnectorError(f"Mock device at {self.ip} refused connection (simulated)")
        self._connected = True
        return True

    def disconnect(self):
        self._connected = False

    def test_connection(self):
        try:
            self.connect()
            self.disconnect()
            return True, "ok (mock)"
        except ZKConnectorError as e:
            return False, str(e)

    def fetch_attendance(self):
        if not self._connected:
            self.connect()
            self.disconnect()
        # Return copies so callers mutating the list don't corrupt the fixture
        return list(self._records)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


def make_adapter(device_row, mock=False, **mock_kwargs):
    """Factory: build the right adapter type for a zk_devices row (a dict-like
    with ip/port/comm_password/timeout_seconds). `mock=True` is used by tests
    and by any explicit "test without hardware" action in a future UI."""
    ip = device_row.get('ip')
    port = int(device_row.get('port') or 4370)
    password = device_row.get('comm_password') or 0
    timeout = int(device_row.get('timeout_seconds') or 10)
    if mock:
        return MockZKAdapter(ip=ip, port=port, password=password, timeout=timeout, **mock_kwargs)
    return ZKDeviceAdapter(ip=ip, port=port, password=password, timeout=timeout)
