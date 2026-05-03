"""Generates a self-signed SSL cert for divAI mobile HTTPS. Run once, then trust on iPhone."""
import os, sys, socket, ipaddress, datetime

CERT_FILE = os.path.join(os.path.dirname(__file__), "divai.crt")
KEY_FILE  = os.path.join(os.path.dirname(__file__), "divai.key")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def generate():
    if os.path.exists(KEY_FILE) and os.path.exists(CERT_FILE):
        print("  [CERT] divai.key + divai.crt already exist — skipping generation.")
        return True

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        import subprocess
        print("  [CERT] Installing cryptography...")
        subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], check=True)
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

    ip = get_local_ip()
    print(f"  [CERT] Generating self-signed cert for {ip}...")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME,       u"divAI Local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"divAI"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.IPv4Address(ip)),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.DNSName("localhost"),
        ]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ))
    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"  [CERT] ✓ Cert generated for {ip}")
    print()
    print("  ┌─ iPhone setup (one-time) ────────────────────────────────────┐")
    print(f"  │  1. AirDrop  divai.crt  to your iPhone                      │")
    print(f"  │  2. Settings → General → VPN & Device Management → Install  │")
    print(f"  │  3. Settings → General → About → Certificate Trust Settings │")
    print(f"  │     → Enable divAI Local                                     │")
    print(f"  │  4. Open Safari → https://{ip}:8443                         │")
    print(f"  └─────────────────────────────────────────────────────────────┘")
    print()
    return True

if __name__ == "__main__":
    generate()
