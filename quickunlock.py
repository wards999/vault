"""Quick Unlock: re-open a database that was already unlocked this session with Touch ID (macOS) or
Windows Hello (fingerprint, face or PIN), like KeePassXC.

The master password is never written anywhere. After a normal unlock it's kept in memory,
encrypted, until Vault quits; Touch ID / Windows Hello has to approve before Vault decrypts it again.

    verifier = get_verifier()           # None if this computer has neither
    verifier.name                       # "Touch ID" / "Windows Hello"
    pending = verifier.verify(window_handle, "unlock your database")
    pending.result()                    # None while waiting, then (approved, message)
"""
import hashlib
import sys
import uuid

from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes


class Sealed:
    """A master password held in memory for Quick Unlock, encrypted with a random key."""

    def __init__(self, path, keyfile, password):
        self.path, self.keyfile = path, keyfile
        self._key = get_random_bytes(32)
        cipher = AES.new(self._key, AES.MODE_GCM)
        self._nonce = cipher.nonce
        self._data, self._tag = cipher.encrypt_and_digest(password.encode("utf-8"))

    def matches(self, path, keyfile):
        return self.path == path and (self.keyfile or "") == (keyfile or "")

    def password(self):
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=self._nonce)
        return cipher.decrypt_and_verify(self._data, self._tag).decode("utf-8")


class _Pending:
    def __init__(self):
        self._result = None

    def finish(self, approved, message=""):
        if self._result is None:
            self._result = (approved, message)

    def result(self):
        return self._result


# ---------------------------------------------------------------- Windows Hello

def _pinterface_iid(signature):
    """IID of a parameterised WinRT interface such as IAsyncOperation<T> (the WinRT type system's
    SHA-1 based rule)."""
    namespace = uuid.UUID("11f47ad5-7b73-42c0-abae-878b1e16adee").bytes
    h = bytearray(hashlib.sha1(namespace + signature.encode()).digest()[:16])
    h[6] = (h[6] & 0x0F) | 0x50
    h[8] = (h[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(h))


_ASYNC_OPERATION = "{9fc2b0bb-e446-44e2-aa61-9cab8f636af2}"
_UI = "Windows.Security.Credentials.UI."
IID_ASYNC_VERIFICATION = _pinterface_iid(
    f"pinterface({_ASYNC_OPERATION};enum({_UI}UserConsentVerificationResult;i4))")
IID_ASYNC_AVAILABILITY = _pinterface_iid(
    f"pinterface({_ASYNC_OPERATION};enum({_UI}UserConsentVerifierAvailability;i4))")
IID_ASYNC_INFO = uuid.UUID("00000036-0000-0000-c000-000000000046")
IID_STATICS = uuid.UUID("af4f3f91-564c-4ddc-b8b5-973447627c65")  # IUserConsentVerifierStatics
IID_INTEROP = uuid.UUID("39e050c3-4e74-441a-8dc0-b81104df949c")  # IUserConsentVerifierInterop

_HELLO_MESSAGES = {  # UserConsentVerificationResult
    1: "No Windows Hello device is available.",
    2: "Windows Hello isn't set up. Set it up in Windows Settings → Accounts → Sign-in options.",
    3: "Windows Hello is turned off by your organisation.",
    4: "Windows Hello is busy. Try again.",
    5: "Too many attempts. Use your master password.",
    6: "",  # cancelled
}


class WindowsHello:
    name = "Windows Hello"

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes
        combase = ctypes.WinDLL("combase")
        combase.RoInitialize.restype = ctypes.c_long  # already initialised by Qt: ignore the result
        combase.RoInitialize(0)
        self._create = combase.WindowsCreateString
        self._create.argtypes = [wintypes.LPCWSTR, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        self._create.restype = ctypes.HRESULT
        self._delete = combase.WindowsDeleteString
        self._delete.argtypes = [ctypes.c_void_p]
        self._factory = combase.RoGetActivationFactory
        self._factory.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        self._factory.restype = ctypes.HRESULT

    # -- COM plumbing
    def _hstring(self, text):
        h = self.ct.c_void_p()
        self._create(text, len(text), self.ct.byref(h))
        return h

    def _method(self, obj, index, *argtypes):
        vtable = self.ct.cast(obj, self.ct.POINTER(self.ct.POINTER(self.ct.c_void_p)))[0]
        proto = self.ct.WINFUNCTYPE(self.ct.HRESULT, self.ct.c_void_p, *argtypes)
        return lambda *args: proto(vtable[index])(obj, *args)

    def _release(self, obj):
        if obj:
            vtable = self.ct.cast(obj, self.ct.POINTER(self.ct.POINTER(self.ct.c_void_p)))[0]
            self.ct.WINFUNCTYPE(self.ct.c_ulong, self.ct.c_void_p)(vtable[2])(obj)

    def _query(self, obj, iid):
        out = self.ct.c_void_p()
        self._method(obj, 0, self.ct.c_char_p, self.ct.POINTER(self.ct.c_void_p))(iid.bytes_le, self.ct.byref(out))
        return out

    def _get_factory(self, iid):
        name = self._hstring("Windows.Security.Credentials.UI.UserConsentVerifier")
        try:
            out = self.ct.c_void_p()
            self._factory(name, iid.bytes_le, self.ct.byref(out))
            return out
        finally:
            self._delete(name)

    def _async_state(self, operation):
        """(finished, value or None): polls an IAsyncOperation<enum> without blocking."""
        info = self._query(operation, IID_ASYNC_INFO)
        try:
            status = self.ct.c_int()
            self._method(info, 7, self.ct.POINTER(self.ct.c_int))(self.ct.byref(status))  # get_Status
        finally:
            self._release(info)
        if status.value == 0:  # Started
            return False, None
        if status.value != 1:  # Canceled or Error
            return True, None
        value = self.ct.c_int()
        self._method(operation, 8, self.ct.POINTER(self.ct.c_int))(self.ct.byref(value))  # GetResults
        return True, value.value

    # -- public
    def available(self, timeout=2.0):
        import time
        try:
            statics = self._get_factory(IID_STATICS)
            operation = self.ct.c_void_p()
            self._method(statics, 6, self.ct.POINTER(self.ct.c_void_p))(self.ct.byref(operation))
            self._release(statics)
            end = time.monotonic() + timeout
            try:
                while time.monotonic() < end:
                    done, value = self._async_state(operation)
                    if done:
                        return value == 0  # UserConsentVerifierAvailability.Available
                    time.sleep(0.01)
            finally:
                self._release(operation)
        except OSError:
            pass
        return False

    def verify(self, window_handle, reason):
        pending = _Pending()
        try:
            interop = self._get_factory(IID_INTEROP)
            message = self._hstring(f"Vault: {reason}")
            operation = self.ct.c_void_p()
            try:
                self._method(interop, 6, self.ct.c_void_p, self.ct.c_void_p, self.ct.c_char_p,
                             self.ct.POINTER(self.ct.c_void_p))(
                    window_handle, message, IID_ASYNC_VERIFICATION.bytes_le, self.ct.byref(operation))
            finally:
                self._delete(message)
                self._release(interop)
        except OSError as exc:
            pending.finish(False, f"Windows Hello couldn't start ({exc.strerror or exc}).")
            return pending
        windows = self

        class HelloPending(_Pending):
            def result(self):
                if self._result is None:
                    try:
                        done, value = windows._async_state(operation)
                    except OSError:
                        done, value = True, None
                    if done:
                        windows._release(operation)
                        if value == 0:
                            self.finish(True)
                        else:
                            self.finish(False, _HELLO_MESSAGES.get(value, "Windows Hello didn't work. Use your master password."))
                return self._result

        hello = HelloPending()
        return hello


# ---------------------------------------------------------------- Touch ID

class TouchID:
    name = "Touch ID"
    POLICY = 1  # LAPolicyDeviceOwnerAuthenticationWithBiometrics

    def __init__(self):
        from LocalAuthentication import LAContext  # pyobjc-framework-LocalAuthentication
        self._context_class = LAContext

    def available(self):
        try:
            ok, _error = self._context_class.new().canEvaluatePolicy_error_(self.POLICY, None)
            return bool(ok)
        except Exception:
            return False

    def verify(self, window_handle, reason):
        pending = _Pending()
        context = self._context_class.new()
        context.setLocalizedFallbackTitle_("Use master password")

        def reply(success, error):  # called on another thread
            if success:
                pending.finish(True)
            elif error is not None and error.code() in (-2, -3, -4):  # cancelled / fallback / system cancel
                pending.finish(False, "")
            else:
                pending.finish(False, "Touch ID didn't work. Use your master password.")

        pending._context = context  # keep it alive until the reply arrives
        try:
            context.evaluatePolicy_localizedReason_reply_(self.POLICY, reason, reply)
        except Exception as exc:
            pending.finish(False, f"Touch ID couldn't start ({exc}).")
        return pending


_verifier = False


def get_verifier():
    """The fingerprint/face verifier for this computer, or None (checked once)."""
    global _verifier
    if _verifier is False:
        _verifier = None
        try:
            candidate = WindowsHello() if sys.platform == "win32" else TouchID() if sys.platform == "darwin" else None
            if candidate is not None and candidate.available():
                _verifier = candidate
        except Exception:
            pass
    return _verifier
