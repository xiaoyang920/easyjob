"""Generate the Python contract from the same IDL used by Maven."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
committed = root / 'python-agent/app/rpc/generated'
temporary = tempfile.TemporaryDirectory() if '--check' in sys.argv else None
output = Path(temporary.name) if temporary else committed
output.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, '-m', 'grpc_tools.protoc', f'-I{root / "contracts"}',
                f'--python_out={output}', f'--grpc_python_out={output}',
                str(root / 'contracts/easyjob_rpc.proto')], check=True)
stub = output / 'easyjob_rpc_pb2_grpc.py'
stub.write_text(stub.read_text(encoding='utf-8').replace(
    'import easyjob_rpc_pb2 as', 'from . import easyjob_rpc_pb2 as'), encoding='utf-8')
if temporary:
    changed = [path.name for path in output.iterdir() if not (committed / path.name).exists()
               or path.read_text(encoding='utf-8') != (committed / path.name).read_text(encoding='utf-8')]
    temporary.cleanup()
    if changed:
        raise SystemExit('RPC contracts need regeneration: ' + ', '.join(changed))
    print('RPC contracts match the shared IDL.')
else:
    print('Generated Python RPC contracts.')
