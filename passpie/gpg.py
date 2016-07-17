from tempfile import mkdtemp, NamedTemporaryFile
import re
import os

from .proc import run
from .utils import which, yaml_load


DEFAULT_GPG_HOMEDIR = os.path.expanduser('~/.gnupg')
DEVNULL = open(os.devnull, 'w')
DEFAULT_KEY_LENGTH = 4096
DEFAULT_EMAIL = "passpie@localhost"
DEFAULT_NAME = "Passpie"
DEFAULT_COMMENT = "Generated by Passpie"
DEFAULT_EXPIRE_DATE = 0
KEY_INPUT = u"""Key-Type: RSA
Key-Length: {}
Subkey-Type: RSA
Name-Comment: {}
Passphrase: {}
Name-Real: {}
Name-Email: {}
Expire-Date: {}
%commit
"""


def make_key_input(**kwargs):
    kwargs.setdefault("key_length", DEFAULT_KEY_LENGTH)
    kwargs.setdefault("name", DEFAULT_NAME)
    kwargs.setdefault("email", DEFAULT_EMAIL)
    kwargs.setdefault("comment", DEFAULT_COMMENT)
    kwargs.setdefault("expire_date", DEFAULT_EXPIRE_DATE)
    key_input = KEY_INPUT.format(
        kwargs["key_length"],
        kwargs["comment"],
        kwargs["passphrase"],
        kwargs["name"],
        kwargs["email"],
        kwargs["expire_date"],
    )
    return key_input, kwargs


def list_keys(homedir, emails=False):
    command = [
        which("gpg2", "gpg"),
        '--no-tty',
        "--batch",
        '--fixed-list-mode',
        '--with-colons',
        "--homedir", homedir,
        "--list-keys",
        "--fingerprint",
    ]
    response = run(command)
    keys = []
    for line in response.std_out.splitlines():
        if emails is True:
            mobj = re.search(r'uid:.*?<(.*?@.*?)>:', line)
        else:
            mobj = re.search(r'fpr:.*?(\w+):', line)
        if mobj:
            found = mobj.group(1)
            keys.append(found)
    return keys


def export_keys(homedir, fingerprint=""):
    command = [
        which('gpg2', 'gpg'),
        '--no-tty',
        '--batch',
        '--homedir', homedir,
        '--export',
        '--armor',
        fingerprint,
    ]
    command_secret = [
        which('gpg2', 'gpg'),
        '--no-tty',
        '--batch',
        '--homedir', homedir,
        '--export-secret-keys',
        '--armor',
        fingerprint,
    ]
    ret = run(command)
    ret_secret = run(command_secret)
    return ret.std_out + ret_secret.std_out


def generate_keys(values):
    homedir = mkdtemp()
    command = [
        which('gpg2', 'gpg'),
        '--batch',
        '--no-tty',
        '--homedir', homedir,
        '--gen-key',
    ]
    recipient = values.get("email", DEFAULT_EMAIL)
    key_input, _ = make_key_input(**values)
    run(command, data=key_input)
    return export_keys(homedir, recipient)


def encrypt_data(data, recipient, homedir):
    command = [
        which('gpg2', 'gpg'),
        '--batch',
        '--no-tty',
        '--always-trust',
        '--armor',
        '--recipient', recipient,
        '--homedir', homedir,
        '--encrypt'
    ]
    ret = run(command, data=data)
    return ret.std_out


def decrypt_data(data, recipient, homedir, passphrase):
    command = [
        which('gpg2', 'gpg'),
        '--batch',
        '--no-tty',
        '--always-trust',
        '--recipient', recipient,
        '--homedir', homedir,
        '--passphrase', passphrase,
        '-o', '-',
        '-d', '-',
    ]
    response = run(command, data=data)
    return response.std_out


def import_keys(keyspath, homedir):
    cmd = (
        which("gpg2", "gpg"),
        "--no-tty",
        "--batch",
        "--homedir", homedir,
        '--allow-secret-key-import',
        "--import", keyspath,
    )
    response = run(cmd)
    return response


def setup_homedir(homedir, keys):
    if homedir:
        return homedir
    elif keys:
        homedir = mkdtemp()
        for key in keys:
            keysfile = NamedTemporaryFile(delete=False, dir=homedir, suffix=".asc")
            keysfile.write(key.encode("utf-8"))
            import_keys(keysfile.name, homedir)
        return homedir
    else:
        raise ValueError("Homedir not set and keys not found, set PASSPIE_GPG_HOMEDIR")


class GPG(object):

    def __init__(self, path, passphrase, homedir, recipient):
        self.path = path
        self.keys = yaml_load(self.path)
        self.default_homedir = homedir
        self.homedir = setup_homedir(self.default_homedir, self.keys)
        self.passphrase = passphrase
        self.recipient = recipient

    def write(self):
        # if not self.default_homedir and self.is_modified():
        #     return yaml_dump(self.export(), self.path)
        pass

    def is_modified(self):
        return len(self.list_keys()) != len(self.keys) and self.homedir

    def list_keys(self, emails=True):
        return list_keys(self.homedir, emails=emails)

    def export(self):
        keys = []
        for fingerprint in self.list_keys(emails=False):
            keyasc = export_keys(self.homedir, fingerprint)
            keys.append(keyasc)
        return keys

    def encrypt(self, data):
        return encrypt_data(data, self.recipient, self.homedir)

    def decrypt(self, data):
        return decrypt_data(data, self.recipient, self.homedir, self.passphrase)

    def ensure(self):
        # Test recipient
        if self.recipient not in (self.list_keys() + self.list_keys(False)):
            message = "Recipient '{}' not found in homedir".format(self.recipient)
            raise ValueError(message)

        # Test passphrase
        if self.passphrase:
            if not self.decrypt(self.encrypt("OK")) == "OK":
                raise ValueError("Wrong passphrase")
        else:
            raise ValueError("Passphrase not set")
