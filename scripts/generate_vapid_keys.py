"""Generate a fresh VAPID key pair for Web Push.

Run this ONCE before enabling Web Push. Copy the two values to:
- locally: a `.env` file or your shell as env vars
- production: Render dashboard -> Environment Variables

    python scripts/generate_vapid_keys.py
"""
import base64

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("pip install cryptography")
    raise SystemExit(1)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main():
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key()

    # PEM-formatted private key, urlsafe-b64 — what pywebpush expects in
    # VAPID_PRIVATE_KEY as the raw PEM string (or a path to a file).
    priv_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    # The browser needs the public key as urlsafe-base64 of the uncompressed
    # SEC1 point (65 bytes: 0x04 || X || Y).
    pub_raw = public.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64url = _b64url(pub_raw)

    print("=" * 60)
    print("VAPID KEYS GENERATED. Set these as environment variables.")
    print("=" * 60)
    print()
    print("VAPID_PUBLIC_KEY (browser uses this):")
    print(pub_b64url)
    print()
    print("VAPID_PRIVATE_KEY (server signs with this; paste the whole PEM):")
    print(priv_pem)
    print()
    print("Optional:")
    print("VAPID_CLAIM_EMAIL=mailto:you@example.com")
    print()
    print("Locally: add to .env file. On Render: dashboard > Environment.")


if __name__ == "__main__":
    main()
