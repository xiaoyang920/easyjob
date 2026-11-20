"""Install the pinned ip2region databases in the ignored local runtime directory."""
from hashlib import file_digest
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from urllib.request import urlopen


SOURCE = 'https://raw.githubusercontent.com/lionsoul2014/ip2region/v3.16.0/data/'
FILES = {
    'ip2region_v4.xdb': '59d4ce4ffd9dfcab94ff08dd0fa842e3cc7f19684f16a12396e80a0226a5d3a7',
    'ip2region_v6.xdb': '5859527ac7a44b9207d08e303b3d10634d01d0a5ced85dc3f17928c40829877c',
}


def checksum(path):
    with path.open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def install(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        destination = directory / name
        if destination.is_file() and checksum(destination) == expected:
            print(f'{name}: verified')
            continue
        with NamedTemporaryFile(dir=directory, delete=False) as output:
            staged = Path(output.name)
        try:
            with urlopen(SOURCE + name, timeout=30) as source, staged.open('wb') as output:
                copyfileobj(source, output)
            if checksum(staged) != expected:
                raise ValueError(f'Checksum mismatch for {name}')
            staged.chmod(0o644)
            staged.replace(destination)
            print(f'{name}: installed')
        finally:
            staged.unlink(missing_ok=True)


if __name__ == '__main__':
    install(Path(__file__).resolve().parents[1] / 'temp' / 'ip-location')
