"""Prepared Windows Authenticode adapter, not connected to BAT execution.

The .sig is a UTF-16LE Authenticode-signed COMMENT container of the manifest's
SHA-256. It is DATA, passed as bytes to Get-AuthenticodeSignature, never executed.
Default empty/disabled external trust continues to reject all real updates.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .lifecycle import Blocked, ordinary_absolute
from .zip_update import PublisherEvidence, Trust, _object

HEADER = '# NewsFlow-BAT-Manifest-Digest-v1'
BEGIN = '# SIG # Begin signature block'
END = '# SIG # End signature block'


def manifest_digest(content: bytes, signature: bytes) -> str:
    if not content or not 0 < len(signature) <= 65536 or not signature.startswith(b'\xff\xfe'):
        raise Blocked('invalid-signed-comment-container')
    try:
        lines = signature[2:].decode('utf-16le').splitlines()
        if (len(lines) < 5 or lines[0] != HEADER or lines[1] != '# ' + hashlib.sha256(content).hexdigest()
                or lines[2] != BEGIN or lines[-1] != END
                or any(not re.fullmatch(r'# [A-Za-z0-9+/=]+', line) for line in lines[3:-1])):
            raise Blocked('manifest-comment-binding-mismatch')
        # Syntax only; Windows cryptographic verification is still mandatory.
        if not base64.b64decode(''.join(line[2:] for line in lines[3:-1]), validate=True):
            raise Blocked('empty-signature-block')
        return lines[1][2:]
    except (UnicodeError, binascii.Error, ValueError) as error:
        if isinstance(error, Blocked):
            raise
        raise Blocked('invalid-signed-comment-container') from None


def _windows_acl_attest(path):
    """Read-only current-owner/protected-DACL check; never create/relax ACLs."""
    from newsflow.distribution.windows_profile import _api, current_sid
    _, _, _, security = _api()
    owner = security.ConvertSidToStringSid(current_sid())
    descriptor = security.GetFileSecurity(str(path), security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
    acl = descriptor.GetSecurityDescriptorDacl()
    if (security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) != owner or acl is None
            or not descriptor.GetSecurityDescriptorControl()[0] & security.SE_DACL_PROTECTED):
        raise Blocked('untrusted-anchor-owner-or-acl')
    allowed = {owner, 'S-1-5-18', 'S-1-5-32-544'}
    owner_access = False
    for number in range(acl.GetAceCount()):
        ace = acl.GetAce(number)
        who = security.ConvertSidToStringSid(ace[2])
        if ace[0][0] != security.ACCESS_ALLOWED_ACE_TYPE or who not in allowed:
            raise Blocked('untrusted-anchor-ace')
        owner_access |= who == owner and (ace[1] & 0x1F01FF) == 0x1F01FF
    if not owner_access:
        raise Blocked('anchor-owner-access-missing')


@dataclass(frozen=True)
class PreparedAnchor:
    trust: Trust
    verifier_script_sha256: str


def load_anchor(profile: Path, *, attestor=None) -> PreparedAnchor:
    """Fixed path outside ZIP/program. No writes, account lookup or provisioning."""
    profile = ordinary_absolute(profile)
    security = ordinary_absolute(profile / 'security')
    anchor = ordinary_absolute(security / 'publisher-trust.json')
    cert = ordinary_absolute(security / 'publisher.cer')
    if not profile.is_dir() or not security.is_dir() or not anchor.is_file():
        raise Blocked('external-publisher-anchor-missing')
    attest = _windows_acl_attest if attestor is None else attestor
    try:
        for path in (profile, security, anchor):
            attest(path)
        if not 0 < anchor.stat().st_size <= 8192:
            raise Blocked('anchor-size')
        value = json.loads(anchor.read_bytes(), object_pairs_hook=_object)
        if (set(value) != {'schemaVersion', 'channel', 'updatesEnabled', 'publisherCertificateSha256',
                          'certificateFile', 'verifierScriptSha256', 'offlineValidationAccepted'}
                or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
                or value['channel'] != 'private-bat' or value['updatesEnabled'] is not True
                or value['offlineValidationAccepted'] is not True or value['certificateFile'] != 'publisher.cer'
                or not re.fullmatch('[0-9a-f]{64}', value['publisherCertificateSha256'])
                or not re.fullmatch('[0-9a-f]{64}', value['verifierScriptSha256'])):
            raise Blocked('updates-disabled-or-unprovisioned-publisher')
        if not cert.is_file() or not 0 < cert.stat().st_size <= 65536:
            raise Blocked('external-publisher-certificate-missing')
        attest(cert)
        if hashlib.sha256(cert.read_bytes()).hexdigest() != value['publisherCertificateSha256']:
            raise Blocked('external-certificate-pin-mismatch')
        return PreparedAnchor(Trust(True, value['publisherCertificateSha256']), value['verifierScriptSha256'])
    except (OSError, TypeError, ValueError, KeyError) as error:
        if isinstance(error, Blocked):
            raise
        raise Blocked('external-publisher-anchor-rejected') from None


class WindowsContentReader:
    """Fixed verifier script only; received signed content is never a command.

    Windows certificate APIs may consult system caches/network. This prepared
    adapter is not an independently qualified cache-only verifier. The external
    anchor's offline qualification must remain false until separately verified.
    """
    def __init__(self, expected_script_sha256):
        self.expected_script_sha256 = expected_script_sha256

    def read(self, signature: bytes) -> dict:
        if os.name != 'nt' or not re.fullmatch('[0-9a-f]{64}', self.expected_script_sha256):
            raise Blocked('windows-verifier-not-provisioned')
        script = ordinary_absolute(Path(__file__).with_name('verify_manifest_content.ps1'))
        if hashlib.sha256(script.read_bytes()).hexdigest() != self.expected_script_sha256:
            raise Blocked('verifier-script-pin-mismatch')
        system_root = ordinary_absolute(Path(os.environ.get('SystemRoot', '')))
        powershell = ordinary_absolute(system_root / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        if not powershell.is_file():
            raise Blocked('windows-signature-host-missing')
        environment = {'SystemRoot': str(system_root), 'WINDIR': str(system_root),
                       'PATH': str(system_root / 'System32')}
        try:
            result = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
                '-File', str(script)], input=json.dumps({'content': base64.b64encode(signature).decode('ascii')}).encode(),
                cwd=script.parent, env=environment, capture_output=True, timeout=30, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode != 0 or len(result.stdout) > 4096:
                raise Blocked('windows-signature-rejected')
            return json.loads(result.stdout.decode('utf-8-sig'), object_pairs_hook=_object)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise Blocked('windows-signature-unavailable-or-rejected') from None


class WindowsCommentSignatureVerifier:
    def __init__(self, anchor: PreparedAnchor, *, reader=None):
        if (anchor.trust.enabled is not True
                or not re.fullmatch('[0-9a-f]{64}', anchor.trust.certificate_sha256)):
            raise Blocked('publisher-trust-missing')
        self.anchor = anchor
        self.reader = reader if reader is not None else WindowsContentReader(anchor.verifier_script_sha256)

    def verify(self, content: bytes, signature: bytes) -> PublisherEvidence:
        digest = manifest_digest(content, signature)
        observed = self.reader.read(signature)
        if (set(observed) != {'status', 'certificateSha256', 'timestamped', 'codeSigning', 'containerSha256'}
                or observed['status'] != 'Valid'
                or observed['certificateSha256'] != self.anchor.trust.certificate_sha256
                or observed['timestamped'] is not True or observed['codeSigning'] is not True
                or observed['containerSha256'] != hashlib.sha256(signature).hexdigest()):
            raise Blocked('publisher-or-content-signature-mismatch')
        return PublisherEvidence(observed['certificateSha256'], digest, True, True, True)


def prepare_update_context(profile: Path):
    """Bridge to existing zip_update.validate(..., trust, verifier=verifier).

    Not wired to contract_entry or any installer. Default absent/disabled anchor
    fails before Windows verification or update file access.
    """
    anchor = load_anchor(profile)
    return anchor.trust, WindowsCommentSignatureVerifier(anchor)
