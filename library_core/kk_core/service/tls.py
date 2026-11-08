"""Certificado TLS self-signed para o daemon servir HTTPS na LAN.

HTTPS é necessário para o Safari habilitar AudioWorklet / Wake Lock (recursos de
"contexto seguro"). O certificado é self-signed: no iPhone, Safari mostra um aviso
uma vez → "Visitar mesmo assim" → a página passa a ser contexto seguro (mesmo com
cert não confiável), liberando o AudioWorklet.

Gerado com `cryptography` (já dependência do licenciamento). Guardado em data_dir.
"""
from __future__ import annotations

import datetime
import ipaddress
from pathlib import Path


def ensure_cert(data_dir: Path, extra_ips: list[str] | None = None) -> tuple[str, str]:
    """Garante (certfile, keyfile) PEM em data_dir; gera se faltar. SAN inclui
    localhost + 127.0.0.1 + IPs informados (ex.: IP da LAN)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    cert_path = data_dir / "daemon_cert.pem"
    key_path = data_dir / "daemon_key.pem"
    if cert_path.exists() and key_path.exists():
        return str(cert_path), str(key_path)

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Videoke Familia Silva")])

    san: list = [x509.DNSName("localhost")]
    for ip in ["127.0.0.1", *(extra_ips or [])]:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass

    now = datetime.datetime.utcnow()
    # iOS 13+ exige: SAN, EKU serverAuth e validade <= 825 dias.
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=820))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        # CA:TRUE → iOS mostra o botão de confiar em "Certificados Confiáveis".
        # Self-signed servindo como sua própria âncora (uso doméstico).
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True,
                                     content_commitment=False, data_encipherment=False,
                                     key_agreement=False, key_cert_sign=True, crl_sign=True,
                                     encipher_only=False, decipher_only=False), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)
