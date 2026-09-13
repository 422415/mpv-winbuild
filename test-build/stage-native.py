"""Bundle the native player and its imported non-system DLLs for portable tests."""
from collections import deque
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

prefix, runtime, output = map(Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)
info = output / 'build-info'
info.mkdir(exist_ok=True)
config = Path('build-mpv/config.h').read_text()
for feature in ('D3D11', 'VULKAN', 'CUDA_HWACCEL', 'CUDA_INTEROP', 'ASS_RENDER_THREAD_COUNT',
                'ASS_BLUR_DEFERRED', 'ASS_COMPOSITE_DEFERRED', 'ASS_OUTLINE_DEFERRED'):
    if not re.search(rf'^#define HAVE_{feature} 1$', config, re.M):
        raise RuntimeError(f'Required AJN feature missing: {feature}')

search = [prefix / 'bin', runtime / 'bin']
available = {directory: {p.name.lower(): p for p in directory.glob('*.dll')}
             for directory in search}
system = Path(os.environ['WINDIR']) / 'System32'
system_names = {p.name.lower() for p in system.glob('*.dll')}
queue = deque([prefix / 'bin/mpv.exe', prefix / 'bin/libmpv-2.dll'])
console = prefix / 'bin/mpv.com'
if console.is_file():
    queue.append(console)
copied = {}
while queue:
    source = queue.popleft()
    key = source.name.lower()
    if key in copied:
        continue
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copy2(source, output / source.name)
    copied[key] = str(source)
    imports = subprocess.check_output(['objdump', '-p', str(source)], text=True,
                                      encoding='utf-8', errors='replace')
    for name in re.findall(r'DLL Name:\s*(\S+)', imports):
        key = name.lower()
        candidate = next((available[d][key] for d in search if key in available[d]), None)
        if candidate:
            queue.append(candidate)
        elif key not in system_names and not key.startswith(('api-ms-', 'ext-ms-')):
            raise RuntimeError(f'Unresolved dependency {name} imported by {source.name}')

shutil.copy2('build-mpv/config.h', info / 'mpv-config.h')
for name in ('intro-buildoptions.json', 'intro-dependencies.json'):
    shutil.copy2(Path('build-mpv/meson-info') / name, info / name)
shutil.copytree(runtime / 'share/licenses', output / 'licenses/MSYS2', dirs_exist_ok=True)
for repo, files in {'mpv-source': ['Copyright', 'LICENSE.GPL', 'LICENSE.LGPL'],
                    'libass-source': ['COPYING']}.items():
    folder = output / 'licenses' / repo
    folder.mkdir(parents=True, exist_ok=True)
    for name in files:
        shutil.copy2(Path(repo) / name, folder / name)

player = output.resolve() / 'mpv.exe'
env = dict(os.environ, PATH=str(system))
for name, arguments in (
    ('version', ['--version']),
    ('null-playback', ['--no-config', '--vo=null', '--ao=null', '--frames=2', '--load-select=no',
                       '--msg-level=all=v,ao/wasapi=debug',
                       'av://lavfi:color=c=black:s=640x360:r=24:d=1']),
):
    result = subprocess.run([str(player), *arguments], capture_output=True,
                            text=True, encoding='utf-8', errors='replace',
                            timeout=30, env=env)
    (info / (name + '.txt')).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        debugger = shutil.which('gdb')
        if debugger:
            try:
                trace = subprocess.run([debugger, '--batch', '-ex', 'set pagination off',
                    '-ex', 'run', '-ex', 'thread apply all bt', '--args', str(player), *arguments],
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    timeout=60, env=env)
                (info / (name + '-backtrace.txt')).write_text(
                    trace.stdout + trace.stderr, encoding='utf-8')
            except subprocess.TimeoutExpired:
                (info / (name + '-backtrace.txt')).write_text('Debugger timed out.\n')
        raise RuntimeError(f'{name} failed: {result.returncode}; see build-info')

# The Server runner has no audio endpoint. Keep its default-script/WASAPI
# teardown check visible, alongside stock MSYS2 mpv as an independent control.
# Desktop playback (including the default scripts) is validated separately on
# real Windows hardware before distributing a complete AJN test package.
desktop_results = []
desktop_args = ['--no-config', '--vo=null', '--ao=null', '--frames=2',
                '--msg-level=all=v,ao/wasapi=debug',
                'av://lavfi:color=c=black:s=640x360:r=24:d=1']
for name, executable in [('ajn', player), ('msys2-stock', runtime / 'bin/mpv.exe')]:
    probe = subprocess.run([str(executable), *desktop_args], capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=30, env=env)
    (info / (name + '-server-desktop-probe.txt')).write_text(
        probe.stdout + probe.stderr, encoding='utf-8')
    desktop_results.append({'player': name, 'exit_code': probe.returncode,
        'passed': probe.returncode == 0})
(info / 'server-desktop-probes.json').write_text(json.dumps(desktop_results, indent=2) + '\n')
if any(not r['passed'] for r in desktop_results):
    print('WARNING: Server desktop audio cleanup check failed; see server-desktop-probes.json.')

(info / 'runtime-origins.json').write_text(json.dumps(copied, indent=2) + '\n')
hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
          for p in output.iterdir() if p.is_file()}
(info / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
print(f'Staged {len(copied)} native files with complete import dependencies.')
