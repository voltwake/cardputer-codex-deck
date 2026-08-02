from __future__ import annotations

from typing import Protocol


KEYCHAIN_SERVICE = "com.voltwake.cardbridge.pairing"


class TokenStore(Protocol):
    def get(self, device_id: str) -> str | None: ...

    def put(self, device_id: str, token: str) -> None: ...

    def delete(self, device_id: str) -> None: ...


class KeychainTokenStore:
    """Store pairing secrets in the current user's login Keychain."""

    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        try:
            import Security
        except ImportError as exc:  # pragma: no cover - only reachable in broken macOS packaging
            raise RuntimeError("macOS Security framework is unavailable") from exc
        self._security = Security
        self.service = service

    def get(self, device_id: str) -> str | None:
        security = self._security
        status, data = security.SecItemCopyMatching(
            {
                **self._query(device_id),
                security.kSecReturnData: True,
                security.kSecMatchLimit: security.kSecMatchLimitOne,
            },
            None,
        )
        if status == security.errSecItemNotFound:
            return None
        self._require_success(status, "read")
        try:
            return bytes(data).decode("ascii")
        except (TypeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"invalid pairing token in Keychain for {device_id}") from exc

    def put(self, device_id: str, token: str) -> None:
        security = self._security
        attributes = {
            **self._query(device_id),
            security.kSecValueData: token.encode("ascii"),
            security.kSecAttrAccessible: security.kSecAttrAccessibleAfterFirstUnlock,
        }
        status, _item = security.SecItemAdd(attributes, None)
        if status == security.errSecDuplicateItem:
            status = security.SecItemUpdate(
                self._query(device_id),
                {security.kSecValueData: token.encode("ascii")},
            )
        self._require_success(status, "store")

    def delete(self, device_id: str) -> None:
        security = self._security
        status = security.SecItemDelete(self._query(device_id))
        if status not in (security.errSecSuccess, security.errSecItemNotFound):
            self._require_success(status, "delete")

    def _query(self, device_id: str) -> dict[object, object]:
        security = self._security
        return {
            security.kSecClass: security.kSecClassGenericPassword,
            security.kSecAttrService: self.service,
            security.kSecAttrAccount: device_id,
        }

    def _require_success(self, status: int, action: str) -> None:
        security = self._security
        if status == security.errSecSuccess:
            return
        message = security.SecCopyErrorMessageString(status, None)
        raise RuntimeError(f"cannot {action} pairing token in Keychain: {message} ({status})")
